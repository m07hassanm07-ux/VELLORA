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
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPalette, QPdfWriter, QPen, QTextDocument, QTextOption

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


def following_flow_indexes(entries: list[EditableObject], selected_indexes, rect, delta, page_height):
    """Return same-column objects below an expanded paragraph.

    PDF has no paragraph-flow model, so this deliberately uses a conservative
    geometric rule: only top-level text/images that overlap the paragraph's
    horizontal column and start below its original bottom are moved.
    """
    if delta <= .01:
        return []
    selected = set(selected_indexes)
    x, y, w, h = map(float, rect)
    bottom = y + h
    result = []
    for entry in entries:
        indexes = tuple(entry.indices or (entry.index,))
        if selected.intersection(indexes):
            continue
        ex, ey, ew, eh = entry.rect
        overlap = min(x + w, ex + ew) - max(x, ex)
        if overlap <= min(w, ew) * .25 or ey < bottom - 1:
            continue
        if ey + eh + delta > page_height + .01:
            raise ValueError('لا توجد مساحة كافية لتحريك المحتوى التالي داخل الصفحة. قلّل النص أو وسّع الصفحة.')
        result.extend(indexes)
    return list(dict.fromkeys(result))


def _translate_objects(data: bytes, indexes, down: float) -> bytes:
    """Move top-level page objects down in editor coordinates."""
    indexes = sorted(set(indexes))
    if not indexes or down <= .01:
        return data
    if not math.isfinite(down):
        raise ValueError('قيمة تحريك المحتوى غير صالحة.')
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            objects = list(page.get_objects(max_depth=1))
            if any(index < 0 or index >= len(objects) for index in indexes):
                raise ValueError('تعذر تحريك المحتوى التالي؛ أعد تحديد الفقرة.')
            for index in indexes:
                obj = objects[index]
                if obj.type not in (raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_IMAGE):
                    raise ValueError('يوجد عنصر غير قابل لإعادة التدفق أسفل الفقرة.')
                left, bottom, right, top = obj.get_bounds()
                if bottom - down < -.01:
                    raise ValueError('لا توجد مساحة كافية لتحريك المحتوى التالي داخل الصفحة.')
            translation = pdfium.PdfMatrix().translate(0, -down)
            for index in indexes:
                objects[index].transform(translation)
            page.gen_content()
            stream = BytesIO(); document.save(stream)
            return stream.getvalue()
        finally:
            page.close()


def transform_objects(data: bytes, indexes, source_rect, target_rect) -> bytes:
    """Move or resize top-level text/image objects without rasterising them."""
    indexes = sorted(set(indexes))
    sx, sy, sw, sh = map(float, source_rect)
    tx, ty, tw, th = map(float, target_rect)
    values = (sx, sy, sw, sh, tx, ty, tw, th)
    if not indexes or not all(math.isfinite(value) for value in values):
        raise ValueError('تعذر تحريك العنصر المحدد.')
    if min(sw, sh, tw, th) <= 0:
        raise ValueError('يجب أن يظل حجم العنصر أكبر من الصفر.')
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            width, height = page.get_size()
            if tx < 0 or ty < 0 or tx + tw > width + .01 or ty + th > height + .01:
                raise ValueError('ضع العنصر بالكامل داخل حدود الصفحة.')
            objects = list(page.get_objects(max_depth=1))
            if any(index < 0 or index >= len(objects) or objects[index].type not in
                   (raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_IMAGE) for index in indexes):
                raise ValueError('العنصر المحدد غير قابل للتحريك.')
            scale_x, scale_y = tw / sw, th / sh
            source_bottom = height - (sy + sh)
            target_bottom = height - (ty + th)
            matrix = pdfium.PdfMatrix(scale_x, 0, 0, scale_y,
                                      tx - scale_x * sx,
                                      target_bottom - scale_y * source_bottom)
            for index in indexes:
                objects[index].transform(matrix)
            page.gen_content()
            stream = BytesIO(); document.save(stream)
            return stream.getvalue()
        finally:
            page.close()


def reorder_objects(data: bytes, indexes, front=True) -> bytes:
    """Move selected top-level objects to the front or back of page paint order."""
    selected=set(indexes)
    if not selected:return data
    with pdfium.PdfDocument(data) as document:
        page=document[0]
        try:
            objects=list(page.get_objects(max_depth=1))
            if any(index<0 or index>=len(objects) for index in selected):
                raise ValueError('تعذر ترتيب العنصر المحدد.')
            chosen=[obj for index,obj in enumerate(objects) if index in selected]
            others=[obj for index,obj in enumerate(objects) if index not in selected]
            for obj in objects:page.remove_obj(obj)
            for obj in ((others+chosen) if front else (chosen+others)):page.insert_obj(obj)
            page.gen_content();stream=BytesIO();document.save(stream);return stream.getvalue()
        finally:page.close()


