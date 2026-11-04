"""Edit page objects without covering old text or modifying source files.

Only top-level text/image objects are selected. Forms, paths, clipping and
scanned text are not interpreted as editable paragraphs. This is an editor,
not a secure-redaction implementation.
"""
from dataclasses import dataclass
from io import BytesIO
import math
import ctypes

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPalette, QPdfWriter, QTextDocument, QTextOption

from .rendering import ensure_font_support


@dataclass(frozen=True)
class EditableObject:
    index: int
    kind: str
    text: str
    rect: tuple[float, float, float, float]  # left, top, width, height
    size: float = 16
    family: str = 'Segoe UI'
    bold: bool = False
    color: str = '#123b48'
    alignment: str = 'left'
    indices: tuple = ()
    chars: tuple = ()


def prepare_page(data: bytes) -> bytes:
    """Normalize one page to top-left editor coordinates without rasterizing."""
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != 1:
        raise ValueError('محرر الصفحة يحتاج صفحة واحدة.')
    page = reader.pages[0]
    if float(page.get('/UserUnit', 1)) != 1:
        raise ValueError('هذه الصفحة تستخدم وحدات قياس خاصة لا يدعمها محرر الصفحة حاليًا.')
    crop = page.cropbox
    if page.get('/Annots') and (page.rotation or float(crop.left) or float(crop.bottom)):
        raise ValueError('تحرير صفحة مدوّرة أو مقصوصة تحتوي نماذج أو تعليقات غير مدعوم حاليًا؛ لم يتغير المستند.')
    if page.rotation:
        page.transfer_rotation_to_content()
    crop = page.cropbox
    left, bottom = float(crop.left), float(crop.bottom)
    width, height = float(crop.width), float(crop.height)
    if width <= 0 or height <= 0:
        raise ValueError('أبعاد الصفحة غير صالحة.')
    if left or bottom:
        page.add_transformation(Transformation().translate(-left, -bottom))
    page.mediabox = RectangleObject((0, 0, width, height))
    page.cropbox = RectangleObject((0, 0, width, height))
    for name in ('/TrimBox', '/BleedBox', '/ArtBox'):
        if name in page:
            del page[name]
    writer = PdfWriter(); writer.append(reader, import_outline=False)
    writer.pdf_header = max(writer.pdf_header, '%PDF-1.7')
    stream = BytesIO(); writer.write(stream); writer.close()
    return stream.getvalue()


def inspect_page(data: bytes) -> tuple[float, float, list[EditableObject]]:
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            width, height = page.get_size()
            textpage = page.get_textpage()
            try:
                result = []
                for index, obj in enumerate(page.get_objects(max_depth=1, textpage=textpage)):
                    if obj.type not in (raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_IMAGE):
                        continue
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT and raw.FPDFTextObj_GetTextRenderMode(obj) == 3:
                        continue  # searchable OCR text is not the scanned image
                    l, b, r, t = obj.get_bounds()
                    if r <= 0 or t <= 0 or l >= width or b >= height:
                        continue
                    text, size = '', 16.0
                    family, bold, color = 'Segoe UI', False, '#123b48'
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        try:
                            text = obj.extract().strip('\x00\r\n')
                            size = obj.get_font_size()
                            font = obj.get_font()
                            base = font.get_base_name().split('+')[-1]
                            family = base if base in font.STANDARD_FONTS else (font.get_family_name() or base)
                            bold = font.get_weight() >= 600
                            rgba = [ctypes.c_uint() for _ in range(4)]
                            if raw.FPDFPageObj_GetFillColor(obj, *[ctypes.byref(v) for v in rgba]):
                                color = '#%02x%02x%02x' % tuple(v.value for v in rgba[:3])
                        except pdfium.PdfiumError:
                            text = ''
                    result.append(EditableObject(index, 'text' if obj.type == raw.FPDF_PAGEOBJ_TEXT else 'image',
                        text, (l, height-t, max(r-l, .1), max(t-b, .1)), size, family, bold, color))
                return width, height, result
            finally:
                textpage.close()
        finally:
            page.close()


