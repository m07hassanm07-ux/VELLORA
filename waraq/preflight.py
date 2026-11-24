"""PDF preflight and privacy sanitation for publication workflows."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject
from .accessibility import is_marked


@dataclass(frozen=True)
class PreflightIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    version: str
    pages: int
    encrypted: bool
    attachments: int
    fields: int
    signatures: int
    tagged: bool
    pdfa: bool
    issues: tuple[PreflightIssue, ...]


def _font_embedded(font) -> bool:
    font=font.get_object()
    descendants=font.get('/DescendantFonts') or []
    candidates=[item.get_object() for item in descendants] or [font]
    for candidate in candidates:
        descriptor=candidate.get('/FontDescriptor')
        if descriptor:
            descriptor=descriptor.get_object()
            if any(descriptor.get(key) is not None for key in ('/FontFile','/FontFile2','/FontFile3')):return True
    return False


def preflight_pdf(data: bytes, password: str = '') -> PreflightReport:
    reader=PdfReader(BytesIO(data),strict=False);encrypted=reader.is_encrypted
    if encrypted and not reader.decrypt(password):raise ValueError('كلمة مرور المستند غير صحيحة.')
    issues=[];fields=reader.get_fields() or {};signatures=sum(1 for field in fields.values() if str(field.get('/FT',''))=='/Sig')
    attachments=sum(1 for _ in reader.attachment_list)
    root=reader.trailer['/Root'];tagged=is_marked(root)
    language=str(root.get('/Lang','')).strip()
    metadata_stream=root.get('/Metadata');xmp=b''
    if metadata_stream:
        try:xmp=metadata_stream.get_object().get_data()
        except Exception:pass
    pdfa=b'pdfaid:part' in xmp.lower()
    if encrypted:issues.append(PreflightIssue('info','encrypted','المستند مشفّر؛ بعض أنظمة الأرشفة لا تقبل التشفير.'))
    if attachments:issues.append(PreflightIssue('warning','attachments',f'يحتوي المستند على {attachments} مرفقًا.'))
    if signatures:issues.append(PreflightIssue('warning','signatures','إعادة الحفظ قد تبطل التوقيعات الرقمية الموجودة.'))
    if not tagged:issues.append(PreflightIssue('warning','accessibility','المستند غير معلّم كبنية PDF قابلة للوصول.'))
    if not language:issues.append(PreflightIssue('warning','language','لغة المستند غير محددة؛ أضف لغة لتحسين قارئات الشاشة.'))
    if not pdfa:issues.append(PreflightIssue('info','pdfa','لا توجد دلالة موثوقة على توافق PDF/A.'))
    if not (reader.metadata and (reader.metadata.title or '').strip()):issues.append(PreflightIssue('info','title','عنوان المستند غير مُحدد.'))
    unembedded=[];javascript=False;blank_pages=[];image_pages=[]
    if root.get('/OpenAction') or root.get('/AA'):javascript=True
    names=root.get('/Names')
    if names and names.get_object().get('/JavaScript'):javascript=True
    for page_index,page in enumerate(reader.pages,1):
        resources=page.get('/Resources')
        fonts=resources.get_object().get('/Font') if resources else None
        xobjects=resources.get_object().get('/XObject') if resources else None
        has_image=False
        for reference in (xobjects.get_object().values() if xobjects else []):
            try:
                if str(reference.get_object().get('/Subtype',''))=='/Image':has_image=True;break
            except Exception:pass
        try:page_text=(page.extract_text() or '').strip()
        except Exception:page_text=''
        if not page_text and not xobjects:blank_pages.append(page_index)
        if has_image:image_pages.append(page_index)
        for name,font in (fonts.get_object().items() if fonts else []):
            if not _font_embedded(font):unembedded.append(f'{name} (صفحة {page_index})')
        if page.get('/AA'):javascript=True
        for reference in page.get('/Annots',[]):
            annotation=reference.get_object();action=annotation.get('/A')
            if action and str(action.get_object().get('/S',''))=='/JavaScript':javascript=True
    if unembedded:issues.append(PreflightIssue('warning','fonts',f'{len(unembedded)} استخدام خط غير مضمّن بالكامل.'))
    if blank_pages:issues.append(PreflightIssue('warning','blank_pages',f'صفحات فارغة محتملة: {", ".join(map(str,blank_pages[:12]))}.'))
    if image_pages and not tagged:issues.append(PreflightIssue('info','image_alt',f'توجد صور في {len(image_pages)} صفحة، وقد تحتاج نصًا بديلًا لإمكانية الوصول.'))
    if javascript:issues.append(PreflightIssue('warning','javascript','يحتوي المستند على إجراءات أو JavaScript؛ راجعها قبل النشر.'))
    version=data[:16].splitlines()[0].decode('ascii','replace').replace('%PDF-','') if data.startswith(b'%PDF-') else 'unknown'
    return PreflightReport(version,len(reader.pages),encrypted,attachments,len(fields),signatures,tagged,pdfa,tuple(issues))


def sanitize_pdf(data: bytes, *, remove_metadata: bool = True, remove_attachments: bool = True,
                 remove_javascript: bool = True) -> bytes:
    reader=PdfReader(BytesIO(data),strict=False)
    if reader.is_encrypted:raise ValueError('احفظ نسخة غير مشفرة أو افتحها داخل VELLORA قبل التنظيف.')
    writer=PdfWriter();writer.clone_document_from_reader(reader);root=writer._root_object
    if remove_metadata:
        writer._info=None;root.pop(NameObject('/Metadata'),None)
    if remove_attachments:
        for item in list(writer.attachment_list):item.delete()
    if remove_javascript:
        root.pop(NameObject('/OpenAction'),None);root.pop(NameObject('/AA'),None)
        names=root.get('/Names')
        if names:
            names=names.get_object();names.pop(NameObject('/JavaScript'),None)
            if remove_attachments:names.pop(NameObject('/EmbeddedFiles'),None)
        for page in writer.pages:
            page.pop(NameObject('/AA'),None)
            for reference in page.get('/Annots',[]):
                annotation=reference.get_object();action=annotation.get('/A')
                if action and str(action.get_object().get('/S',''))=='/JavaScript':annotation.pop(NameObject('/A'),None)
        for field in (writer.get_fields() or {}).values():field.pop(NameObject('/AA'),None)
    output=BytesIO();writer.write(output);writer.close();return output.getvalue()


def repair_accessibility_basics(data: bytes, language: str = 'ar', title: str = 'VELLORA Document') -> bytes:
    """Set safe language and title metadata without pretending to provide full PDF/UA tagging."""
    language=(language or 'ar').strip()[:32];title=(title or 'VELLORA Document').strip()[:250]
    reader=PdfReader(BytesIO(data),strict=False)
    if reader.is_encrypted:raise ValueError('افتح المستند المحمي داخل VELLORA قبل إصلاح خصائص الوصول.')
    writer=PdfWriter();writer.clone_document_from_reader(reader)
    writer._root_object[NameObject('/Lang')]=TextStringObject(language)
    metadata={str(key):str(value) for key,value in (reader.metadata or {}).items() if value is not None}
    metadata['/Title']=title;writer.add_metadata(metadata)
    output=BytesIO();writer.write(output);writer.close();return output.getvalue()
