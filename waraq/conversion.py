"""Local conversion adapters. Office suites and browsers remain optional.

Subprocess arguments are passed as lists, never interpolated into a shell.
Every headless browser / LibreOffice invocation has a fresh private profile.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader

IMAGE_TYPES={'.png','.jpg','.jpeg','.tif','.tiff','.bmp','.webp'}
OFFICE_TYPES={'.doc','.docx','.rtf','.odt','.xls','.xlsx','.ods','.ppt','.pptx','.odp'}
SUPPORTED_TYPES=IMAGE_TYPES|OFFICE_TYPES|{'.pdf','.html','.htm','.txt'}


class ConversionError(ValueError): pass
class ConversionCancelled(ConversionError): pass


def find_browser() -> Path | None:
    roots=[Path(os.environ.get('PROGRAMFILES',r'C:\Program Files')),
           Path(os.environ.get('PROGRAMFILES(X86)',r'C:\Program Files (x86)')),
           Path(os.environ.get('LOCALAPPDATA',str(Path.home())))]
    for relative in ['Google/Chrome/Application/chrome.exe','Microsoft/Edge/Application/msedge.exe']:
        for root in roots:
            if (root/relative).is_file(): return root/relative
    return None


def find_libreoffice() -> Path | None:
    for root in [Path(os.environ.get('PROGRAMFILES',r'C:\Program Files')),Path(os.environ.get('PROGRAMFILES(X86)',r'C:\Program Files (x86)'))]:
        for name in ('soffice.com','soffice.exe'):
            candidate=root/'LibreOffice'/'program'/name
            if candidate.is_file():return candidate
    detected=shutil.which('libreoffice') or shutil.which('soffice')
    return Path(detected) if detected else None


def office_available(suffix: str) -> bool:
    if os.name!='nt': return False
    import winreg
    program='Word.Application' if suffix in {'.doc','.docx','.rtf','.txt'} else 'Excel.Application' if suffix in {'.xls','.xlsx'} else 'PowerPoint.Application' if suffix in {'.ppt','.pptx'} else None
    if program:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,program+'\\CLSID'):return True
        except OSError:pass
    return False


def _read_pdf(path: Path) -> bytes:
    if not path.is_file():raise ConversionError('لم يُنشئ محرك التحويل ملف PDF. قد يحتاج المستند إلى فتحه داخل البرنامج الأصلي أولًا.')
    data=path.read_bytes()
    if not data.startswith(b'%PDF-') or not len(PdfReader(BytesIO(data)).pages):
        raise ConversionError('ملف التحويل الناتج غير صالح.')
    return data


def run_process(args: list[str], workdir: Path, progress: Callable[[], bool] | None=None, timeout=120) -> None:
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    process=subprocess.Popen(args,cwd=str(workdir),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=creationflags)
    deadline=time.monotonic()+timeout
    try:
        while process.poll() is None:
            if progress and not progress():raise ConversionCancelled('تم إلغاء التحويل.')
            if time.monotonic()>deadline:raise ConversionError('استغرق التحويل وقتًا طويلًا. افتح المستند الأصلي وتحقق من عدم وجود مطالبات بكلمة مرور أو تسجيل دخول.')
            time.sleep(0.08)
        if process.returncode:
            raise ConversionError(f'تعذر التحويل بواسطة البرنامج الخارجي (رمز {process.returncode}).')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


def image_to_pdf(path: Path) -> bytes:
    frames=[]
    with Image.open(path) as image:
        for frame in ImageSequence.Iterator(image):
            current=ImageOps.exif_transpose(frame).convert('RGBA')
            background=Image.new('RGB',current.size,'white')
            background.paste(current,mask=current.getchannel('A'))
            frames.append(background)
    if not frames:raise ConversionError('الصورة لا تحتوي على صفحات.')
    output=BytesIO()
    frames[0].save(output,format='PDF',save_all=True,append_images=frames[1:],resolution=150)
    for frame in frames:frame.close()
    return output.getvalue()


def web_to_pdf(url: str, progress: Callable[[],bool] | None=None, *, local_file=False) -> bytes:
    parsed=urlparse(url)
    if not (parsed.scheme in ('http','https') and parsed.netloc) and not (local_file and parsed.scheme=='file'):
        raise ConversionError('أدخل عنوانًا كاملًا يبدأ بـ https:// أو http://')
    browser=find_browser()
    if not browser:raise ConversionError('حفظ الويب يحتاج Google Chrome أو Microsoft Edge مثبتًا على الجهاز.')
    with tempfile.TemporaryDirectory(prefix='waraq-web-') as directory:
        folder=Path(directory);output=folder/'web.pdf'
        args=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
              '--disable-extensions','--disable-background-networking','--disable-component-update',
              '--no-pdf-header-footer','--timeout=45000',f'--user-data-dir={folder / "profile"}',f'--print-to-pdf={output}',url]
        run_process(args,folder,progress,timeout=90)
        return _read_pdf(output)


def convert_file(path: str | Path, progress: Callable[[],bool] | None=None) -> bytes:
    path=Path(path).resolve()
    suffix=path.suffix.lower()
    if suffix=='.pdf':return path.read_bytes()
    if suffix in IMAGE_TYPES:return image_to_pdf(path)
    if suffix in ('.html','.htm'):return web_to_pdf(path.as_uri(),progress,local_file=True)
    if suffix not in OFFICE_TYPES|{'.txt'}:raise ConversionError('هذه الصيغة غير مدعومة. احفظها من برنامجها الأصلي كملف PDF ثم أضفها.')
    with tempfile.TemporaryDirectory(prefix='waraq-office-') as directory:
        folder=Path(directory);output=folder/'converted.pdf'
        if office_available(suffix):
            command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve().parents[1]/'run.py')]
            try:
                run_process(command+['--convert-office',str(path),str(output)],folder,progress)
            except ConversionError as exc:
                error=output.with_suffix('.error.txt')
                if error.exists():raise ConversionError(error.read_text(encoding='utf-8')) from exc
                raise
        else:
            libreoffice=find_libreoffice()
            if not libreoffice:raise ConversionError('تحويل ملفات Office يحتاج Microsoft Office المناسب أو LibreOffice مثبتًا. يمكنك أيضًا استخدام «طباعة إلى PDF» في البرنامج الأصلي.')
            # A separate profile prevents attachment to the user's open LO session.
            source=folder/('input'+suffix);shutil.copyfile(path,source)
            run_process([str(libreoffice),f'-env:UserInstallation={(folder/"profile").as_uri()}','--headless','--norestore','--convert-to','pdf','--outdir',str(folder),str(source)],folder,progress)
            output=folder/'input.pdf'
        return _read_pdf(output)


def office_worker(source: str, destination: str) -> int:
    """Run in a separate process; never attach to the user's Office document."""
    app=document=None
    try:
        import pythoncom
        from win32com.client import DispatchEx
        pythoncom.CoInitialize()
        extension=Path(source).suffix.lower()
        if extension in {'.doc','.docx','.rtf','.txt'}:
            app=DispatchEx('Word.Application');app.Visible=False;app.DisplayAlerts=0;app.AutomationSecurity=3
            document=app.Documents.Open(source,ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False,Visible=False)
            document.ExportAsFixedFormat(destination,17,OpenAfterExport=False)
            document.Close(False);document=None
        elif extension in {'.xls','.xlsx'}:
            app=DispatchEx('Excel.Application');app.Visible=False;app.DisplayAlerts=False;app.AutomationSecurity=3;app.AskToUpdateLinks=False
            document=app.Workbooks.Open(source,UpdateLinks=0,ReadOnly=True,AddToMru=False)
            document.ExportAsFixedFormat(0,destination)
            document.Close(False);document=None
        elif extension in {'.ppt','.pptx'}:
            app=DispatchEx('PowerPoint.Application');app.AutomationSecurity=3
            document=app.Presentations.Open(source,ReadOnly=True,Untitled=False,WithWindow=False)
            document.SaveAs(destination,32)
            document.Close();document=None
        else:raise ConversionError('صيغة Office غير مدعومة بواسطة هذا المحرك.')
        return 0
    except Exception as exc:
        Path(destination).with_suffix('.error.txt').write_text(f'تعذر تحويل المستند عبر Microsoft Office: {exc}',encoding='utf-8')
        return 1
    finally:
        if document is not None:
            try:document.Close()
            except Exception:pass
        if app is not None:
            try:app.Quit()
            except Exception:pass
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:pass
