from io import BytesIO
import unittest
from pypdf import PdfReader, PdfWriter
from PySide6.QtWidgets import QApplication, QStackedWidget

from waraq.templates import encode_template, decode_template, builtin_template
from waraq.editor_dialog import PageEditorDialog
from waraq.app import MainWindow, CreateDocumentDialog


def blank_page():
    writer=PdfWriter();writer.add_blank_page(595,842);stream=BytesIO();writer.write(stream)
    return stream.getvalue()


class TemplateAndInlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_template_roundtrip_and_strict_members(self):
        data=blank_page();name,pdf=decode_template(encode_template(data,'خطاب الشركة'))
        self.assertEqual(name,'خطاب الشركة');self.assertEqual(len(PdfReader(BytesIO(pdf)).pages),1)
        with self.assertRaises(ValueError):decode_template(b'not a template')

    def test_builtin_business_templates_are_single_page_and_editable_text(self):
        for kind in ('report','letter','meeting','invoice','quote','certificate','contract'):
            name,pdf=builtin_template(kind);reader=PdfReader(BytesIO(pdf))
            self.assertTrue(name);self.assertEqual(len(reader.pages),1)
            self.assertTrue((reader.pages[0].extract_text() or '').strip())

    def test_embedded_editor_is_widget_and_lists_system_fonts(self):
        stack=QStackedWidget();editor=PageEditorDialog(blank_page(),stack,embedded=True);stack.addWidget(editor)
        self.assertTrue(editor.embedded);self.assertGreater(editor.font.count(),0)
        self.assertFalse(editor.isWindow());editor.close();stack.close()

    def test_new_document_dialog_offers_blank_pages_and_templates(self):
        dialog=CreateDocumentDialog(has_document=False)
        kinds=[dialog.choices.item(i).data(256) for i in range(dialog.choices.count())]
        self.assertIn('blank-a4',kinds);self.assertIn('letter',kinds);self.assertIn('saved',kinds)
        dialog.close()

    def test_main_window_enters_and_leaves_inline_edit_mode(self):
        window=MainWindow();window.document.import_bytes('blank.pdf',blank_page());window.refresh()
        window.edit_page_content();self.assertIsNotNone(window._page_editor)
        self.assertIs(window.stack.currentWidget(),window._page_editor)
        window.cancel_inline_edit();self.assertIsNone(window._page_editor)
        self.assertIs(window.stack.currentWidget(),window.splitter)
        window.document.mark_saved();window.close()


if __name__=='__main__':unittest.main()
