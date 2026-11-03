import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject,
                           NumberObject, RectangleObject, TextStringObject)

from waraq.professional import (add_attachment, attachment_bytes, list_attachments, remove_attachment,
                                add_form_field, export_page_images, extract_text,
                                fill_form_fields, inspect_signatures,
                                list_form_fields, secure_redact_page, secure_redact_text)
from waraq.rendering import text_overlay
from waraq.core import Overlay


def sample_form():
    writer = PdfWriter()
    page = writer.add_blank_page(300, 400)
    field = DictionaryObject({
        NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject("employee"),
        NameObject("/V"): TextStringObject("Old"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/Type"): NameObject("/Annot"), NameObject("/F"): NumberObject(4),
        NameObject("/Rect"): RectangleObject((20, 300, 200, 330)),
    })
    ref = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([ref])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([ref]),
        NameObject("/NeedAppearances"): NumberObject(1),
    })
    output = BytesIO(); writer.write(output); writer.close(); return output.getvalue()


class ProfessionalTests(unittest.TestCase):
    def test_list_and_fill_form(self):
        data = sample_form()
        fields = list_form_fields(data)
        self.assertEqual([(f.name, f.kind, f.value) for f in fields], [("employee", "/Tx", "Old")])
        result = fill_form_fields(data, {"employee": "Mohamed"})
        self.assertEqual(str(PdfReader(BytesIO(result)).get_fields()["employee"]["/V"]), "Mohamed")

    def test_unknown_form_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "غير موجودة"):
            fill_form_fields(sample_form(), {"missing": "x"})

    def test_create_text_checkbox_and_choice_fields(self):
        writer = PdfWriter(); writer.add_blank_page(300, 400); stream = BytesIO(); writer.write(stream)
        data = add_form_field(stream.getvalue(), 0, "text", "full_name", (20, 30, 180, 30), value="Ali")
        data = add_form_field(data, 0, "checkbox", "approved", (20, 80, 20, 20), value="yes")
        data = add_form_field(data, 0, "choice", "department", (20, 120, 160, 30), options=["HR", "IT"])
        fields = {field.name: field for field in list_form_fields(data)}
        self.assertEqual(set(fields), {"full_name", "approved", "department"})
        self.assertEqual(fields["full_name"].value, "Ali")
        self.assertEqual(fields["department"].options, ("HR", "IT"))
        with self.assertRaisesRegex(ValueError, "بهذا الاسم"):
            add_form_field(data, 0, "text", "full_name", (20, 200, 100, 20))

    def test_export_images_and_text(self):
        writer = PdfWriter(); writer.add_blank_page(144, 72); stream = BytesIO(); writer.write(stream)
        self.assertEqual(extract_text(stream.getvalue()), "")
        with tempfile.TemporaryDirectory() as directory:
            paths = export_page_images(stream.getvalue(), directory, dpi=72)
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].is_file())
            self.assertTrue(paths[0].read_bytes().startswith(b"\x89PNG"))

    def test_unsigned_document(self):
        writer = PdfWriter(); writer.add_blank_page(100, 100); stream = BytesIO(); writer.write(stream)
        self.assertEqual(inspect_signatures(stream.getvalue()), [])

    def test_attachment_lifecycle(self):
        writer=PdfWriter();writer.add_blank_page(100,100);stream=BytesIO();writer.write(stream)
        data=add_attachment(stream.getvalue(),'notes.txt',b'hello','Work notes')
        self.assertEqual([(item.name,item.size) for item in list_attachments(data)],[('notes.txt',5)])
        self.assertEqual(attachment_bytes(data,'notes.txt'),b'hello')
        with self.assertRaisesRegex(ValueError,'بهذا الاسم'):add_attachment(data,'NOTES.TXT',b'x')
        result=remove_attachment(data,'notes.txt');self.assertEqual(list_attachments(result),[])

    def test_secure_redaction_removes_page_text_objects(self):
        data = text_overlay(300, 400, Overlay("SECRET-123", "center", 24))
        self.assertIn("SECRET-123", extract_text(data))
        result = secure_redact_page(data, 0, [(0, 0, 300, 400)], dpi=72)
        self.assertNotIn("SECRET-123", extract_text(result))
        self.assertEqual(len(PdfReader(BytesIO(result)).pages), 1)

    def test_secure_redaction_by_search(self):
        data=text_overlay(300,400,Overlay('ACCOUNT-7788','center',24))
        result,count=secure_redact_text(data,'account-7788',dpi=72)
        self.assertEqual(count,1);self.assertNotIn('ACCOUNT-7788',extract_text(result))


if __name__ == "__main__": unittest.main()