def rotate_objects(data: bytes, indexes, rect, degrees=90) -> bytes:
    """Rotate selected top-level objects around the selection centre."""
    indexes=sorted(set(indexes));x,y,w,h=map(float,rect);degrees=int(degrees)%360
    if not indexes or degrees not in (90,180,270):raise ValueError('قيمة تدوير العنصر غير صالحة.')
    with pdfium.PdfDocument(data) as document:
        page=document[0]
        try:
            width,height=page.get_size();cx=x+w/2;cy=height-(y+h/2)
            new_w,new_h=(h,w) if degrees in (90,270) else (w,h)
            if cx-new_w/2<-.01 or cx+new_w/2>width+.01 or cy-new_h/2<-.01 or cy+new_h/2>height+.01:
                raise ValueError('لا توجد مساحة كافية لتدوير العنصر داخل الصفحة.')
            objects=list(page.get_objects(max_depth=1))
            if any(index<0 or index>=len(objects) for index in indexes):raise ValueError('تعذر تدوير العنصر المحدد.')
            matrix=pdfium.PdfMatrix().translate(-cx,-cy).rotate(degrees).translate(cx,cy)
            for index in indexes:objects[index].transform(matrix)
            page.gen_content();stream=BytesIO();document.save(stream);return stream.getvalue()
        finally:page.close()


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
    writer.setCreator('VELLORA PDF editor')
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
              auto_fit=False, move_indexes=(), move_down=0) -> bytes:
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
    changed = _translate_objects(data, move_indexes, float(move_down))
    changed = _remove_objects(changed, list(indexes), selected_chars)
    reader = PdfReader(BytesIO(changed))
    if layer:
        reader.pages[0].merge_page(PdfReader(BytesIO(layer)).pages[0])
    writer = PdfWriter(); writer.append(reader, import_outline=False)
    writer.pdf_header = max(writer.pdf_header, '%PDF-1.7')
    stream = BytesIO(); writer.write(stream); writer.close()
    return stream.getvalue()


def insert_table(data: bytes, rect, rows: list[list[str]], *, family='Segoe UI', size=10,
                 header=True, rtl=False, background=None, spans=(), column_widths=None,
                 row_heights=None, border_color='#334e5c', border_width=1,
                 header_color='#dcefe9') -> bytes:
    """Insert a vector table from editable row/column data."""
    if not rows or not any(rows):raise ValueError('أضف خلية واحدة على الأقل للجدول.')
    columns=max(len(row) for row in rows)
    if columns<1 or columns>20 or len(rows)>100:raise ValueError('الجدول محدود بمائة صف وعشرين عمودًا.')
    rows=[list(row)+['']*(columns-len(row)) for row in rows]
    reader=PdfReader(BytesIO(data));page=reader.pages[0];width,height=float(page.cropbox.width),float(page.cropbox.height)
    x,y,w,h=map(float,rect)
    if x<0 or y<0 or w<40 or h<20 or x+w>width+.01 or y+h>height+.01:raise ValueError('ضع الجدول داخل الصفحة وبحجم مناسب.')
    def proportions(values,count):
        if not values or len(values)!=count:return [1/count]*count
        values=[max(.01,float(value)) for value in values];total=sum(values)
        return [value/total for value in values]
    column_parts=proportions(column_widths,columns);row_parts=proportions(row_heights,len(rows))
    column_edges=[0.0]
    for part in column_parts:column_edges.append(column_edges[-1]+part*w)
    row_edges=[0.0]
    for part in row_parts:row_edges.append(row_edges[-1]+part*h)
    covered={};anchors={}
    for raw_span in spans or ():
        if len(raw_span)!=4:raise ValueError('بيانات دمج خلايا الجدول غير صالحة.')
        row,column,row_span,column_span=map(int,raw_span)
        if row<0 or column<0 or row_span<1 or column_span<1 or row+row_span>len(rows) or column+column_span>columns:
            raise ValueError('نطاق الخلايا المدمجة خارج حدود الجدول.')
        if row_span==1 and column_span==1:continue
        cells={(r,c) for r in range(row,row+row_span) for c in range(column,column+column_span)}
        if any(cell in covered for cell in cells):raise ValueError('نطاقات الخلايا المدمجة متداخلة.')
        for cell in cells:covered[cell]=(row,column)
        anchors[(row,column)]=(row_span,column_span)
    def cell_rect(row,column,row_span=1,column_span=1):
        visual_column=columns-column-column_span if rtl else column
        return QRectF(x+column_edges[visual_column],y+row_edges[row],
            column_edges[visual_column+column_span]-column_edges[visual_column],
            row_edges[row+row_span]-row_edges[row])
    cells=[]
    for row_index,row in enumerate(rows):
        for column,value in enumerate(row):
            anchor=covered.get((row_index,column))
            if anchor is not None and anchor!=(row_index,column):continue
            row_span,column_span=anchors.get((row_index,column),(1,1))
            cells.append((row_index,column,cell_rect(row_index,column,row_span,column_span),value))
    output=QByteArray();buffer=QBuffer(output);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pdf=QPdfWriter(buffer);pdf.setResolution(72);pdf.setPageSize(QPageSize(QSizeF(width,height),QPageSize.Unit.Point));pdf.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Point)
    painter=QPainter(pdf)
    try:
        font=QFont(family);font.setPointSizeF(max(4,min(72,size)))
        flags=int(Qt.AlignmentFlag.AlignVCenter|(Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)|Qt.TextFlag.TextWordWrap)
        # Fit long cell content uniformly so columns keep a professional,
        # consistent type size while allowing multi-line cells.
        while font.pointSizeF()>4.01:
            painter.setFont(font)
            if all(painter.boundingRect(QRectF(0,0,max(1,cell.width()-8),max(1,cell.height()-4)),flags,str(value)[:1000]).height()<=cell.height()-4 for _,_,cell,value in cells):break
            font.setPointSizeF(max(4,font.pointSizeF()-.5))
        painter.setFont(font);painter.setPen(QPen(QColor(border_color),max(.25,min(6,float(border_width)))))
        if background:painter.fillRect(QRectF(x,y,w,h),QColor(background))
        for row_index,_,cell,value in cells:
            if header and row_index==0:painter.fillRect(cell,QColor(header_color))
            painter.drawRect(cell)
            painter.drawText(cell.adjusted(4,2,-4,-2),flags,str(value)[:1000])
    finally:painter.end();del pdf;buffer.close()
    page.merge_page(PdfReader(BytesIO(bytes(output))).pages[0])
    writer=PdfWriter();writer.append(reader,import_outline=False);stream=BytesIO();writer.write(stream);writer.close();return stream.getvalue()


