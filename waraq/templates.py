"""Portable single-page templates for Waraqa.

The format is a small ZIP with a JSON manifest and a standards-compliant PDF.
No executable code or external path is stored in a template.
"""
from io import BytesIO
import json, zipfile
from pypdf import PdfReader

FORMAT = 'waraqa-template-1'


def encode_template(pdf: bytes, name: str) -> bytes:
    reader = PdfReader(BytesIO(pdf))
    if reader.is_encrypted or len(reader.pages) != 1:
        raise ValueError('يجب أن يحتوي القالب على صفحة PDF واحدة غير مشفرة.')
    manifest = {'format': FORMAT, 'name': (name.strip() or 'قالب ورقة')[:120]}
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        archive.writestr('page.pdf', pdf)
    return output.getvalue()


def decode_template(data: bytes) -> tuple[str, bytes]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if names != {'manifest.json', 'page.pdf'}:
                raise ValueError
            info = archive.getinfo('page.pdf')
            if info.file_size > 250 * 1024 * 1024:
                raise ValueError
            manifest = json.loads(archive.read('manifest.json'))
            pdf = archive.read('page.pdf')
        if manifest.get('format') != FORMAT or len(PdfReader(BytesIO(pdf)).pages) != 1:
            raise ValueError
        return str(manifest.get('name') or 'قالب ورقة')[:120], pdf
    except Exception as exc:
        raise ValueError('ملف القالب غير صالح أو تالف.') from exc


def builtin_template(kind: str) -> tuple[str, bytes]:
    """Create an editable, local template without external assets."""
    from pypdf import PdfWriter
    from .editing import prepare_page, edit_page
    writer=PdfWriter();writer.add_blank_page(595.28,841.89);stream=BytesIO();writer.write(stream)
    data=prepare_page(stream.getvalue())
    if kind=='letter':
        name='خطاب رسمي'
        data=edit_page(data,text='اسم المؤسسة',rect=(55,45,485,55),size=25,bold=True,alignment='right',color='#087a63')
        data=edit_page(data,text='التاريخ:    /    /\nإلى السيد/ة: ................................................\nالموضوع: ................................................',rect=(55,135,485,105),size=15,alignment='right')
        data=edit_page(data,text='تحية طيبة وبعد،\n\nاكتب نص الخطاب هنا.\n\nوتفضلوا بقبول فائق الاحترام.',rect=(55,285,485,270),size=16,alignment='right')
        data=edit_page(data,text='الاسم: ............................\nالتوقيع: ..........................',rect=(55,650,240,85),size=14,alignment='right')
    elif kind=='meeting':
        name='محضر اجتماع'
        data=edit_page(data,text='محضر اجتماع',rect=(55,45,485,60),size=28,bold=True,alignment='center',color='#087a63')
        data=edit_page(data,text='التاريخ: ....................     الوقت: ....................\nالمكان: ........................................................\nالحضور: ........................................................',rect=(55,145,485,115),size=15,alignment='right')
        data=edit_page(data,text='جدول الأعمال',rect=(55,315,485,45),size=21,bold=True,alignment='right')
        data=edit_page(data,text='1. ............................................................\n2. ............................................................\n3. ............................................................',rect=(55,385,485,120),size=16,alignment='right')
        data=edit_page(data,text='القرارات والإجراءات',rect=(55,560,485,45),size=21,bold=True,alignment='right')
        data=edit_page(data,text='• القرار: .....................................................\n• المسؤول: ..........................  الموعد: ................',rect=(55,630,485,100),size=15,alignment='right')
    else:
        name='تقرير عمل'
        data=edit_page(data,text='تقرير عمل',rect=(55,45,485,60),size=28,bold=True,alignment='right',color='#087a63')
        data=edit_page(data,text='اسم المشروع أو الإدارة\nالفترة: ..........................',rect=(55,125,485,75),size=16,alignment='right')
        for title,y in [('الملخص التنفيذي',255),('النتائج الرئيسية',430),('التوصيات والخطوات القادمة',605)]:
            data=edit_page(data,text=title,rect=(55,y,485,45),size=20,bold=True,alignment='right')
            data=edit_page(data,text='اكتب المحتوى هنا...',rect=(55,y+62,485,80),size=15,alignment='right',color='#566b79')
    return name,data
