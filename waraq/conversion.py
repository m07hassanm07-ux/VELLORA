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
import unicodedata
from urllib.parse import urlparse

from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader, PdfWriter

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


def office_page_layouts(data: bytes) -> list[dict]:
    """Extract positioned, styled top-level objects for editable Office output."""
    from .editing import inspect_page
    from .textlayout import character_map, normal_text, union_rect
    reader=PdfReader(BytesIO(data));layouts=[]
    for page_index,page in enumerate(reader.pages):
        writer=PdfWriter();writer.add_page(page);stream=BytesIO();writer.write(stream);writer.close()
        width,height,entries=inspect_page(stream.getvalue())
        converted=[
            {'kind':entry.kind,'text':entry.text,'rect':entry.rect,'size':entry.size,'family':entry.family,
             'bold':entry.bold,'color':entry.color,'alignment':entry.alignment}
            for entry in entries]
        original_text=[entry for entry in converted if entry['kind']=='text' and entry['text'].strip()]
        converted=[entry for entry in converted if entry['kind']!='text']
        _,_,glyphs=character_map(data,page_index);visible=[glyph for glyph in glyphs if glyph.text and not glyph.text.isspace()];lines=[]
        for glyph in sorted(visible,key=lambda item:(item.rect[1]+item.rect[3]/2,item.rect[0])):
            center=glyph.rect[1]+glyph.rect[3]/2;matches=[line for line in lines if abs(line['center']-center)<=max(2,glyph.rect[3]*.45)]
            if matches:line=min(matches,key=lambda item:abs(item['center']-center));line['glyphs'].append(glyph)
            else:lines.append({'center':center,'glyphs':[glyph]})
        for line in lines:
            visual=sorted(line['glyphs'],key=lambda glyph:glyph.rect[0]);heights=sorted(glyph.rect[3] for glyph in visual);threshold=max(10,heights[len(heights)//2]*1.25)
            runs=[];run=[]
            for glyph in visual:
                if run and glyph.rect[0]-(run[-1].rect[0]+run[-1].rect[2])>threshold:runs.append(run);run=[]
                run.append(glyph)
            if run:runs.append(run)
            for run in runs:
                selected=sorted(run,key=lambda glyph:glyph.index);pieces=[]
                for position,glyph in enumerate(selected):
                    if position:
                        between=glyphs[selected[position-1].index+1:glyph.index]
                        if any(item.text.isspace() for item in between):pieces.append(' ')
                    pieces.append(glyph.text)
                text=normal_text(''.join(pieces));rect=union_rect([glyph.rect for glyph in selected]);size=max(4,sorted(glyph.rect[3] for glyph in selected)[len(selected)//2]*.75)
                def overlap(entry):
                    ex,ey,ew,eh=entry['rect'];return max(0,min(rect[0]+rect[2],ex+ew)-max(rect[0],ex))*max(0,min(rect[1]+rect[3],ey+eh)-max(rect[1],ey))
                sample=max(original_text,key=overlap) if original_text else None
                rtl=sum(unicodedata.bidirectional(char) in ('AL','R') for char in text)>sum(char.isascii() and char.isalpha() for char in text)
                converted.append({'kind':'text','text':text,'rect':rect,'size':sample['size'] if sample else size,
                    'family':sample['family'] if sample else 'Segoe UI','bold':sample['bold'] if sample else False,
                    'color':sample['color'] if sample else '#172a32','alignment':sample['alignment'] if sample else ('right' if rtl else 'left')})
        layouts.append({'width':width,'height':height,'entries':converted})
    return layouts


def spatial_table(entries) -> list[list[str]]:
    """Convert positioned text objects into stable spreadsheet rows/columns."""
    def value(entry,name):return entry[name] if isinstance(entry,dict) else getattr(entry,name)
    texts=[entry for entry in entries if value(entry,'kind')=='text' and value(entry,'text').strip()]
    if not texts:return []
    lines=[]
    for entry in sorted(texts,key=lambda item:(value(item,'rect')[1]+value(item,'rect')[3]/2,value(item,'rect')[0])):
        rect=value(entry,'rect');center=rect[1]+rect[3]/2;tolerance=max(3,float(value(entry,'size'))*.65)
        matches=[line for line in lines if abs(line['center']-center)<=tolerance]
        if matches:
            line=min(matches,key=lambda item:abs(item['center']-center));line['items'].append(entry)
            line['center']=sum(value(item,'rect')[1]+value(item,'rect')[3]/2 for item in line['items'])/len(line['items'])
        else:lines.append({'center':center,'items':[entry]})
    anchors=[]
    for line in lines:
        for entry in sorted(line['items'],key=lambda item:value(item,'rect')[0]):
            x=value(entry,'rect')[0];tolerance=max(12,float(value(entry,'size'))*2)
            matches=[(index,anchor) for index,anchor in enumerate(anchors) if abs(anchor-x)<=tolerance]
            if matches:
                index,_=min(matches,key=lambda pair:abs(pair[1]-x));anchors[index]=(anchors[index]+x)/2
            else:anchors.append(x)
    anchors.sort();rows=[]
    for line in sorted(lines,key=lambda item:item['center']):
        cells=['']*len(anchors)
        for entry in sorted(line['items'],key=lambda item:value(item,'rect')[0]):
            rect=value(entry,'rect');column=min(range(len(anchors)),key=lambda index:abs(anchors[index]-rect[0]))
            text=value(entry,'text').strip();cells[column]=(cells[column]+' '+text).strip()
        while cells and not cells[-1]:cells.pop()
        rows.append(cells or [''])
    return rows


def sample_box_background(image: Image.Image, rect, page_size) -> tuple[tuple[int,int,int],float]:
    """Estimate a text box background and variation for editable PPT overlays."""
    x,y,w,h=rect;page_w,page_h=page_size
    left=max(0,round(x/page_w*image.width));top=max(0,round(y/page_h*image.height))
    right=min(image.width,max(left+1,round((x+w)/page_w*image.width)));bottom=min(image.height,max(top+1,round((y+h)/page_h*image.height)))
    pad=max(2,round(min(image.width/page_w,image.height/page_h)*3));outer=(max(0,left-pad),max(0,top-pad),min(image.width,right+pad),min(image.height,bottom+pad))
    crop=image.convert('RGB').crop(outer);inner=(left-outer[0],top-outer[1],right-outer[0],bottom-outer[1]);step=max(1,max(crop.size)//80)
    pixels=[crop.getpixel((px,py)) for py in range(0,crop.height,step) for px in range(0,crop.width,step)
            if px<inner[0] or px>=inner[2] or py<inner[1] or py>=inner[3]]
    if not pixels:pixels=list(crop.resize((12,12)).get_flattened_data())
    channels=tuple(sorted(pixel[channel] for pixel in pixels)[len(pixels)//2] for channel in range(3))
    variation=sum(abs(pixel[channel]-channels[channel]) for pixel in pixels for channel in range(3))/(len(pixels)*3)
    return channels,variation


def office_rgb(color: str | tuple[int,int,int]) -> int:
    """Return the integer ordering expected by Office COM ForeColor.RGB."""
    if isinstance(color,str):
        value=color.lstrip('#');color=tuple(int(value[index:index+2],16) for index in (0,2,4))
    red,green,blue=color
    return red|(green<<8)|(blue<<16)


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
            document=app.Workbooks.Add();pdf_data=Path(source).read_bytes();layouts=office_page_layouts(pdf_data)
            from .professional import export_page_images
            with tempfile.TemporaryDirectory(prefix='vellora-xlsx-') as directory:
                images=export_page_images(pdf_data,directory,dpi=110,prefix='page')
                for page_index,layout in enumerate(layouts):
                    sheet=document.Worksheets(1) if page_index==0 else document.Worksheets.Add(After=document.Worksheets(document.Worksheets.Count))
                    sheet.Name=('صفحة '+str(page_index+1))[:31];rows=spatial_table(layout['entries']);max_columns=max((len(row) for row in rows),default=1)
                    for row_index,row in enumerate(rows,1):
                        for column_index,value in enumerate(row,1):
                            cell=sheet.Cells(row_index,column_index);cell.NumberFormat='@';cell.Value=value
                    sheet.Cells.WrapText=True;sheet.Cells.VerticalAlignment=-4160;sheet.Columns.AutoFit();sheet.Rows.AutoFit()
                    for column in range(1,max_columns+1):
                        if sheet.Columns(column).ColumnWidth>60:sheet.Columns(column).ColumnWidth=60
                    joined=' '.join(value for row in rows for value in row)
                    if sum('\u0600'<=char<='\u06ff' for char in joined)>sum(char.isascii() and char.isalpha() for char in joined):
                        sheet.DisplayRightToLeft=True
                    if page_index<len(images):
                        with Image.open(images[page_index]) as picture:
                            preview_width=360;preview_height=preview_width*picture.height/picture.width
                        anchor=sheet.Cells(1,max_columns+2)
                        sheet.Shapes.AddPicture(str(images[page_index]),False,True,float(anchor.Left),float(anchor.Top),preview_width,preview_height)
            document.SaveAs(destination,FileFormat=51);document.Close(False);document=None
        elif kind=='pptx':
            from .professional import export_page_images
            pdf_data=Path(source).read_bytes();layouts=office_page_layouts(pdf_data)
            app=DispatchEx('PowerPoint.Application');document=app.Presentations.Add(WithWindow=False)
            if layouts:
                document.PageSetup.SlideWidth=720;document.PageSetup.SlideHeight=720*layouts[0]['height']/layouts[0]['width']
            with tempfile.TemporaryDirectory(prefix='waraq-ppt-') as directory:
                images=export_page_images(pdf_data,directory,dpi=144,prefix='slide')
                slide_width=float(document.PageSetup.SlideWidth);slide_height=float(document.PageSetup.SlideHeight)
                for page_index,image in enumerate(images):
                    slide=document.Slides.Add(document.Slides.Count+1,12)
                    with Image.open(image) as opened:
                        picture=opened.convert('RGB');pixel_width,pixel_height=picture.size
                        scale=min(slide_width/picture.width,slide_height/picture.height)
                        width,height=picture.width*scale,picture.height*scale
                        image_left,image_top=(slide_width-width)/2,(slide_height-height)/2
                        slide.Shapes.AddPicture(str(image),False,True,image_left,image_top,width,height)
                        if page_index<len(layouts):
                            layout=layouts[page_index];page_w,page_h=layout['width'],layout['height']
                            for entry in [item for item in layout['entries'] if item['kind']=='text' and item['text'].strip()][:250]:
                                background,variation=sample_box_background(picture,entry['rect'],(page_w,page_h))
                                if variation>28:continue
                                x,y,w,h=entry['rect'];left=image_left+x/page_w*width;top=image_top+y/page_h*height
                                box_width=max(8,w/page_w*width);box_height=max(6,h/page_h*height*1.25)
                                shape=slide.Shapes.AddTextbox(1,left-.5,top-.5,box_width+1,box_height+1)
                                shape.Fill.Visible=-1;shape.Fill.Solid();shape.Fill.ForeColor.RGB=office_rgb(background);shape.Line.Visible=0
                                frame=shape.TextFrame;frame.MarginLeft=0;frame.MarginRight=0;frame.MarginTop=0;frame.MarginBottom=0;frame.WordWrap=-1
                                text=frame.TextRange;text.Text=entry['text'];text.Font.Name=entry['family'];text.Font.Size=max(4,entry['size']*width/page_w)
                                text.Font.Bold=-1 if entry['bold'] else 0;text.Font.Color.RGB=office_rgb(entry['color'])
                                text.ParagraphFormat.Alignment={'left':1,'center':2,'right':3}.get(entry['alignment'],1)
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
