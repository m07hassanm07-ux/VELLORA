"""Cryptographic PDF signing and offline signature inspection using pyHanko."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import uuid


@dataclass(frozen=True)
class ValidationResult:
    field_name: str
    signer: str
    intact: bool
    valid: bool
    trusted: bool
    summary: str


def sign_pkcs12(data: bytes, certificate: str | Path, password: str,
                *, reason: str = '', location: str = '', field_name: str | None = None) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    certificate=Path(certificate)
    if certificate.suffix.lower() not in {'.pfx','.p12'} or not certificate.is_file():
        raise ValueError('اختر ملف شهادة PKCS#12 صالحًا بصيغة PFX أو P12.')
    signer=signers.SimpleSigner.load_pkcs12(certificate,passphrase=password.encode('utf-8'))
    if signer is None:raise ValueError('تعذر فتح الشهادة. تحقق من كلمة المرور ومحتوى ملف الشهادة.')
    field=field_name or 'WaraqaSignature_'+uuid.uuid4().hex[:12]
    metadata=signers.PdfSignatureMetadata(field_name=field,reason=reason[:500] or None,location=location[:500] or None)
    source=BytesIO(data);writer=IncrementalPdfFileWriter(source);output=BytesIO()
    signers.sign_pdf(writer,metadata,signer=signer,output=output,existing_fields_only=field_name is not None)
    return output.getvalue()


def validate_signatures(data: bytes) -> list[ValidationResult]:
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    reader=PdfFileReader(BytesIO(data));results=[]
    for embedded in reader.embedded_signatures:
        try:
            status=validate_pdf_signature(embedded)
            certificate=embedded.signer_cert
            signer=certificate.subject.human_friendly if certificate is not None else ''
            results.append(ValidationResult(embedded.field_name,signer,bool(status.intact),bool(status.valid),bool(status.trusted),status.summary()))
        except Exception as exc:
            results.append(ValidationResult(embedded.field_name,'',False,False,False,f'تعذر التحقق: {exc}'))
    return results
