"""Edit page objects without covering old text or modifying source files.

Only top-level text/image objects are selected. Forms, paths, clipping and
scanned text are not interpreted as editable paragraphs. This is an editor,
not a secure-redaction implementation.
"""
from dataclasses import dataclass
from io import BytesIO
import math

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
                    l, b, r, t = obj.get_bounds()
                    if r <= 0 or t <= 0 or l >= width or b >= height:
                        continue
                    text, size = '', 16.0
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        try:
                            text = obj.extract().strip('\x00\r\n')
                            size = obj.get_font_size()
                        except pdfium.PdfiumError:
                            text = ''
                    result.append(EditableObject(index, 'text' if obj.type == raw.FPDF_PAGEOBJ_TEXT else 'image',
                        text, (l, height-t, max(r-l, .1), max(t-b, .1)), size))
                return width, height, result
            finally:
                textpage.close()
        finally:
            page.close()


def _remove_objects(data: bytes, indexes: list[int]) -> bytes:
    if not indexes:
        return data
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            objects = list(page.get_objects(max_depth=1))
            selected = sorted(set(indexes), reverse=True)
            if any(i < 0 or i >= len(objects) or objects[i].type not in (raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_IMAGE) for i in selected):
                raise ValueError('العنصر المحدد غير قابل للتحرير. أعد تحديده من الصفحة.')
            # No live PdfTextPage handles while text objects are removed.
            for index in selected:
                obj = objects[index]
                page.remove_obj(obj)
                obj.close()
            page.gen_content()
            stream = BytesIO(); document.save(stream)
            return stream.getvalue()
        finally:
            page.close()


def _layer(width, height, rect, *, text=None, image=None, size=16, family='Segoe UI', color='#123b48', bold=False):
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
        layout.setDefaultTextOption(option)
        # Plain text only: PDF text is never interpreted as rich HTML.
        layout.setPlainText(text)
        layout.setTextWidth(w)
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
              size=16, family='Segoe UI', color='#123b48', bold=False) -> bytes:
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
        layer = _layer(width, height, rect, text=text, image=image, size=size, family=family, color=color, bold=bold)
    elif not indexes:
        raise ValueError('حدد عنصرًا للحذف.')
    changed = _remove_objects(data, list(indexes))
    reader = PdfReader(BytesIO(changed))
    if layer:
        reader.pages[0].merge_page(PdfReader(BytesIO(layer)).pages[0])
    writer = PdfWriter(); writer.append(reader, import_outline=False)
    writer.pdf_header = max(writer.pdf_header, '%PDF-1.7')
    stream = BytesIO(); writer.write(stream); writer.close()
    return stream.getvalue()
