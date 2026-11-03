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
        results=validate_signatures(signed)
        self.assertEqual(len(results),1);self.assertTrue(results[0].intact);self.assertTrue(results[0].valid)
        self.assertFalse(results[0].trusted);self.assertIn('Waraqa Test Signer',results[0].signer)


if __name__=='__main__':unittest.main()
