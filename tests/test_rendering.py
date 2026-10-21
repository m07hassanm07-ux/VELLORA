import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium

from waraq.core import Document, Overlay
from waraq.rendering import render_image, text_overlay
from waraq.app import MainWindow, SaveDialog


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_arabic_overlay_is_vector_pdf_with_visible_glyphs(self):
        data = text_overlay(595, 842, Overlay("مرحبًا بك في ورّاق PDF", "center", 26))
        reader = PdfReader(BytesIO(data))
        self.assertEqual(len(reader.pages), 1)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595, delta=1)
        self.assertTrue(reader.pages[0].get("/Resources").get("/Font"))
        with pdfium.PdfDocument(data) as pdf:
            image = render_image(pdf, 0, 0.7)
            self.assertFalse(image.isNull())
            pixels = image.convertToFormat(image.Format.Format_RGB32)
            count = sum(1 for y in range(260, 330) for x in range(35, 380) if pixels.pixelColor(x, y).lightness() < 200)
            self.assertGreater(count, 300)

    def test_rotated_page_overlay_has_correct_dimensions_and_number_context(self):
        writer = PdfWriter()
        writer.add_blank_page(200, 500)
        writer.add_blank_page(300, 500)
        data = BytesIO()
        writer.write(data)
        doc = Document()
        doc.import_bytes("input.pdf", data.getvalue())
        doc.rotate([0], 90)
        doc.add_overlay([0, 1], Overlay("", numbering=True))
        output = PdfReader(BytesIO(doc.build_bytes(overlay_renderer=text_overlay)))
        self.assertAlmostEqual(float(output.pages[0].mediabox.width), 500)
        self.assertAlmostEqual(float(output.pages[0].mediabox.height), 200)
        self.assertIn("1 / 2", " ".join(output.pages[0].extract_text().split()))
        self.assertIn("2 / 2", " ".join(output.pages[1].extract_text().split()))
        preview = PdfReader(BytesIO(doc.build_bytes([1], overlay_renderer=text_overlay, preview_context=(2, 2))))
        self.assertIn("2 / 2", " ".join(preview.pages[0].extract_text().split()))

    def test_desktop_preview_and_history_smoke(self):
        window = MainWindow()
        window.add_blank()
        window.render_current()
        self.assertEqual(window.pages.count(), 1)
        self.assertFalse(window.image_label.pixmap().isNull())
        window.document.add_overlay([0], Overlay("اختبار", "center"))
        window.refresh()
        window.render_current()
        self.assertFalse(window.image_label.pixmap().isNull())
        window.rotate(90)
        self.assertEqual(window.document.pages[0].rotation, 90)
        window.undo()
        self.assertEqual(window.document.pages[0].rotation, 0)
        options = SaveDialog(window, protected_input=True)
        self.assertTrue(options.protect.isChecked())
        self.assertTrue(options.password.isEnabled())
        window.document.mark_saved()
        window.close()


if __name__ == "__main__":
    unittest.main()
