from io import BytesIO
import unittest
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DictionaryObject,NameObject,TextStringObject
from waraq.preflight import preflight_pdf,sanitize_pdf


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


if __name__=='__main__':unittest.main()
