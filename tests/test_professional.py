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
from waraq.form_detection import suggest_text_fields


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

    def test_create_text_checkbox_choice_button_and_calculation_fields(self):
        writer = PdfWriter(); writer.add_blank_page(300, 400); stream = BytesIO(); writer.write(stream)
        data = add_form_field(stream.getvalue(), 0, "text", "full_name", (20, 30, 180, 30), value="Ali")
        data = add_form_field(data, 0, "checkbox", "approved", (20, 80, 20, 20), value="yes")
        data = add_form_field(data, 0, "choice", "department", (20, 120, 160, 30), options=["HR", "IT"])
        data = add_form_field(data, 0, "text", "amount_a", (20, 160, 100, 25), value="12.5")
        data = add_form_field(data, 0, "text", "amount_b", (130, 160, 100, 25), value="7.5")
        data = add_form_field(data, 0, "calculation", "total", (20, 200, 160, 30), options=["amount_a", "amount_b"])
        data = add_form_field(data, 0, "button", "reset", (20, 250, 100, 30), value="Reset")
        fields = {field.name: field for field in list_form_fields(data)}
        self.assertEqual(set(fields), {"full_name", "approved", "department", "amount_a", "amount_b", "total", "reset"})
        self.assertEqual(fields["full_name"].value, "Ali")
        self.assertEqual(fields["department"].options, ("HR", "IT"))
        filled = fill_form_fields(data, {"amount_a": "30", "amount_b": "12.25"})
        self.assertEqual(str(PdfReader(BytesIO(filled)).get_fields()["total"]["/V"]), "42.25")
        data = add_form_field(data, 0, "calculation", "average", (20, 290, 160, 22),
                              options=["total", "amount_b"], calculation="AVG")
        filled = fill_form_fields(data, {"amount_a": "٣٠", "amount_b": "١٢٫٢٥"})
        updated = PdfReader(BytesIO(filled)).get_fields()
        self.assertEqual(str(updated["average"]["/V"]), "27.25")
        self.assertEqual(str(updated["amount_b"]["/V"]), "12.25")
        with self.assertRaisesRegex(ValueError, "رقمًا صالحًا"):
            fill_form_fields(data, {"amount_a": "NaN"})
        with self.assertRaisesRegex(ValueError, "اختر قيمة"):
            fill_form_fields(data, {"department": "Unknown"})
        with self.assertRaisesRegex(ValueError, "بهذا الاسم"):
            add_form_field(data, 0, "text", "full_name", (20, 200, 100, 20))

    def test_required_field_rejects_blank(self):
        data = add_form_field(sample_form(), 0, "text", "required_name", (20, 130, 150, 20), required=True)
        with self.assertRaisesRegex(ValueError, "مطلوب"):
            fill_form_fields(data, {"required_name": " "})
        filled = fill_form_fields(data, {"required_name": "Ali"})
        self.assertEqual(PdfReader(BytesIO(filled)).get_fields()["required_name"]["/V"], "Ali")

    def test_suggests_text_blank_and_skips_existing_widget(self):
        data = text_overlay(300, 400, Overlay("Name: __________________", "center", 16))
        suggestions = suggest_text_fields(data, 0)
        self.assertEqual(len(suggestions), 1)
        label, rect = suggestions[0]
        self.assertEqual(label, "Name")
        with_field = add_form_field(data, 0, "text", "name", rect)
        reader = PdfReader(BytesIO(with_field))
        widget = reader.pages[0]["/Annots"][0].get_object()
        self.assertEqual(suggest_text_fields(with_field, 0, [widget["/Rect"]]), [])

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
