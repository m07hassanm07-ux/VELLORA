from io import BytesIO
import unittest

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, RectangleObject
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from waraq.core import Document
from waraq.editing import prepare_page, inspect_page, edit_page
from waraq.editor_dialog import PageEditorDialog
from waraq.rendering import ensure_font_support, render_image


def text_fixture(rotation=0, cropped=False):
    writer = PdfWriter(); page = writer.add_blank_page(500, 800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'q .9 .95 .8 rg 0 0 500 800 re f Q\nBT /F1 16 Tf 1 0 0 1 40 720 Tm (OLD TEXT) Tj ET\nBT /F1 16 Tf 1 0 0 1 40 650 Tm (KEEP ME) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    if cropped:
        page.cropbox = RectangleObject((20, 30, 480, 780))
    if rotation:
        page.rotate(rotation)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


class PageEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([]); ensure_font_support()

    def test_replace_actually_removes_selected_text_and_preserves_other_content(self):
        source = prepare_page(text_fixture())
        width, height, entries = inspect_page(source)
        old = next(e for e in entries if e.text == 'OLD TEXT')
        changed = edit_page(source, [old.index], text='NEW TEXT', rect=(40, 60, 250, 40), size=16)
        extracted = PdfReader(BytesIO(changed)).pages[0].extract_text()
        self.assertNotIn('OLD TEXT', extracted)
        self.assertIn('NEW TEXT', ' '.join(extracted.split())); self.assertIn('KEEP ME', extracted)
        self.assertIn('OLD TEXT', PdfReader(BytesIO(source)).pages[0].extract_text())
        with pdfium.PdfDocument(changed) as pdf:
            image = render_image(pdf, 0, .5)
            color = image.pixelColor(10, 10)
            self.assertGreater(color.green(), color.blue())  # colored background retained

    def test_delete_and_insert_image_preserve_unselected_text(self):
        source = prepare_page(text_fixture())
        old = next(e for e in inspect_page(source)[2] if e.text == 'OLD TEXT')
        changed = edit_page(source, [old.index])
        self.assertNotIn('OLD TEXT', PdfReader(BytesIO(changed)).pages[0].extract_text())
        image = QImage(80, 40, QImage.Format.Format_RGB32); image.fill(QColor('red'))
        changed = edit_page(changed, image=image, rect=(100, 200, 160, 160))
        item = next(e for e in inspect_page(changed)[2] if e.kind == 'image')
        self.assertAlmostEqual(item.rect[2]/item.rect[3], 2, places=2)
        changed = edit_page(changed, [item.index])
        self.assertFalse(any(e.kind == 'image' for e in inspect_page(changed)[2]))
        self.assertIn('KEEP ME', PdfReader(BytesIO(changed)).pages[0].extract_text())

    def test_arabic_addition_and_plain_text_not_html(self):
        changed = edit_page(prepare_page(text_fixture()), text='نص عربي جديد\n<b>literal</b>', rect=(30, 180, 420, 110), size=20)
        with pdfium.PdfDocument(changed) as pdf:
            page = pdf[0]; textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
                self.assertIn('<b>literal</b>', text)
                self.assertIn('نص عربي جديد', text)
            finally:
                textpage.close(); page.close()
            image = render_image(pdf, 0, .7)
            self.assertFalse(image.isNull())

    def test_invalid_box_and_overflow_are_rejected_before_removal(self):
        source = prepare_page(text_fixture())
        index = next(e.index for e in inspect_page(source)[2] if e.text == 'OLD TEXT')
        for rect in ((-1, 0, 100, 40), (450, 0, 100, 40), (0, 0, 100, 0), (0, 0, float('nan'), 30)):
            with self.assertRaises(ValueError):
                edit_page(source, [index], text='NEW', rect=rect)
        with self.assertRaisesRegex(ValueError, 'النص أكبر'):
            edit_page(source, [index], text='Too much content '*20, rect=(10, 10, 20, 10), size=30)
        self.assertIn('OLD TEXT', PdfReader(BytesIO(source)).pages[0].extract_text())

    def test_cropped_rotated_page_normalizes_without_visual_change(self):
        for rotation in (0, 90, 180, 270):
            source = text_fixture(rotation, cropped=True)
            normalized = prepare_page(source)
            with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(normalized) as after:
                a, b = render_image(before, 0, .5), render_image(after, 0, .5)
                self.assertEqual(a.size(), b.size())
                differing = sum(a.pixel(x, y) != b.pixel(x, y) for y in range(a.height()) for x in range(a.width()))
                self.assertLess(differing, a.width()*a.height()*.025)
            self.assertEqual(PdfReader(BytesIO(normalized)).pages[0].rotation, 0)

    def test_page_replacement_history_encryption_and_duplicate_independence(self):
        source = text_fixture(); writer = PdfWriter(); writer.append(PdfReader(BytesIO(source)))
        writer.encrypt('known-password', algorithm='AES-256'); encrypted = BytesIO(); writer.write(encrypted)
        model = Document(); sid = model.import_bytes('protected.pdf', encrypted.getvalue(), 'known-password')
        model.duplicate([0]); model.mark_saved()
        before = model.pages.copy(); original_data = model.sources[sid].data
        data = edit_page(prepare_page(source), text='ADDED', rect=(20, 200, 200, 40))
        model.replace_page(0, data)
        self.assertEqual(model.pages[0].uid, before[0].uid)
        self.assertEqual(model.pages[1], before[1])
        self.assertTrue(model.sources[model.pages[0].source].reader.is_encrypted)
        self.assertTrue(model.dirty)
        self.assertEqual(model.sources[sid].data, original_data)
        model.undo(); self.assertEqual(model.pages, before); self.assertFalse(model.dirty)
        model.redo(); self.assertIn('ADDED', PdfReader(BytesIO(model.build_bytes())).pages[0].extract_text())
        state = model.fingerprint()
        with self.assertRaises(ValueError):
            two = PdfWriter(); two.add_blank_page(200, 200); two.add_blank_page(200, 200)
            stream = BytesIO(); two.write(stream); model.replace_page(0, stream.getvalue())
        self.assertEqual(model.fingerprint(), state)

    def test_dialog_apply_preview_undo_redo_and_parent_stays_unchanged(self):
        source = text_fixture(); dialog = PageEditorDialog(source)
        original = dialog.data
        dialog.new_text(); dialog.text.setPlainText('DIALOG EDIT'); dialog.set_rect(QRectF(30, 200, 350, 50))
        dialog.preview_change(); self.assertIsNotNone(dialog.draft)
        self.assertEqual(dialog.data, original)
        dialog.apply_change(); self.assertIn('DIALOG EDIT', ' '.join(PdfReader(BytesIO(dialog.data)).pages[0].extract_text().split()))
        dialog.undo(); self.assertEqual(dialog.data, original)
        dialog.redo(); self.assertIn('DIALOG EDIT', ' '.join(PdfReader(BytesIO(dialog.data)).pages[0].extract_text().split()))
        dialog.reject(); self.assertIn('OLD TEXT', PdfReader(BytesIO(source)).pages[0].extract_text())

    def test_mouse_region_replaces_existing_text_and_invalidates_changed_preview(self):
        dialog = PageEditorDialog(text_fixture())
        dialog.show(); self.app.processEvents()
        start = dialog.canvas.mapFromScene(QPointF(30, 60))
        end = dialog.canvas.mapFromScene(QPointF(190, 110))
        QTest.mousePress(dialog.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(dialog.canvas.viewport(), end)
        QTest.mouseRelease(dialog.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(dialog.selected_indexes()), 1)
        self.assertEqual(dialog.text.toPlainText(), 'OLD TEXT')
        dialog.text.setPlainText('REPLACED'); dialog.set_rect(QRectF(40, 60, 250, 50))
        dialog.preview_change(); self.assertIsNotNone(dialog.draft)
        dialog.text.setPlainText('FINAL'); self.assertIsNone(dialog.draft)
        dialog.apply_change()
        text = PdfReader(BytesIO(dialog.data)).pages[0].extract_text()
        self.assertNotIn('OLD TEXT', text); self.assertIn('FINAL', text); self.assertIn('KEEP ME', text)
        self.assertFalse(dialog.pending)
        dialog.reject()


if __name__ == '__main__':
    unittest.main()
