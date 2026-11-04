"""Explicit user-initiated printing; no shell commands or external PDF reader."""
from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter

from .rendering import render_image


class PrintCancelled(Exception):
    pass


def assemble_print_batch(paths: list[str | Path], progress: Callable[[int, int, str], bool] | None = None,
                         cancelled: Callable[[], bool] | None = None) -> tuple[bytes, int]:
    """Combine user-selected PDFs for one ordered print job without editing sources."""
    files = [Path(path) for path in paths]
    if not files:
        raise ValueError("اختر ملف PDF واحدًا على الأقل للطباعة الدفعية.")
    if len(files) > 100:
        raise ValueError("الطباعة الدفعية محدودة بمائة ملف في العملية الواحدة.")
    writer = PdfWriter(); pages = 0
    try:
        for index, path in enumerate(files):
            if cancelled and cancelled():
                raise PrintCancelled()
            if path.suffix.casefold() != ".pdf" or not path.is_file():
                raise ValueError(f"ملف الطباعة غير صالح: {path.name}")
            if progress and not progress(index, len(files), f"جاري تجهيز {path.name}…"):
                raise PrintCancelled()
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                raise ValueError(f"الملف {path.name} محمي بكلمة مرور؛ افتحه واحفظ نسخة قابلة للطباعة أولًا.")
            writer.append(reader, import_outline=False)
            pages += len(reader.pages)
        if not pages:
            raise ValueError("لا تحتوي الملفات المختارة على صفحات قابلة للطباعة.")
        output = BytesIO(); writer.write(output)
        if progress: progress(len(files), len(files), "اكتمل تجهيز الملفات.")
        return output.getvalue(), pages
    finally:
        writer.close()


def requested_pages(printer: QPrinter, count: int, current: int = 0, selected: list[int] | None = None) -> list[int]:
    choice = printer.printRange()
    if choice == QPrinter.PrintRange.CurrentPage:
        pages = [current]
    elif choice == QPrinter.PrintRange.Selection:
        pages = sorted(set(selected or [current]))
    elif choice == QPrinter.PrintRange.PageRange:
        ranges = printer.pageRanges().toRangeList()
        if ranges:
            pages = [i for part in ranges for i in range(max(1, part.from_) - 1, min(count, part.to))]
        else:
            pages = list(range(max(1, printer.fromPage()) - 1, min(count, printer.toPage() or count)))
    else:
        pages = list(range(count))
    pages = [i for i in pages if 0 <= i < count]
    if printer.pageOrder() == QPrinter.PageOrder.LastPageFirst:
        pages.reverse()
    return pages


def paint_pdf(printer: QPrinter, data: bytes, indexes: list[int], progress: Callable[[int, int], bool] | None = None,
              *, pages_per_sheet: int = 1, grayscale: bool = False) -> int:
    """Fit PDF pages to printable paper at up to 300 DPI, with bounded memory.

    Content is rasterized for the print job only. Saved PDFs remain vector PDFs.
    Native printer drivers handle their supported copy/collation options.
    """
    if not indexes:
        raise ValueError("لم يتم اختيار صفحات للطباعة.")
    if pages_per_sheet not in (1, 2, 4):
        raise ValueError("عدد الصفحات في الورقة يجب أن يكون 1 أو 2 أو 4.")
    copies = max(1, printer.copyCount()) if not printer.supportsMultipleCopies() else 1
    if printer.collateCopies():
        sequence = indexes * copies
    else:
        sequence = [index for index in indexes for _ in range(copies)]
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("تعذر بدء الطباعة. تحقق من الطابعة أو مكان ملف الإخراج.")
    try:
        with pdfium.PdfDocument(data) as document:
            for offset, index in enumerate(sequence):
                if progress and not progress(offset, len(sequence)):
                    printer.abort()
                    raise PrintCancelled()
                slot = offset % pages_per_sheet
                if offset and slot == 0 and not printer.newPage():
                    raise RuntimeError("رفضت الطابعة بدء صفحة جديدة.")
                page = document[index]
                try:
                    width, height = page.get_size()
                finally:
                    page.close()
                scale = min(300, printer.resolution()) / 72
                scale = min(scale, (22_000_000 / max(width * height, 1)) ** 0.5)
                image = render_image(document, index, scale)
                if grayscale:
                    from PySide6.QtGui import QImage
                    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
                paper = printer.pageLayout().paintRectPixels(printer.resolution())
                columns,rows=(1,1) if pages_per_sheet==1 else (2,1) if pages_per_sheet==2 else (2,2)
                column,row=slot%columns,slot//columns
                cell_width,cell_height=paper.width()/columns,paper.height()/rows
                margin=min(cell_width,cell_height)*.02
                ratio = min((cell_width-2*margin) / image.width(), (cell_height-2*margin) / image.height())
                target = QRectF(paper.x()+column*cell_width+(cell_width-image.width()*ratio)/2,
                                paper.y()+row*cell_height+(cell_height-image.height()*ratio)/2,
                                image.width() * ratio, image.height() * ratio)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(target, image)
            if progress:
                progress(len(sequence), len(sequence))
    except Exception:
        printer.abort()
        raise
    finally:
        painter.end()
    if printer.printerState() == QPrinter.PrinterState.Error:
        raise RuntimeError("أبلغت الطابعة عن خطأ أثناء الطباعة.")
    return len(sequence)