def infer_table(entries: list[EditableObject], rect=None):
    """Infer a cell matrix from positioned text, with conservative safeguards."""
    candidates=[entry for entry in entries if entry.kind=='text' and entry.text.strip()]
    if rect is not None:
        x,y,w,h=rect
        candidates=[entry for entry in candidates if x<=entry.rect[0]+entry.rect[2]/2<=x+w and y<=entry.rect[1]+entry.rect[3]/2<=y+h]
    if len(candidates)<4:return None
    rows=[]
    for entry in sorted(candidates,key=lambda item:(item.rect[1]+item.rect[3]/2,item.rect[0])):
        center=entry.rect[1]+entry.rect[3]/2;tolerance=max(3,entry.size*.7)
        matches=[row for row in rows if abs(row['center']-center)<=tolerance]
        if matches:
            row=min(matches,key=lambda value:abs(value['center']-center));row['items'].append(entry)
            row['center']=sum(item.rect[1]+item.rect[3]/2 for item in row['items'])/len(row['items'])
        else:rows.append({'center':center,'items':[entry]})
    rows=[row for row in rows if len(row['items'])>=2]
    if len(rows)<2:return None
    column_centers=[]
    for entry in sorted((item for row in rows for item in row['items']),key=lambda item:item.rect[0]+item.rect[2]/2):
        center=entry.rect[0]+entry.rect[2]/2;tolerance=max(10,entry.size*2)
        matches=[(index,value) for index,value in enumerate(column_centers) if abs(value-center)<=tolerance]
        if matches:
            index,_=min(matches,key=lambda pair:abs(pair[1]-center));column_centers[index]=(column_centers[index]+center)/2
        else:column_centers.append(center)
    column_centers.sort()
    if len(column_centers)<2:return None
    matrix=[]
    for row in sorted(rows,key=lambda value:value['center']):
        cells=['']*len(column_centers)
        for entry in sorted(row['items'],key=lambda item:item.rect[0]):
            column=min(range(len(column_centers)),key=lambda i:abs(column_centers[i]-(entry.rect[0]+entry.rect[2]/2)))
            cells[column]=(cells[column]+' '+entry.text).strip()
        matrix.append(cells)
    used=[item for row in rows for item in row['items']]
    left=min(item.rect[0] for item in used);top=min(item.rect[1] for item in used)
    right=max(item.rect[0]+item.rect[2] for item in used);bottom=max(item.rect[1]+item.rect[3] for item in used)
    pad=max(5,max(item.size for item in used)*.6)
    bounds=(max(0,left-pad),max(0,top-pad),right-left+2*pad,bottom-top+2*pad)
    return matrix,list(dict.fromkeys(item.index for item in used)),bounds


def replace_table(data: bytes, indexes, rect, rows, *, family='Segoe UI', size=10, header=True, rtl=False,
                  spans=(), column_widths=None, row_heights=None, border_color='#334e5c',
                  border_width=1, header_color='#dcefe9'):
    """Replace inferred table text and cover the prior grid inside its bounds."""
    changed=_remove_objects(data,list(indexes))
    return insert_table(changed,rect,rows,family=family,size=size,header=header,rtl=rtl,background='#ffffff',
        spans=spans,column_widths=column_widths,row_heights=row_heights,border_color=border_color,
        border_width=border_width,header_color=header_color)
