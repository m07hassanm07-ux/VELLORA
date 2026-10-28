import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject,
                           NumberObject, RectangleObject, TextStringObject)

from waraq.professional import (export_page_images, extract_text,
                                fill_form_fields, inspect_signatures,
                                list_form_fields, secure_redact_page)
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

    def test_secure_redaction_removes_page_text_objects(self):
        data = text_overlay(300, 400, Overlay("SECRET-123", "center", 24))
        self.assertIn("SECRET-123", extract_text(data))
        result = secure_redact_page(data, 0, [(0, 0, 300, 400)], dpi=72)
        self.assertNotIn("SECRET-123", extract_text(result))
        self.assertEqual(len(PdfReader(BytesIO(result)).pages), 1)


if __name__ == "__main__": unittest.main()
