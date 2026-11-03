from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

from waraq.core import Document, Overlay, PasswordRequired, atomic_write, parse_pages


def fixture(widths=(200, 300, 400), password=""):
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width, 500)
    writer.add_metadata({"/Title": "Input document", "/Author": "Test author"})
    if password:
        writer.encrypt(password, algorithm="AES-256")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def form_fixture(value):
    writer = PdfWriter()
    page = writer.add_blank_page(300, 500)
    field = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Tx"),
        NameObject("/T"): TextStringObject("name"),
        NameObject("/V"): TextStringObject(value),
        NameObject("/Rect"): ArrayObject([FloatObject(n) for n in (10, 10, 100, 30)]),
    })
    reference = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([reference])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([reference])})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document()
        self.original = fixture()
        self.doc.import_bytes("first.pdf", self.original)
        self.doc.mark_saved()

    def test_range_parser_and_arabic_numerals(self):
        self.assertEqual(parse_pages("٣، ١-٢،٣", 3), [2, 0, 1])
        for bad in ("", "0", "4", "3-1", "1,,2", "1-a", "1-2-3"):
            with self.assertRaises(ValueError, msg=bad):
                parse_pages(bad, 3)

    def test_reorder_rotate_merge_undo_and_input_immutability(self):
        self.doc.rotate([0], 90)
        self.assertTrue(self.doc.dirty)
        self.doc.undo()
        self.assertFalse(self.doc.dirty)
        self.doc.redo()
        self.doc.import_bytes("second.pdf", fixture((600,)))
        self.doc.reorder([p.uid for p in reversed(self.doc.pages)])
        saved = PdfReader(BytesIO(self.doc.build_bytes()))
        self.assertEqual([float(p.mediabox.width) for p in saved.pages], [600, 400, 300, 200])
        self.assertEqual(saved.pages[-1].rotation, 90)
        self.assertEqual(PdfReader(BytesIO(self.original)).pages[0].rotation, 0)
        self.assertEqual(saved.metadata.title, "Input document")

    def test_duplicate_pages_are_independent(self):
        self.doc.duplicate([0])
        self.doc.rotate([1], 180)
        output = PdfReader(BytesIO(self.doc.build_bytes()))
        self.assertEqual(len(output.pages), 4)
        self.assertEqual([p.rotation for p in output.pages[:2]], [0, 180])

    def test_extract_and_delete(self):
        self.doc.remove([1])
        self.assertEqual(len(self.doc.pages), 2)
        output = PdfReader(BytesIO(self.doc.build_bytes([1])))
        self.assertEqual(float(output.pages[0].mediabox.width), 400)
        with self.assertRaises(ValueError):
            self.doc.remove([0, 1])

    def test_pdf_two_header_is_not_downgraded(self):
        writer = PdfWriter()
        writer.add_blank_page(200, 500)
        writer.pdf_header = '%PDF-2.0'
        stream = BytesIO()
        writer.write(stream)
        doc = Document()
        doc.import_bytes('newer.pdf', stream.getvalue())
        self.assertTrue(doc.build_bytes().startswith(b'%PDF-2.0'))

    def test_encrypted_input_and_output(self):
        encrypted = fixture((200,), "input-pass")
        doc = Document()
        with self.assertRaises(PasswordRequired):
            doc.import_bytes("locked.pdf", encrypted)
        self.assertEqual(doc.pages, [])
        doc.import_bytes("locked.pdf", encrypted, "input-pass")
        output = PdfReader(BytesIO(doc.build_bytes(password="output-pass")))
        self.assertTrue(output.is_encrypted)
        self.assertFalse(output.decrypt("wrong"))
        self.assertTrue(output.decrypt("output-pass"))
        self.assertEqual(len(output.pages), 1)

    def test_encrypted_output_honors_restricted_permissions_and_owner_password(self):
        # Reserved ISO bits plus printing only; copy and modification are denied.
        permissions = sum(1 << bit for bit in range(6, 32)) | 4 | 2048
        output = PdfReader(BytesIO(self.doc.build_bytes(
            password="reader-pass", owner_password="owner-pass", permissions=permissions)))
        self.assertEqual(output.decrypt("reader-pass").name, "USER_PASSWORD")
        access = output.user_access_permissions
        self.assertTrue(access.PRINT in access)
        self.assertFalse(access.EXTRACT in access)
        fresh = PdfReader(BytesIO(self.doc.build_bytes(
            password="reader-pass", owner_password="owner-pass", permissions=permissions)))
        self.assertEqual(fresh.decrypt("owner-pass").name, "OWNER_PASSWORD")

    def test_failed_import_and_save_keep_state_and_destination(self):
        before = self.doc.fingerprint()
        with self.assertRaises(Exception):
            self.doc.import_bytes("broken.pdf", b"broken")
        self.assertEqual(before, self.doc.fingerprint())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.pdf"
            path.write_bytes(b"original")
            self.doc.add_overlay([0], Overlay("test"))
            with self.assertRaises(ValueError):
                self.doc.save(path)  # Missing renderer fails before touching the target.
            self.assertEqual(path.read_bytes(), b"original")
            atomic_write(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"replacement")
            self.assertEqual(list(Path(directory).glob(".waraq-*")), [])

    def test_attachments_survive_document_assembly(self):
        writer=PdfWriter();writer.add_blank_page(100,100);writer.add_attachment('source.txt',b'kept')
        stream=BytesIO();writer.write(stream)
        doc=Document();doc.import_bytes('attached.pdf',stream.getvalue())
        result=PdfReader(BytesIO(doc.build_bytes()))
        self.assertEqual(result.attachments['source.txt'],[b'kept'])

    def test_form_values_survive_merge_with_colliding_names(self):
        doc = Document()
        doc.import_bytes("a.pdf", form_fixture("Alice"))
        doc.import_bytes("b.pdf", form_fixture("Bob"))
        output = PdfReader(BytesIO(doc.build_bytes()))
        fields = output.get_fields()
        values = [field.get("/V") for field in fields.values() if field.get("/FT") == "/Tx"]
        self.assertCountEqual(values, ["Alice", "Bob"])
        self.assertEqual(len(output.pages), 2)


if __name__ == "__main__":
    unittest.main()
