from io import BytesIO
import unittest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
import pypdfium2 as pdfium
from test_editing import text_fixture
from waraq.editing import inspect_page, prepare_page, edit_page
from waraq.textlayout import group_text, find_matches, extract_text
from waraq.editor_dialog import PageEditorDialog
from waraq.rendering import ensure_font_support, render_image


class TextLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([]); ensure_font_support()

    def test_word_edit_inside_one_object_preserves_other_glyphs(self):
        data = prepare_page(text_fixture())
        words = group_text(data, inspect_page(data)[2], 'word')
        self.assertEqual([w.text for w in words], ['OLD', 'TEXT', 'KEEP', 'ME'])
        word = words[0]
        changed = edit_page(data, word.indices, selected_chars=word.chars, text='NEW', rect=(40, 50, 50, 40), size=16)
        text = extract_text(changed)
        self.assertNotIn('OLD', text); self.assertIn('TEXT', text); self.assertIn('KEEP ME', text)
        with pdfium.PdfDocument(data) as before, pdfium.PdfDocument(changed) as after:
            a, b = render_image(before, 0, 1), render_image(after, 0, 1)
            # Original suffix at its original location, with its embedded font.
            mismatches = sum(a.pixel(x,y) != b.pixel(x,y) for y in range(60,85) for x in range(80,135))
            self.assertLess(mismatches, 40)

    def test_paragraphs_keep_separate_lines_when_gap_is_large_and_style_inferred(self):
        data = prepare_page(text_fixture())
        groups = group_text(data, inspect_page(data)[2])
        self.assertEqual([g.text for g in groups], ['OLD TEXT', 'KEEP ME'])
        self.assertEqual(groups[0].size, 16)
        self.assertEqual(groups[0].family, 'Helvetica')
        self.assertEqual(groups[0].color, '#000000')

    def test_bilingual_search_normalizes_and_returns_positions(self):
        data = edit_page(prepare_page(text_fixture()), text='اختبار البحث SEARCH test', rect=(30,200,420,70), size=20)
        self.assertEqual(len(find_matches(data, 'search')), 1)
        found = find_matches(data, 'البحث')
        self.assertEqual(len(found), 1); self.assertTrue(found[0]['rects'])

    def test_editor_word_mode_and_style_selection(self):
        dialog = PageEditorDialog(text_fixture())
        self.assertTrue(dialog.format_bar.isHidden())
        dialog.group_mode.setCurrentIndex(dialog.group_mode.findData('word'))
        dialog.objects.item(0).setSelected(True)
        self.assertFalse(dialog.format_bar.isHidden())
        self.assertEqual(dialog.text.toPlainText(), 'OLD')
        self.assertEqual(dialog.color.currentData(), '#000000')
        dialog.text.setPlainText('NEW'); dialog.set_rect(QRectF(40,50,50,40)); dialog.apply_change()
        text = extract_text(dialog.data)
        self.assertNotIn('OLD',text); self.assertIn('TEXT',text)
        dialog.reject()
