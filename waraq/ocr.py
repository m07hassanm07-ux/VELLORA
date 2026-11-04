"""Local bilingual OCR. No cloud upload; the Tesseract engine is external."""
from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time

from pypdf import PdfReader, PdfWriter, Transformation
import pypdfium2 as pdfium

from .editing import prepare_page


class OcrError(ValueError): pass
class JobCancelled(Exception): pass


def find_tesseract(configured=None):
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    candidates = [configured, os.environ.get('WARAQ_TESSERACT'), shutil.which('tesseract'),
        root/'ocr'/'tesseract.exe', root/'.tools'/'tesseract-5.5.3'/'engine'/'tesseract.exe',
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'))/'Tesseract-OCR'/'tesseract.exe',
        Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'Programs'/'Tesseract-OCR'/'tesseract.exe']
    return next((Path(p).resolve() for p in candidates if p and Path(p).is_file()), None)


def find_tessdata():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    path=root/'ocr-data'/'tessdata' if getattr(sys,'frozen',False) else root/'assets'/'ocr'/'tessdata'
    return path if (path/'ara.traineddata').is_file() and (path/'eng.traineddata').is_file() else None


def engine_languages(engine):
    tessdata=find_tessdata();args=[str(engine)]+(['--tessdata-dir',str(tessdata)] if tessdata else [])+['--list-langs']
    result = subprocess.run(args, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode: raise OcrError('تعذر تشغيل محرك OCR. اختر ملف tesseract.exe الصحيح.')
    return set(line.strip() for line in result.stdout.splitlines()[1:] if line.strip())


def run_ocr(data, indexes=None, language='ara+eng', engine=None, skip_text=True, progress=None, preprocess=True):
    engine = find_tesseract(engine)
    if not engine:
        raise OcrError('ثبّت Tesseract OCR مع بيانات العربية ara والإنجليزية eng، أو اختر محركه من إعدادات OCR.')
    if language not in ('ara', 'eng', 'ara+eng'): raise OcrError('لغة OCR غير مدعومة.')
    missing = set(language.split('+'))-engine_languages(engine)
    if missing: raise OcrError('بيانات OCR غير مثبتة: '+', '.join(sorted(missing)))
    reader = PdfReader(BytesIO(data)); writer = PdfWriter()
    chosen = set(range(len(reader.pages)) if indexes is None else indexes)
    if any(i < 0 or i >= len(reader.pages) for i in chosen): raise OcrError('نطاق صفحات OCR غير صالح.')
    total = len(chosen); done = 0; recognized = []; skipped = []
    def tick(message):
        if progress and progress(done, total, message) is False: raise JobCancelled('تم إلغاء OCR؛ لم يتغير المستند.')
    with tempfile.TemporaryDirectory(prefix='waraq-ocr-') as directory:
        folder = Path(directory)
        for index, page in enumerate(reader.pages):
            if index not in chosen:
                writer.add_page(page); continue
            tick(f'جاري تجهيز الصفحة {index+1}…')
            single = PdfWriter(); single.add_page(page); stream = BytesIO(); single.write(stream)
            normalized = prepare_page(stream.getvalue())
            with pdfium.PdfDocument(normalized) as pdf:
                source = pdf[0]
                try:
                    tp = source.get_textpage()
                    try: existing = tp.get_text_range().strip()
                    finally: tp.close()
                    if skip_text and existing:
                        writer.add_page(page); skipped.append(index); done += 1; continue
                    width, height = source.get_size()
                    scale = min(300/72, (30_000_000/max(1, width*height))**.5)
                    bitmap = source.render(scale=scale)
                    try:
                        image=bitmap.to_pil().convert('L')
                        if preprocess:
                            from PIL import ImageEnhance,ImageFilter,ImageOps
                            image=ImageOps.autocontrast(image,cutoff=1).filter(ImageFilter.MedianFilter(3))
                            image=ImageEnhance.Contrast(image).enhance(1.25)
                        image.convert('RGB').save(folder/'scan.png',dpi=(scale*72,scale*72))
                    finally: bitmap.close()
                finally: source.close()
            args = [str(engine), str(folder/'scan.png'), str(folder/'result'), '-l', language,
                '--oem', '1', '--psm', '3', '--dpi', str(round(scale*72)),
                '-c', 'tessedit_create_pdf=1', '-c', 'textonly_pdf=1', '-c', 'tessedit_create_txt=1']
            tessdata=find_tessdata()
            if tessdata:args.extend(['--tessdata-dir',str(tessdata)])
            with (folder/'engine.log').open('wb') as log:
                process = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                deadline = time.monotonic()+240
                try:
                    while process.poll() is None:
                        tick(f'التعرف على النص في الصفحة {index+1}…')
                        if time.monotonic() > deadline: raise OcrError(f'تجاوز التعرف على الصفحة {index+1} المهلة. جرّب صفحة أبسط أو نطاقًا أصغر.')
                        time.sleep(.1)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=5)
                        except subprocess.TimeoutExpired: process.kill(); process.wait()
                if process.returncode: raise OcrError(f'فشل OCR في الصفحة {index+1}. تحقق من المحرك وبيانات اللغة.')
            layer_path = folder/'result.pdf'
            if not layer_path.is_file(): raise OcrError('لم يُنشئ المحرك طبقة PDF قابلة للبحث.')
            base = PdfReader(BytesIO(normalized)).pages[0]; layer = PdfReader(layer_path).pages[0]
            base.merge_transformed_page(layer, Transformation().scale(float(base.mediabox.width)/float(layer.mediabox.width),
                float(base.mediabox.height)/float(layer.mediabox.height)))
            writer.add_page(base)
            text_path = folder/'result.txt'
            recognized.append({'page': index, 'text': text_path.read_text(encoding='utf-8') if text_path.exists() else ''})
            done += 1; tick(f'اكتملت الصفحة {index+1}')
    writer.add_metadata(dict(reader.metadata or {})); writer.pdf_header = max(writer.pdf_header, '%PDF-1.7')
    output = BytesIO(); writer.write(output); writer.close()
    return output.getvalue(), {'recognized': recognized, 'skipped': skipped, 'language': language, 'preprocessed':preprocess}
