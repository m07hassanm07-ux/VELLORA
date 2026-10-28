import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from io import BytesIO
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader,PdfWriter
from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout,QPageRanges,QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication
import pypdfium2 as pdfium

from waraq.core import Document,Overlay
from waraq.printing import paint_pdf,requested_pages,PrintCancelled
from waraq.rendering import text_overlay,ensure_font_support,render_image
from waraq.conversion import image_to_pdf,web_to_pdf,ConversionError,run_process,ConversionCancelled
from waraq.merge_dialog import MergeDialog


class PrintingAndConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);ensure_font_support()

    def printer(self,path):
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path));printer.setResolution(150)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(8,8,8,8),QPageLayout.Unit.Millimeter)
        return printer

    def test_page_range_current_selection_and_reverse(self):
        with tempfile.TemporaryDirectory() as folder:
            printer=self.printer(Path(folder)/'unused.pdf')
            printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
            self.assertEqual(requested_pages(printer,8,3),[3])
            printer.setPrintRange(QPrinter.PrintRange.Selection)
            self.assertEqual(requested_pages(printer,8,selected=[4,1,4]),[1,4])
            ranges=QPageRanges();ranges.addRange(2,3);ranges.addPage(6)
            printer.setPageRanges(ranges);printer.setPrintRange(QPrinter.PrintRange.PageRange)
            self.assertEqual(requested_pages(printer,8),[1,2,5])
            printer.setPageOrder(QPrinter.PageOrder.LastPageFirst)
            self.assertEqual(requested_pages(printer,8),[5,2,1])

    def test_print_output_contains_two_visible_pages(self):
        doc=Document();writer=PdfWriter();writer.add_blank_page(595,842);writer.add_blank_page(842,595)
        stream=BytesIO();writer.write(stream);doc.import_bytes('input.pdf',stream.getvalue())
        doc.add_overlay([0,1],Overlay('ورّاق PDF PRINT TEST','center',32))
        data=doc.build_bytes(overlay_renderer=text_overlay)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'printed.pdf';printer=self.printer(output)
            self.assertEqual(paint_pdf(printer,data,[0,1]),2)
            self.assertEqual(len(PdfReader(output).pages),2)
            with pdfium.PdfDocument(str(output)) as pdf:
                for index in range(2):
                    image=render_image(pdf,index,0.35)
                    dark=sum(image.pixelColor(x,y).lightness()<200 for y in range(image.height()) for x in range(image.width()))
                    self.assertGreater(dark,100)

    def test_two_pages_per_sheet_and_grayscale(self):
        writer=PdfWriter();writer.add_blank_page(300,400);writer.add_blank_page(300,400)
        stream=BytesIO();writer.write(stream)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'nup.pdf';printer=self.printer(output)
            self.assertEqual(paint_pdf(printer,stream.getvalue(),[0,1],pages_per_sheet=2,grayscale=True),2)
            self.assertEqual(len(PdfReader(output).pages),1)

    def test_cancel_print_stops_job(self):
        writer=PdfWriter();writer.add_blank_page(200,300);stream=BytesIO();writer.write(stream)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(PrintCancelled):
                paint_pdf(self.printer(Path(folder)/'cancel.pdf'),stream.getvalue(),[0],lambda *_:False)

    def test_transparent_image_and_multipage_tiff(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.png'
            Image.new('RGBA',(150,100),(255,0,0,100)).save(path)
            self.assertEqual(len(PdfReader(BytesIO(image_to_pdf(path))).pages),1)
            path=Path(folder)/'scan.tiff'
            first=Image.new('RGB',(100,100),'red');second=Image.new('RGB',(100,150),'blue')
            first.save(path,save_all=True,append_images=[second])
            self.assertEqual(len(PdfReader(BytesIO(image_to_pdf(path))).pages),2)

    def test_three_file_merge_order_and_independence(self):
        document=Document()
        for width in (200,300,400):
            writer=PdfWriter();writer.add_blank_page(width,500);stream=BytesIO();writer.write(stream)
            document.import_bytes(str(width)+'.pdf',stream.getvalue())
        document.reorder([document.pages[i].uid for i in [2,0,1]])
        output=document.build_bytes()
        self.assertTrue(output.startswith(b'%PDF-1.7'))
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(BytesIO(output)).pages],[400,200,300])

    def test_merge_dialog_reordering(self):
        dialog=MergeDialog(has_document=True);dialog.add_paths(['first.pdf','second.pdf','third.pdf'])
        dialog.files.setCurrentRow(2);dialog.move(-1)
        self.assertEqual(dialog.paths(),['first.pdf','third.pdf','second.pdf'])
        self.assertTrue(dialog.append_current.isChecked())

    def test_web_url_validation_does_not_launch_browser(self):
        for value in ('javascript:alert(1)','file:///C:/private.pdf','--no-sandbox','example.com'):
            with self.assertRaises(ConversionError):web_to_pdf(value)


if __name__=='__main__':unittest.main()
