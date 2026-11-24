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
from waraq.printing import (assemble_print_batch,booklet_order,paint_pdf,requested_pages,
                            preview_sheet,sheet_grid,PrintCancelled)
from waraq.app import ProfessionalPrintDialog
from waraq.rendering import text_overlay,ensure_font_support,render_image
from waraq.editing import insert_table
from waraq.conversion import (acquire_wia_image,image_bytes_to_pdf,image_to_pdf,web_to_pdf,
    export_pdf_office,office_page_layouts,office_rgb,sample_box_background,spatial_table,
    table_rows,ConversionError,run_process,ConversionCancelled)
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

    def test_professional_nup_booklet_and_poster_layouts(self):
        self.assertEqual(sheet_grid(6),(3,2))
        self.assertEqual(booklet_order(list(range(5))),[-1,0,1,-1,-1,2,3,4])
        writer=PdfWriter()
        for _ in range(6):writer.add_blank_page(300,400)
        stream=BytesIO();writer.write(stream);data=stream.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            nup=Path(folder)/'six-up.pdf';self.assertEqual(paint_pdf(self.printer(nup),data,list(range(6)),pages_per_sheet=6,page_border=True),6)
            self.assertEqual(len(PdfReader(nup).pages),1)
            booklet=Path(folder)/'booklet.pdf';self.assertEqual(paint_pdf(self.printer(booklet),data,list(range(5)),mode='booklet'),5)
            self.assertEqual(len(PdfReader(booklet).pages),4)
            poster=Path(folder)/'poster.pdf';self.assertEqual(paint_pdf(self.printer(poster),data,[0],mode='poster',poster_scale=200),1)
            self.assertGreaterEqual(len(PdfReader(poster).pages),2)

    def test_unified_print_dialog_ranges_and_preview(self):
        writer=PdfWriter()
        for _ in range(6):writer.add_blank_page(300,400)
        stream=BytesIO();writer.write(stream);data=stream.getvalue()
        dialog=ProfessionalPrintDialog(data,6,current=2,selected=[1,4])
        dialog.range.setCurrentIndex(dialog.range.findData('current'));self.assertEqual(dialog.indexes(),[2])
        dialog.range.setCurrentIndex(dialog.range.findData('selected'));self.assertEqual(dialog.indexes(),[1,4])
        dialog.range.setCurrentIndex(dialog.range.findData('custom'));dialog.pages.setText('2-3, 6');self.assertEqual(dialog.indexes(),[1,2,5])
        normal=preview_sheet(data,[0,1],pages_per_sheet=2,page_border=True)
        booklet=preview_sheet(data,[0,1,2],mode='booklet')
        self.assertFalse(normal.isNull());self.assertGreater(normal.height(),normal.width())
        self.assertGreater(booklet.width(),booklet.height())

    def test_cancel_print_stops_job(self):
        writer=PdfWriter();writer.add_blank_page(200,300);stream=BytesIO();writer.write(stream)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(PrintCancelled):
                paint_pdf(self.printer(Path(folder)/'cancel.pdf'),stream.getvalue(),[0],lambda *_:False)

    def test_batch_print_assembly_order_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[]
            for index,width in enumerate((200,300,400)):
                path=Path(folder)/f'{index}.pdf';writer=PdfWriter();writer.add_blank_page(width,500)
                with path.open('wb') as stream:writer.write(stream)
                paths.append(path)
            data,count=assemble_print_batch(paths)
            self.assertEqual(count,3)
            self.assertEqual([float(page.mediabox.width) for page in PdfReader(BytesIO(data)).pages],[200,300,400])
            with self.assertRaises(PrintCancelled):
                assemble_print_batch(paths,lambda *_:False)

    def test_transparent_image_and_multipage_tiff(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.png'
            Image.new('RGBA',(150,100),(255,0,0,100)).save(path)
            self.assertEqual(len(PdfReader(BytesIO(image_to_pdf(path))).pages),1)
            path=Path(folder)/'scan.tiff'
            first=Image.new('RGB',(100,100),'red');second=Image.new('RGB',(100,150),'blue')
            first.save(path,save_all=True,append_images=[second])
            self.assertEqual(len(PdfReader(BytesIO(image_to_pdf(path))).pages),2)

    def test_scanned_image_bytes_and_platform_guard(self):
        image=Image.new('RGB',(80,60),'white');stream=BytesIO();image.save(stream,format='JPEG')
        self.assertEqual(len(PdfReader(BytesIO(image_bytes_to_pdf(stream.getvalue()))).pages),1)
        with patch('waraq.conversion.os.name','posix'):
            with self.assertRaisesRegex(ConversionError,'Windows'):acquire_wia_image()

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

    def test_office_export_validation_and_table_rows(self):
        self.assertEqual(table_rows('Name  Amount\nAli\t10\n\nTotal  10'),[['Name','Amount'],['Ali','10'],['Total','10']])
        with self.assertRaisesRegex(ConversionError,'غير مدعومة'):
            export_pdf_office(b'%PDF-invalid','unused.bin','exe')

    def test_office_spatial_layout_and_background_sampling(self):
        entries=[{'kind':'text','text':'Name','rect':(30,40,80,15),'size':12},
                 {'kind':'text','text':'Amount','rect':(220,40,80,15),'size':12},
                 {'kind':'text','text':'Ali','rect':(30,70,80,15),'size':12},
                 {'kind':'text','text':'25','rect':(220,70,80,15),'size':12}]
        self.assertEqual(spatial_table(entries),[['Name','Amount'],['Ali','25']])
        image=Image.new('RGB',(200,100),(17,34,51));color,variation=sample_box_background(image,(10,10,50,20),(100,50))
        self.assertEqual(color,(17,34,51));self.assertEqual(variation,0)
        self.assertEqual(office_rgb('#112233'),0x332211)

        document=Document();writer=PdfWriter();writer.add_blank_page(595,842);stream=BytesIO();writer.write(stream)
        document.import_bytes('layout.pdf',stream.getvalue());document.add_overlay([0],Overlay('EDITABLE OFFICE TEXT','center',24))
        layouts=office_page_layouts(document.build_bytes(overlay_renderer=text_overlay))
        self.assertEqual(len(layouts),1);self.assertTrue(any('EDITABLE' in item['text'] for item in layouts[0]['entries']))

        writer=PdfWriter();writer.add_blank_page(595,842);stream=BytesIO();writer.write(stream)
        table_pdf=insert_table(stream.getvalue(),(40,100,510,150),[['Name','Department','Amount'],['Ali','Engineering','1250']],rtl=False)
        self.assertEqual(spatial_table(office_page_layouts(table_pdf)[0]['entries'])[:2],
                         [['Name','Department','Amount'],['Ali','Engineering','1250']])


if __name__=='__main__':unittest.main()
