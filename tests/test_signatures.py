from datetime import datetime,timedelta,timezone
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pypdf import PdfWriter

from waraq.signatures import sign_pkcs12,validate_signatures
from waraq.signing_requests import RequestStore, create_request, draft_email, inspect_return, request_fields


class SignatureTests(unittest.TestCase):
    def test_pkcs12_signing_produces_intact_untrusted_signature(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Waraqa Test Signer')])
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
        pfx=pkcs12.serialize_key_and_certificates(b'waraqa',key,cert,None,serialization.BestAvailableEncryption(b'secret-pass'))
        writer=PdfWriter();writer.add_blank_page(200,300);source=BytesIO();writer.write(source)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.pfx';path.write_bytes(pfx)
            signed=sign_pkcs12(source.getvalue(),path,'secret-pass',reason='Approval',location='Cairo')
            request = create_request('اختبار', ['first@example.com', 'second@example.com'], source.getvalue())
            store = RequestStore(Path(directory)/'requests')
            store.save(request)
            self.assertEqual(store.load(request['id']), request)
            self.assertNotIn(b'first@example.com', store.path(request['id']).read_bytes())
            from email import policy
            from email.parser import BytesParser
            mail = BytesParser(policy=policy.default).parsebytes(draft_email(request))
            self.assertEqual(str(mail['To']), 'first@example.com')
            self.assertEqual(next(mail.iter_attachments()).get_payload(decode=True), request['pdf'])
            first, second = request_fields(request['pdf'])
            from pyhanko.pdf_utils.generic import TextStringObject, pdf_name
            from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
            modified = IncrementalPdfFileWriter(BytesIO(request['pdf']))
            modified.root[pdf_name('/Lang')] = TextStringObject('fr')
            modified.update_root()
            changed_pdf = BytesIO()
            modified.write(changed_pdf)
            modified_signed = sign_pkcs12(changed_pdf.getvalue(), path, 'secret-pass', field_name=first)
            with self.assertRaises(ValueError):
                inspect_return(request, modified_signed)
            wrong = sign_pkcs12(request['pdf'], path, 'secret-pass', field_name=second)
            with self.assertRaises(ValueError):
                inspect_return(request, wrong)
            first_signed = sign_pkcs12(request['pdf'], path, 'secret-pass', field_name=first)
            self.assertIn('Waraqa Test Signer', inspect_return(request, first_signed)[0])
            request['signers'][0]['status'] = 'signed'
            request['pdf'] = first_signed
            second_signed = sign_pkcs12(first_signed, path, 'secret-pass', field_name=second)
            self.assertIn('Waraqa Test Signer', inspect_return(request, second_signed)[0])
        results=validate_signatures(signed)
        self.assertEqual(len(results),1);self.assertTrue(results[0].intact);self.assertTrue(results[0].valid)
        self.assertFalse(results[0].trusted);self.assertIn('Waraqa Test Signer',results[0].signer)


if __name__=='__main__':unittest.main()
