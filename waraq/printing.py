"""Explicit user-initiated printing; no shell commands or external PDF reader."""
from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
import math
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtPrintSupport import QPrinter
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter

from .rendering import render_image


class PrintCancelled(Exception):
    pass


def booklet_order(indexes: list[int]) -> list[int]:
    """Impose pages in landscape two-up booklet order; -1 denotes a blank."""
    pages=list(indexes)
    while len(pages)%4:pages.append(-1)
    result=[]
    for offset in range(len(pages)//4):
        left=offset*2;right=len(pages)-1-offset*2
        result.extend((pages[right],pages[left],pages[left+1],pages[right-1]))
    return result


def sheet_grid(pages_per_sheet: int) -> tuple[int,int]:
    grids={1:(1,1),2:(2,1),4:(2,2),6:(3,2),9:(3,3),16:(4,4)}
    if pages_per_sheet not in grids:
        raise ValueError('عدد الصفحات في الورقة يجب أن يكون 1 أو 2 أو 4 أو 6 أو 9 أو 16.')
    return grids[pages_per_sheet]


def preview_sheet(data: bytes, indexes: list[int], *, pages_per_sheet=1, grayscale=False,
                  mode='normal', poster_scale=100, draw_annotations=True, page_border=False) -> QImage:
    """Render a lightweight first-sheet preview using the same imposition rules."""
    sequence=booklet_order(indexes) if mode=='booklet' else list(indexes)
    landscape=mode=='booklet';canvas=QImage(840 if landscape else 600,600 if landscape else 840,QImage.Format.Format_ARGB32)
    canvas.fill(QColor('#d9dde2'));painter=QPainter(canvas);paper=QRectF(18,18,canvas.width()-36,canvas.height()-36)
    painter.fillRect(paper,QColor('white'));painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if not sequence:painter.end();return canvas
    with pdfium.PdfDocument(data) as document:
        if mode=='poster':
            index=next((value for value in sequence if value>=0),None)
            if index is not None:
                image=render_image(document,index,.6,draw_annotations=draw_annotations)
                if grayscale:image=image.convertToFormat(QImage.Format.Format_Grayscale8)
                ratio=min((paper.width()-24)/image.width(),(paper.height()-24)/image.height());target=QRectF(
                    paper.center().x()-image.width()*ratio/2,paper.center().y()-image.height()*ratio/2,image.width()*ratio,image.height()*ratio)
                painter.drawImage(target,image)
                tiles=max(1,math.ceil(poster_scale/100));painter.setPen(QPen(QColor('#c9343e'),2))
                for part in range(1,tiles):
                    painter.drawLine(target.left()+target.width()*part/tiles,target.top(),target.left()+target.width()*part/tiles,target.bottom())
                    painter.drawLine(target.left(),target.top()+target.height()*part/tiles,target.right(),target.top()+target.height()*part/tiles)
                painter.drawRect(target)
        else:
            if mode=='booklet':pages_per_sheet=2
            columns,rows=sheet_grid(pages_per_sheet);cell_w=paper.width()/columns;cell_h=paper.height()/rows
            for slot,index in enumerate(sequence[:pages_per_sheet]):
                if index<0:continue
                image=render_image(document,index,.45,draw_annotations=draw_annotations)
                if grayscale:image=image.convertToFormat(QImage.Format.Format_Grayscale8)
                column,row=slot%columns,slot//columns;margin=min(cell_w,cell_h)*.04
                ratio=min((cell_w-2*margin)/image.width(),(cell_h-2*margin)/image.height())
                target=QRectF(paper.left()+column*cell_w+(cell_w-image.width()*ratio)/2,
                    paper.top()+row*cell_h+(cell_h-image.height()*ratio)/2,image.width()*ratio,image.height()*ratio)
                painter.drawImage(target,image)
                if page_border:painter.setPen(QPen(QColor('#70757a'),1));painter.drawRect(target)
    painter.setPen(QPen(QColor('#adb5bd'),2));painter.drawRect(paper);painter.end();return canvas


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
              *, pages_per_sheet: int = 1, grayscale: bool = False, sizing: str = 'fit',
              scale_percent: float = 100, mode: str = 'normal', poster_scale: float = 100,
              draw_annotations: bool = True, page_border: bool = False) -> int:
    """Fit PDF pages to printable paper at up to 300 DPI, with bounded memory.

    Content is rasterized for the print job only. Saved PDFs remain vector PDFs.
    Native printer drivers handle their supported copy/collation options.
    """
    if not indexes:
        raise ValueError("لم يتم اختيار صفحات للطباعة.")
    if sizing not in ('fit','actual','shrink','custom'):
        raise ValueError('وضع تحجيم الطباعة غير صالح.')
    if not 10 <= scale_percent <= 500 or not 25 <= poster_scale <= 500:
        raise ValueError('نسبة تحجيم الطباعة خارج النطاق المسموح.')
    if mode not in ('normal','booklet','poster'):
        raise ValueError('تخطيط الطباعة غير صالح.')
    if mode=='booklet':
        indexes=booklet_order(indexes);pages_per_sheet=2
    columns,rows=sheet_grid(pages_per_sheet)
    copies = max(1, printer.copyCount()) if not printer.supportsMultipleCopies() else 1
    if printer.collateCopies():
        sequence = indexes * copies
    else:
        sequence = [index for index in indexes for _ in range(copies)]
    painter = QPainter()
    printed_result = len([index for index in sequence if index>=0])
    if not painter.begin(printer):
        raise RuntimeError("تعذر بدء الطباعة. تحقق من الطابعة أو مكان ملف الإخراج.")
    try:
        with pdfium.PdfDocument(data) as document:
            if mode=='poster':
                real=[index for index in sequence if index>=0]
                paper=printer.pageLayout().paintRectPixels(printer.resolution());dpi=min(300,printer.resolution())
                specs=[]
                for index in real:
                    page=document[index]
                    try:width,height=page.get_size()
                    finally:page.close()
                    wanted_w=width*dpi/72*poster_scale/100;wanted_h=height*dpi/72*poster_scale/100
                    tiles_x=max(1,math.ceil(wanted_w/paper.width()));tiles_y=max(1,math.ceil(wanted_h/paper.height()))
                    specs.append((index,width,height,wanted_w,wanted_h,tiles_x,tiles_y))
                total=sum(spec[5]*spec[6] for spec in specs);done=0
                for index,width,height,wanted_w,wanted_h,tiles_x,tiles_y in specs:
                    render_scale=dpi/72*poster_scale/100
                    render_scale=min(render_scale,(36_000_000/max(width*height,1))**.5)
                    image=render_image(document,index,render_scale,draw_annotations=draw_annotations)
                    if grayscale:image=image.convertToFormat(QImage.Format.Format_Grayscale8)
                    for tile_y in range(tiles_y):
                        for tile_x in range(tiles_x):
                            if progress and not progress(done,total):
                                printer.abort();raise PrintCancelled()
                            if done and not printer.newPage():raise RuntimeError('رفضت الطابعة بدء صفحة جديدة.')
                            source_x=tile_x*paper.width()/wanted_w*image.width();source_y=tile_y*paper.height()/wanted_h*image.height()
                            source_w=min(paper.width(),wanted_w-tile_x*paper.width())/wanted_w*image.width()
                            source_h=min(paper.height(),wanted_h-tile_y*paper.height())/wanted_h*image.height()
                            target=QRectF(paper.x(),paper.y(),source_w/image.width()*wanted_w,source_h/image.height()*wanted_h)
                            painter.drawImage(target,image,QRectF(source_x,source_y,source_w,source_h));done+=1
                if progress:progress(done,done)
                printed_result=len(real)
            else:
                for offset, index in enumerate(sequence):
                    if progress and not progress(offset, len(sequence)):
                        printer.abort()
                        raise PrintCancelled()
                    slot = offset % pages_per_sheet
                    if offset and slot == 0 and not printer.newPage():
                        raise RuntimeError("رفضت الطابعة بدء صفحة جديدة.")
                    if index < 0:
                        continue
                    page = document[index]
                    try:
                        width, height = page.get_size()
                    finally:
                        page.close()
                    scale = min(300, printer.resolution()) / 72
                    scale = min(scale, (22_000_000 / max(width * height, 1)) ** 0.5)
                    image = render_image(document, index, scale, draw_annotations=draw_annotations)
                    if grayscale:
                        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
                    paper = printer.pageLayout().paintRectPixels(printer.resolution())
                    column,row=slot%columns,slot//columns
                    cell_width,cell_height=paper.width()/columns,paper.height()/rows
                    margin=min(cell_width,cell_height)*.02
                    fit_ratio=min((cell_width-2*margin)/image.width(),(cell_height-2*margin)/image.height())
                    physical_ratio=(width*printer.resolution()/72)/image.width()
                    ratio={'fit':fit_ratio,'actual':physical_ratio,'shrink':min(fit_ratio,physical_ratio),
                           'custom':physical_ratio*scale_percent/100}[sizing]
                    target = QRectF(paper.x()+column*cell_width+(cell_width-image.width()*ratio)/2,
                                    paper.y()+row*cell_height+(cell_height-image.height()*ratio)/2,
                                    image.width() * ratio, image.height() * ratio)
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    painter.save()
                    painter.setClipRect(QRectF(paper.x()+column*cell_width,paper.y()+row*cell_height,cell_width,cell_height))
                    painter.drawImage(target, image)
                    if page_border:
                        painter.setPen(QPen(QColor('#70757a'),max(1,printer.resolution()/150)))
                        painter.drawRect(target)
                    painter.restore()
                if progress:
                    progress(len(sequence), len(sequence))
    except Exception:
        printer.abort()
        raise
    finally:
        painter.end()
    if printer.printerState() == QPrinter.PrinterState.Error:
        raise RuntimeError("أبلغت الطابعة عن خطأ أثناء الطباعة.")
    return printed_result
