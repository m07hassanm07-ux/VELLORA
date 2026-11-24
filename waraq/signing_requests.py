"""Local sequential signing requests with portable PDF handoff."""
from base64 import b64decode, b64encode
from email.message import EmailMessage
from email.policy import SMTP
from io import BytesIO
import json
from pathlib import Path
import uuid

from PySide6.QtCore import QLockFile

from .core import atomic_write
from .projects import data_directory, protect_local, unprotect_local


def request_fields(data):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.fields import enumerate_sig_fields

    reader = PdfFileReader(BytesIO(data))
    return sorted(name for name, _, _ in enumerate_sig_fields(reader, filled_status=False)
                  if name.startswith('VelloraRequest_'))


def create_request(title, addresses, data):
    from email.headerregistry import Address
    from pyhanko.pdf_utils.generic import NumberObject, pdf_name
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field

    title = ' '.join(title.split())[:150]
    if not title or not 1 <= len(addresses) <= 20:
        raise ValueError('اكتب عنوانًا وأضف من 1 إلى 20 موقّعًا.')
    try:
        addresses = [Address(addr_spec=email.strip()).addr_spec for email in addresses]
        if any('@' not in email for email in addresses):
            raise ValueError()
    except (ValueError, IndexError) as exc:
        raise ValueError('اكتب بريدًا إلكترونيًا صالحًا لكل موقّع، في سطر مستقل.') from exc
    if len({email.casefold() for email in addresses}) != len(addresses):
        raise ValueError('كل موقّع يحتاج عنوان بريد مختلفًا.')
    identifier = uuid.uuid4().hex
    writer = IncrementalPdfFileWriter(BytesIO(data))
    if writer.prev.embedded_signatures:
        raise ValueError('ابدأ طلب التوقيع بنسخة PDF غير موقّعة.')
    signers = []
    for index, email in enumerate(addresses, 1):
        field = f'VelloraRequest_{identifier}_{index:02}'
        append_signature_field(writer, SigFieldSpec(field))
        signers.append({'email': email, 'field': field, 'status': 'waiting'})
    writer.root['/AcroForm'][pdf_name('/SigFlags')] = NumberObject(3)
    writer.update_container(writer.root['/AcroForm'])
    output = BytesIO()
    writer.write(output)
    return {'id': identifier, 'title': title, 'signers': signers, 'pdf': output.getvalue()}


def next_signer(request):
    return next((signer for signer in request['signers'] if signer['status'] != 'signed'), None)


def draft_email(request):
    signer = next_signer(request)
    if signer is None:
        raise ValueError('اكتملت جميع التوقيعات.')
    message = EmailMessage(policy=SMTP)
    message['X-Unsent'] = '1'
    message['To'] = signer['email']
    message['Subject'] = 'طلب توقيع — ' + request['title']
    message.set_content(
        'يرجى توقيع ملف PDF المرفق رقميًا وإعادة النسخة الموقّعة بالرد على هذه الرسالة.\n'
        'في VELLORA اختر «أدوات ← توقيع ملف طلب وارد»، ثم اختر المرفق وشهادتك.\n'
        f'حقل التوقيع المخصص لك: {signer["field"]}\n'
    )
    message.add_attachment(request['pdf'], maintype='application', subtype='pdf', filename='Vellora-request.pdf')
    return message.as_bytes()


def inspect_return(request, data):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.diff_analysis import DEFAULT_DIFF_POLICY, DiffResult, ModificationLevel
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel

    signer = next_signer(request)
    if signer is None or len(data) <= len(request['pdf']) or not data.startswith(request['pdf']):
        raise ValueError('الملف المرتجع يجب أن يكون نسخة موقّعة من آخر PDF أُعدّ لهذا الطلب.')
    expected = {entry['field'] for entry in request['signers'] if entry['status'] == 'signed'}
    expected.add(signer['field'])
    reader = PdfFileReader(BytesIO(data))
    base_revision = PdfFileReader(BytesIO(request['pdf'])).total_revisions - 1
    diff = DEFAULT_DIFF_POLICY.review_file(reader, base_revision)
    if (not isinstance(diff, DiffResult) or diff.modification_level > ModificationLevel.FORM_FILLING
            or diff.changed_form_fields - {signer['field']}):
        raise ValueError('تغيّر محتوى المستند أو حقل آخر خارج حقل التوقيع المخصص.')
    signatures = reader.embedded_signatures
    if len(signatures) != len(expected) or {sig.field_name for sig in signatures} != expected:
        raise ValueError('وقّع الحقل المخصص للموقّع الحالي فقط، وبالترتيب المحدد.')
    result = None
    for signature in signatures:
        status = validate_pdf_signature(signature)
        if not status.intact or not status.valid or status.docmdp_ok is False:
            raise ValueError('تعذر التحقق من سلامة أحد التوقيعات أو من التعديلات بعده.')
        if signature.field_name == signer['field']:
            if status.coverage != SignatureCoverageLevel.ENTIRE_FILE:
                raise ValueError('الملف يحتوي تعديلات بعد التوقيع الأخير.')
            result = (signature.signer_cert.subject.human_friendly, status.trusted)
    return result


class RequestStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_directory() / 'signing-requests'

    def ids(self):
        return [path.stem for path in sorted(self.root.glob('*.request'))]

    def path(self, identifier):
        if uuid.UUID(hex=identifier).hex != identifier:
            raise ValueError('معرّف الطلب غير صالح.')
        return self.root / (identifier + '.request')

    def load(self, identifier):
        payload = json.loads(unprotect_local(self.path(identifier).read_bytes()))
        payload['pdf'] = b64decode(payload['pdf'], validate=True)
        return payload

    def save(self, request, *, previous=None):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(request['id'])
        lock = QLockFile(str(path) + '.lock')
        if not lock.tryLock(0):
            raise ValueError('الطلب مفتوح في عملية أخرى. أعد المحاولة.')
        try:
            if path.exists() and self.load(request['id']) != previous:
                raise ValueError('تغير الطلب منذ فتحه. اختره مجددًا ثم أعد المحاولة.')
            payload = dict(request, pdf=b64encode(request['pdf']).decode('ascii'))
            atomic_write(path, protect_local(json.dumps(payload, ensure_ascii=False).encode('utf-8')))
        finally:
            lock.unlock()
