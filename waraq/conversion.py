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
import re
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


def office_export_available(kind: str) -> bool:
    if os.name != 'nt':return False
    import winreg
    program={'docx':'Word.Application','xlsx':'Excel.Application','pptx':'PowerPoint.Application'}.get(kind)
    if not program:return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,program+'\\CLSID'):return True
    except OSError:return False


def table_rows(text: str) -> list[list[str]]:
    """Conservative plain-text rows used by the local Excel adapter."""
    rows=[]
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        cells=[cell.strip() for cell in re.split(r'\t+| {2,}',line) if cell.strip()]
        rows.append(cells or [line])
    return rows


def export_pdf_office(data: bytes, destination: str | Path, kind: str,
                      progress: Callable[[],bool] | None=None) -> Path:
    """Export through an installed Office application in an isolated process."""
    kind=kind.lower();destination=Path(destination).resolve()
    suffix={"docx":".docx","xlsx":".xlsx","pptx":".pptx"}.get(kind)
    if suffix is None:raise ConversionError('صيغة تصدير Office غير مدعومة.')
    if not office_export_available(kind):raise ConversionError('يتطلب هذا التصدير تثبيت تطبيق Microsoft Office المناسب على الجهاز.')
    if destination.suffix.lower()!=suffix:destination=destination.with_suffix(suffix)
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.waraq-export-',suffix=suffix,dir=destination.parent);os.close(fd);os.unlink(temporary)
    temporary=Path(temporary)
    try:
        with tempfile.TemporaryDirectory(prefix='waraq-office-export-') as directory:
            folder=Path(directory);source=folder/'input.pdf';source.write_bytes(data);error=folder/'error.txt'
            command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve().parents[1]/'run.py')]
            try:run_process(command+['--export-office',str(source),str(temporary),kind,str(error)],folder,progress,timeout=300)
            except ConversionError as exc:
                if error.is_file():raise ConversionError(error.read_text(encoding='utf-8')) from exc
                raise
        if not temporary.is_file() or temporary.stat().st_size<100:
            raise ConversionError('لم يُنشئ Office ملف التصدير المتوقع.')
        os.replace(temporary,destination);return destination
    finally:
        if temporary.exists():temporary.unlink()


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
    return image_bytes_to_pdf(path.read_bytes())


def image_bytes_to_pdf(data: bytes) -> bytes:
    frames=[]
    with Image.open(BytesIO(data)) as image:
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


def acquire_wia_image() -> bytes:
    """Acquire one image using Windows' standard WIA scanner dialog."""
    if os.name!='nt':raise ConversionError('المسح المباشر متاح على Windows فقط.')
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        dialog=Dispatch('WIA.CommonDialog')
        # ScannerDeviceType=1, UnspecifiedIntent=0, JPEG format. Windows owns
        # the device-selection/progress UI and returns None when cancelled.
        image=dialog.ShowAcquireImage(1,0,0,'{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}',True,True,False)
        if image is None:raise ConversionCancelled('أُلغي المسح الضوئي.')
        value=image.FileData.BinaryData
        try:data=bytes(value)
        except ValueError:data=bytes((int(item)&255) for item in value)
        if len(data)<32:raise ConversionError('لم يُرجع الماسح صورة صالحة.')
        return data
    except ConversionCancelled:raise
    except Exception as exc:raise ConversionError(f'تعذر الاتصال بالماسح عبر WIA: {exc}') from exc
    finally:
        try:
            import pythoncom;pythoncom.CoUninitialize()
        except Exception:pass


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


def office_export_worker(source: str, destination: str, kind: str, error_path: str) -> int:
    """Private COM worker for PDF-to-Office export; never attaches to open apps."""
    app=document=None
    try:
        import pythoncom
        from win32com.client import DispatchEx
        pythoncom.CoInitialize();source=str(Path(source).resolve());destination=str(Path(destination).resolve())
        if kind=='docx':
            app=DispatchEx('Word.Application');app.Visible=False;app.DisplayAlerts=0;app.AutomationSecurity=3
            document=app.Documents.Open(source,ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False,Visible=False)
            document.SaveAs2(destination,FileFormat=16);document.Close(False);document=None
        elif kind=='xlsx':
            app=DispatchEx('Excel.Application');app.Visible=False;app.DisplayAlerts=False;app.AutomationSecurity=3
            document=app.Workbooks.Add();reader=PdfReader(source)
            for page_index,page in enumerate(reader.pages):
                sheet=document.Worksheets(1) if page_index==0 else document.Worksheets.Add(After=document.Worksheets(document.Worksheets.Count))
                sheet.Name=('صفحة '+str(page_index+1))[:31]
                for row_index,row in enumerate(table_rows(page.extract_text() or ''),1):
                    for column_index,value in enumerate(row,1):sheet.Cells(row_index,column_index).Value=value
                sheet.Columns.AutoFit()
            document.SaveAs(destination,FileFormat=51);document.Close(False);document=None
        elif kind=='pptx':
            from .professional import export_page_images
            app=DispatchEx('PowerPoint.Application');document=app.Presentations.Add(WithWindow=False)
            with tempfile.TemporaryDirectory(prefix='waraq-ppt-') as directory:
                images=export_page_images(Path(source).read_bytes(),directory,dpi=144,prefix='slide')
                slide_width=float(document.PageSetup.SlideWidth);slide_height=float(document.PageSetup.SlideHeight)
                for image in images:
                    slide=document.Slides.Add(document.Slides.Count+1,12)
                    slide.Shapes.AddPicture(str(image),False,True,0,0,slide_width,slide_height)
            document.SaveAs(destination,24);document.Close();document=None
        else:raise ConversionError('صيغة تصدير Office غير مدعومة.')
        return 0
    except Exception as exc:
        Path(error_path).write_text(f'تعذر التصدير إلى Office: {exc}',encoding='utf-8');return 1
    finally:
        if document is not None:
            try:document.Close(False)
            except Exception:pass
        if app is not None:
            try:app.Quit()
            except Exception:pass
        try:
            import pythoncom;pythoncom.CoUninitialize()
        except Exception:pass