def _remove_objects(data: bytes, indexes: list[int], selected_chars=None) -> bytes:
    if not indexes:
        return data
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            objects = list(page.get_objects(max_depth=1))
            selected = sorted(set(indexes), reverse=True)
            if any(i < 0 or i >= len(objects) or objects[i].type not in (raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_IMAGE) for i in selected):
                raise ValueError('العنصر المحدد غير قابل للتحرير. أعد تحديده من الصفحة.')
            retained = []
            if selected_chars is not None:
                from .textlayout import address
                root_map = {address(o.raw): i for i, o in enumerate(objects)}
                wanted = set(selected_chars)
                textpage = page.get_textpage()
                try:
                    owner_chars = {owner: [] for owner in selected}
                    for char_index in range(textpage.count_chars()):
                        obj = textpage.get_textobj(char_index)
                        owner = root_map.get(address(obj.raw)) if obj is not None else None
                        if owner in owner_chars:
                            owner_chars[owner].append(char_index)
                    # PDF subset fonts often cannot encode individual Unicode
                    # glyphs again. Refuse a partial rewrite instead of silently
                    # producing scrambled text; whole-object edits remain safe.
                    for owner, chars in owner_chars.items():
                        if chars and wanted.intersection(chars) != set(chars):
                            font = objects[owner].get_font()
                            base = font.get_base_name().split('+')[-1]
                            if base not in font.STANDARD_FONTS:
                                raise ValueError('هذا الخط المضمّن لا يسمح بتعديل جزء من عنصر النص بأمان. اختر «عنصر أصلي» وحدده كاملًا؛ لم تتغير الصفحة.')
                    for char_index in range(textpage.count_chars()):
                        obj = textpage.get_textobj(char_index)
                        owner = root_map.get(address(obj.raw)) if obj is not None else None
                        if owner not in selected or char_index in wanted:
                            continue
                        code = raw.FPDFText_GetUnicode(textpage, char_index)
                        if not code or chr(code).isspace(): continue
                        original = objects[owner]
                        if raw.FPDFTextObj_GetTextRenderMode(original) != 0:
                            raise ValueError('هذا العنصر يستخدم تأثيرات خط خاصة. اختر تحديد العنصر كاملًا بدل جزء منه.')
                        x, y = ctypes.c_double(), ctypes.c_double()
                        if not raw.FPDFText_GetCharOrigin(textpage, char_index, ctypes.byref(x), ctypes.byref(y)):
                            raise ValueError('تعذر الاحتفاظ بمواضع بقية حروف العنصر.')
                        handle = raw.FPDFPageObj_CreateTextObj(document, original.get_font(), original.get_font_size())
                        if not handle: raise ValueError('تعذر تقسيم العنصر النصي.')
                        copy = pdfium.PdfObject(handle, pdf=document)
                        encoded = (ctypes.c_ushort * ((len(chr(code).encode('utf-16-le'))//2)+1))()
                        ctypes.memmove(encoded, chr(code).encode('utf-16-le'), len(chr(code).encode('utf-16-le')))
                        if not raw.FPDFText_SetText(copy, encoded):
                            copy.close(); raise ValueError('الخط المضمّن لا يسمح بتقسيم هذا العنصر. اختر العنصر كاملًا.')
                        matrix = original.get_matrix()
                        copy.set_matrix(pdfium.PdfMatrix(matrix.a, matrix.b, matrix.c, matrix.d, x.value, y.value))
                        rgba = [ctypes.c_uint() for _ in range(4)]
                        if raw.FPDFPageObj_GetFillColor(original, *[ctypes.byref(v) for v in rgba]):
                            raw.FPDFPageObj_SetFillColor(copy, *[v.value for v in rgba])
                        retained.append(copy)
                except Exception:
                    for obj in retained: obj.close()
                    raise
                finally:
                    textpage.close()
            # No live PdfTextPage handles while text objects are removed.
            for index in selected:
                obj = objects[index]
                page.remove_obj(obj)
                obj.close()
            for obj in retained:
                page.insert_obj(obj)
            page.gen_content()
            stream = BytesIO(); document.save(stream)
            return stream.getvalue()
        finally:
            page.close()


def _layer(width, height, rect, *, text=None, image=None, size=16, family='Segoe UI', color='#123b48', bold=False,
           alignment='auto', auto_fit=False):
    ensure_font_support()
    x, y, w, h = rect
    if not all(math.isfinite(v) for v in (x, y, w, h, width, height)) or w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > width+.01 or y+h > height+.01:
        raise ValueError('ضع مساحة التعديل داخل حدود الصفحة وبحجم أكبر من الصفر.')
    if text is None and image is None:
        raise ValueError('اختر نصًا أو صورة للإضافة.')
    layout = None
    if text is not None:
        if not text.strip():
            raise ValueError('اكتب النص الجديد، أو استخدم «حذف المحدد».')
        if not 4 <= size <= 200:
            raise ValueError('حجم الخط خارج النطاق المسموح.')
        layout = QTextDocument()
        metrics = QImage(1, 1, QImage.Format.Format_ARGB32)
        metrics.setDotsPerMeterX(round(72/.0254)); metrics.setDotsPerMeterY(round(72/.0254))
        layout.documentLayout().setPaintDevice(metrics)
        layout.setDocumentMargin(0)
        font = QFont(family); font.setPointSizeF(size); font.setBold(bold)
        layout.setDefaultFont(font)
        option = layout.defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment({'left': Qt.AlignmentFlag.AlignLeft, 'right': Qt.AlignmentFlag.AlignRight,
            'center': Qt.AlignmentFlag.AlignHCenter, 'auto': Qt.AlignmentFlag.AlignLeading}.get(alignment, Qt.AlignmentFlag.AlignLeading))
        layout.setDefaultTextOption(option)
        # Plain text only: PDF text is never interpreted as rich HTML.
        layout.setPlainText(text)
        layout.setTextWidth(w)
        if auto_fit:
            fitted=float(size)
            while layout.size().height() > h+.5 and fitted > 4.01:
                fitted=max(4.0,fitted-.5)
                font.setPointSizeF(fitted);layout.setDefaultFont(font);layout.setTextWidth(w)
        if layout.size().height() > h+.5:
            raise ValueError('النص أكبر من المساحة المحددة. وسّع المربع أو قلّل حجم الخط ثم جرّب المعاينة.')
    elif image.isNull():
        raise ValueError('تعذر قراءة الصورة.')
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer); writer.setResolution(72)
    writer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setCreator('Waraq PDF page editor')
    painter = QPainter(writer)
    try:
        if not painter.isActive():
            raise RuntimeError('تعذر إنشاء التعديل.')
        painter.setClipRect(QRectF(x, y, w, h))
        if layout is not None:
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette.setColor(QPalette.ColorRole.Text, QColor(color))
            painter.translate(QPointF(x, y))
            layout.documentLayout().draw(painter, context)
        else:
            factor = min(w/image.width(), h/image.height())
            iw, ih = image.width()*factor, image.height()*factor
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(x+(w-iw)/2, y+(h-ih)/2, iw, ih), image)
    finally:
        painter.end()
    del writer
    buffer.close()
    return bytes(data)


def edit_page(data: bytes, indexes=(), *, text=None, image: QImage | None=None, rect=None,
              size=16, family='Segoe UI', color='#123b48', bold=False, alignment='auto', selected_chars=None,
              auto_fit=False) -> bytes:
    """Delete selected objects and optionally place a new vector-text/image layer.

    The caller owns source bytes; a failure returns no replacement and changes
    nothing. Existing text outside selected objects is not rewritten.
    """
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != 1:
        raise ValueError('اختر صفحة واحدة للتحرير.')
    width, height = float(reader.pages[0].cropbox.width), float(reader.pages[0].cropbox.height)
    layer = None
    if text is not None or image is not None:
        if rect is None:
            raise ValueError('حدد مكان الإضافة على الصفحة.')
        layer = _layer(width, height, rect, text=text, image=image, size=size, family=family, color=color,
                       bold=bold, alignment=alignment, auto_fit=auto_fit)
    elif not indexes:
        raise ValueError('حدد عنصرًا للحذف.')
    changed = _remove_objects(data, list(indexes), selected_chars)
    reader = PdfReader(BytesIO(changed))
    if layer:
        reader.pages[0].merge_page(PdfReader(BytesIO(layer)).pages[0])
    writer = PdfWriter(); writer.append(reader, import_outline=False)
    writer.pdf_header = max(writer.pdf_header, '%PDF-1.7')
    stream = BytesIO(); writer.write(stream); writer.close()
    return stream.getvalue()


def insert_table(data: bytes, rect, rows: list[list[str]], *, family='Segoe UI', size=10,
                 header=True, rtl=False) -> bytes:
    """Insert a vector table from editable row/column data."""
    if not rows or not any(rows):raise ValueError('أضف خلية واحدة على الأقل للجدول.')
    columns=max(len(row) for row in rows)
    if columns<1 or columns>20 or len(rows)>100:raise ValueError('الجدول محدود بمائة صف وعشرين عمودًا.')
    rows=[list(row)+['']*(columns-len(row)) for row in rows]
    reader=PdfReader(BytesIO(data));page=reader.pages[0];width,height=float(page.cropbox.width),float(page.cropbox.height)
    x,y,w,h=map(float,rect)
    if x<0 or y<0 or w<40 or h<20 or x+w>width+.01 or y+h>height+.01:raise ValueError('ضع الجدول داخل الصفحة وبحجم مناسب.')
    output=QByteArray();buffer=QBuffer(output);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pdf=QPdfWriter(buffer);pdf.setResolution(72);pdf.setPageSize(QPageSize(QSizeF(width,height),QPageSize.Unit.Point));pdf.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Point)
    painter=QPainter(pdf)
    try:
        cell_w,cell_h=w/columns,h/len(rows);font=QFont(family);font.setPointSizeF(max(4,min(72,size)))
        painter.setFont(font);painter.setPen(QColor('#334e5c'))
        for row_index,row in enumerate(rows):
            for logical_column,value in enumerate(row):
                column=columns-1-logical_column if rtl else logical_column
                cell=QRectF(x+column*cell_w,y+row_index*cell_h,cell_w,cell_h)
                if header and row_index==0:painter.fillRect(cell,QColor('#dcefe9'))
                painter.drawRect(cell);align=Qt.AlignmentFlag.AlignVCenter|(Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
                painter.drawText(cell.adjusted(4,2,-4,-2),align,str(value)[:1000])
    finally:painter.end();del pdf;buffer.close()
    page.merge_page(PdfReader(BytesIO(bytes(output))).pages[0])
    writer=PdfWriter();writer.append(reader,import_outline=False);stream=BytesIO();writer.write(stream);writer.close();return stream.getvalue()
