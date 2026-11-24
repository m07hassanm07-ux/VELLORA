from io import BytesIO
import unittest
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject
from waraq.accessibility import AccessibilityDocument
from waraq.pdfua_validation import parse_report
from waraq.preflight import preflight_pdf,sanitize_pdf,repair_accessibility_basics


class PreflightTests(unittest.TestCase):
    def fixture(self):
        writer=PdfWriter();writer.add_blank_page(200,300);writer.add_metadata({'/Title':'Confidential'})
        writer.add_attachment('secret.txt',b'hidden')
        writer._root_object[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject('app.alert(1)')})
        stream=BytesIO();writer.write(stream);return stream.getvalue()

    def test_preflight_detects_risks_and_sanitize_removes_them(self):
        data=self.fixture();report=preflight_pdf(data)
        self.assertEqual(report.attachments,1);self.assertIn('javascript',{item.code for item in report.issues})
        result=sanitize_pdf(data);reader=PdfReader(BytesIO(result))
        self.assertEqual(list(reader.attachment_list),[]);self.assertIsNone(reader.trailer['/Root'].get('/OpenAction'))
        self.assertFalse(reader.metadata)

    def test_accessibility_basics_sets_language_and_title(self):
        repaired=repair_accessibility_basics(self.fixture(),'ar','عنوان واضح')
        reader=PdfReader(BytesIO(repaired))
        self.assertEqual(str(reader.trailer['/Root']['/Lang']),'ar')
        self.assertEqual(reader.metadata.title,'عنوان واضح')

    def test_repair_existing_tags_preserves_marked_content_and_parent_tree(self):
        writer = PdfWriter()
        page = writer.add_blank_page(200, 300)
        tree = DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')})
        tree_ref = writer._add_object(tree)
        children = ArrayObject()
        for role, mcid in (('/P', 0), ('/Figure', 1)):
            tag = DictionaryObject({NameObject('/Type'): NameObject('/StructElem'),
                                    NameObject('/P'): tree_ref, NameObject('/S'): NameObject(role),
                                    NameObject('/Pg'): page.indirect_reference, NameObject('/K'): NumberObject(mcid)})
            children.append(writer._add_object(tag))
        tree[NameObject('/K')] = children
        tree[NameObject('/ParentTree')] = writer._add_object(DictionaryObject({
            NameObject('/Nums'): ArrayObject([NumberObject(0), ArrayObject(list(children))])
        }))
        page[NameObject('/StructParents')] = NumberObject(0)
        content = DecodedStreamObject()
        original = b'/P <</MCID 0>> BDC EMC /Figure <</MCID 1>> BDC 0 0 10 10 re f EMC'
        content.set_data(original)
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.root_object[NameObject('/StructTreeRoot')] = tree_ref
        writer.root_object[NameObject('/MarkInfo')] = DictionaryObject({NameObject('/Marked'): BooleanObject(True)})
        stream = BytesIO()
        writer.write(stream)

        doc = AccessibilityDocument(stream.getvalue())
        self.assertEqual([(tag.role, tag.page) for tag in doc.tags()], [('P', 1), ('Figure', 1)])
        doc.set_alt((1,), 'رسم يوضح البيانات')
        doc.move((1,), -1)
        doc.set_text_role((1,), 'H1')
        doc.set_metadata('مستند تجريبي', 'ar-EG')
        saved = doc.output()
        reopened = AccessibilityDocument(saved)
        self.assertEqual([(tag.role, tag.alt) for tag in reopened.tags()],
                         [('Figure', 'رسم يوضح البيانات'), ('H1', '')])
        self.assertEqual(reopened.issues(reopened.tags()), [])
        result = PdfReader(BytesIO(saved))
        self.assertTrue(result.root_object['/ViewerPreferences']['/DisplayDocTitle'].value)
        self.assertEqual(result.pages[0].get_contents().get_data(), original)
        structure = result.root_object['/StructTreeRoot']
        parents = structure['/ParentTree']['/Nums'][1]
        self.assertEqual(parents[0], structure['/K'][1])
        self.assertEqual(parents[1], structure['/K'][0])
        self.assertTrue(preflight_pdf(saved).tagged)

    def test_mark_info_without_structure_is_not_reported_as_tagged(self):
        writer = PdfWriter()
        writer.add_blank_page(200, 300)
        writer.root_object[NameObject('/MarkInfo')] = DictionaryObject({NameObject('/Marked'): BooleanObject(True)})
        stream = BytesIO()
        writer.write(stream)
        self.assertFalse(preflight_pdf(stream.getvalue()).tagged)

    def test_initial_tags_bind_text_and_image_without_changing_content(self):
        writer = PdfWriter()
        page = writer.add_blank_page(200, 300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        image = DecodedStreamObject()
        image.update({NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(1),
                      NameObject('/Height'): NumberObject(1), NameObject('/ColorSpace'): NameObject('/DeviceGray'),
                      NameObject('/BitsPerComponent'): NumberObject(8)})
        image.set_data(b'\xff')
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)}),
            NameObject('/XObject'): DictionaryObject({NameObject('/I1'): writer._add_object(image)}),
        })
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 20 50 Td (Sample text) Tj ET q 10 0 0 10 20 80 cm /I1 Do Q')
        page[NameObject('/Contents')] = writer._add_object(content)
        out = BytesIO()
        writer.write(out)
        doc = AccessibilityDocument(out.getvalue())
        doc.auto_tag()
        self.assertEqual([(tag.role, tag.page) for tag in doc.tags()],
                         [('Document', None), ('P', 1), ('Figure', 1)])
        doc.set_alt((0, 1), 'Example image')
        saved = PdfReader(BytesIO(doc.output()))
        self.assertEqual(saved.pages[0].extract_text().strip(), 'Sample text')
        operations = saved.pages[0].get_contents().operations
        self.assertEqual([args[1]['/MCID'] for args, op in operations if op == b'BDC'], [0, 1])
        tree = saved.root_object['/StructTreeRoot']
        parent_entries = tree['/ParentTree']['/Nums'][1].get_object()
        self.assertEqual(parent_entries, tree['/K']['/K'])

    def test_initial_tags_leave_complex_input_unchanged(self):
        writer = PdfWriter()
        page = writer.add_blank_page(200, 300)
        content = DecodedStreamObject()
        content.set_data(b'0 0 20 20 re f')
        page[NameObject('/Contents')] = writer._add_object(content)
        stream = BytesIO()
        writer.write(stream)
        doc = AccessibilityDocument(stream.getvalue())
        with self.assertRaisesRegex(ValueError, 'محتوى معقدًا'):
            doc.auto_tag()
        self.assertFalse(doc.changed)
        self.assertNotIn('/StructTreeRoot', doc.root)

    def test_verapdf_report_distinguishes_failure_from_missing_result(self):
        xml = b"""<report><jobs><job><validationReport isCompliant="false"><details>
          <rule clause="7.1" status="failed"><description>Missing tag</description></rule>
          </details></validationReport></job></jobs></report>"""
        self.assertEqual(parse_report(xml), (False, ['7.1 — Missing tag']))
        with self.assertRaises(ValueError):
            parse_report(b'<report/>')


if __name__=='__main__':unittest.main()
