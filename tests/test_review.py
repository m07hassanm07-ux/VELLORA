from io import BytesIO
import unittest
from pypdf import PdfReader
import pypdfium2 as pdfium
from PySide6.QtWidgets import QApplication
from test_editing import text_fixture
from waraq.review import apply_review,list_review
from waraq.textlayout import find_matches
from waraq.core import Document
from waraq.rendering import ensure_font_support,render_image


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);ensure_font_support()

    def test_annotations_have_metadata_and_appearances_without_rewriting_text(self):
        source=text_fixture();data=source
        rects=find_matches(data,'OLD')[0]['rects']
        for action,payload in [('highlight',{'rects':rects,'text':'OLD','color':'#ffdd20'}),
            ('note',{'point':(200,100),'text':'ملاحظة عربية'}),
            ('arrow',{'start':(200,200),'end':(350,280),'text':'انظر هنا'}),
            ('stamp',{'rect':(200,330,180,60),'text':'معتمد'})]:
            data=apply_review(data,0,action,payload|{'author':'مراجع تجريبي'})
        annotations=PdfReader(BytesIO(data)).pages[0]['/Annots']
        self.assertEqual(len(annotations),4)
        self.assertEqual({a.get_object()['/Subtype'] for a in annotations},{'/Highlight','/Text','/Line','/Stamp'})
        for ref in annotations:
            obj=ref.get_object();self.assertIn('/AP',obj);self.assertTrue(obj['/NM'].startswith('waraq-'));self.assertEqual(obj['/T'],'مراجع تجريبي')
        self.assertEqual(PdfReader(BytesIO(source)).pages[0].extract_text(),PdfReader(BytesIO(data)).pages[0].extract_text())
        with pdfium.PdfDocument(source) as original,pdfium.PdfDocument(data) as reviewed:
            before,after=render_image(original,0,.7),render_image(reviewed,0,.7)
            count=sum(before.pixel(x,y)!=after.pixel(x,y) for y in range(before.height()) for x in range(before.width()))
            self.assertGreater(count,300)
        self.assertEqual(list_review(data,0)[1]['text'],'ملاحظة عربية')

    def test_edit_delete_and_undo_after_reopening(self):
        original=text_fixture();data=apply_review(original,0,'note',{'point':(200,200),'text':'before'})
        name=list_review(data,0)[0]['id']
        data=apply_review(data,0,'update',{'id':name,'text':'بعد التعديل'})
        self.assertEqual(list_review(data,0)[0]['text'],'بعد التعديل')
        model=Document();model.import_bytes('sample.pdf',original);uid=model.pages[0].uid
        model.replace_document(data);self.assertEqual(uid,model.pages[0].uid)
        model.undo();self.assertFalse(list_review(model.build_bytes(),0))
        model.redo();self.assertEqual(len(list_review(model.build_bytes(),0)),1)
        deleted=apply_review(data,0,'delete',{'id':name});self.assertFalse(list_review(deleted,0))
        with self.assertRaises(ValueError):apply_review(data,0,'delete',{'id':'foreign-annotation'})

    def test_stamp_position_on_rotated_pages(self):
        for angle in (0,90,180,270):
            source=text_fixture(rotation=angle);rect=(200,180,180,60)
            changed=apply_review(source,0,'stamp',{'rect':rect,'text':'للمراجعة'})
            with pdfium.PdfDocument(source) as original,pdfium.PdfDocument(changed) as reviewed:
                a,b=render_image(original,0,.5),render_image(reviewed,0,.5)
                difference=[(x,y) for y in range(a.height()) for x in range(a.width()) if a.pixel(x,y)!=b.pixel(x,y)]
                self.assertTrue(difference)
                self.assertGreaterEqual(min(x for x,y in difference),98)
                self.assertLessEqual(max(x for x,y in difference),192)
                self.assertGreaterEqual(min(y for x,y in difference),88)
                self.assertLessEqual(max(y for x,y in difference),122)
