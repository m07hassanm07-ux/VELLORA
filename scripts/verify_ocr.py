"""Real Arabic/English OCR on synthetic scans; writes no private content."""
from io import BytesIO
from pathlib import Path
import os, site, sys, json
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root/'.deps')]
site.addsitedir(str(root/'.deps')); os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter, PdfReader
import pypdfium2 as pdfium
from waraq.rendering import ensure_font_support, render_image
from waraq.editing import prepare_page, edit_page
from waraq.ocr import run_ocr, find_tesseract, engine_languages
from waraq.textlayout import extract_text, find_matches
app = QApplication([]); ensure_font_support()
out = root/'tmp'/'ocr-qa'; out.mkdir(parents=True, exist_ok=True)
writer = PdfWriter(); writer.add_blank_page(595,842); stream = BytesIO(); writer.write(stream)
data = prepare_page(stream.getvalue())
data = edit_page(data,text='WARAQ OCR TEST 12345',rect=(35,100,525,70),size=30)
data = edit_page(data,text='مرحبا بكم في تجربة قراءة النص العربي',rect=(35,230,525,120),size=30)
with pdfium.PdfDocument(data) as pdf:
    page = pdf[0]; bitmap = page.render(scale=3)
    try:
        scan = BytesIO(); bitmap.to_pil().convert('RGB').save(scan,format='PDF',resolution=216)
    finally: bitmap.close(); page.close()
scan = scan.getvalue(); (out/'scan.pdf').write_bytes(scan)
assert not PdfReader(BytesIO(scan)).pages[0].extract_text().strip()
result, report = run_ocr(scan, language='ara+eng')
(out/'searchable.pdf').write_bytes(result)
text = extract_text(result)
print(text.encode('unicode_escape').decode('ascii'))
assert 'WARAQ' in text and '12345' in text
assert any(word in text for word in ('العربي','قراءة','مرحبا'))
assert find_matches(result,'WARAQ')
with pdfium.PdfDocument(scan) as before, pdfium.PdfDocument(result) as after:
    a,b=render_image(before,0,.5),render_image(after,0,.5)
    assert a.size()==b.size()
    difference=sum(a.pixel(x,y)!=b.pixel(x,y) for y in range(a.height()) for x in range(a.width()))
    assert difference==0,difference
    b.save(str(out/'recognized.png'))
report.update({'engine_languages':sorted(engine_languages(find_tesseract())), 'english_search':True,
    'arabic_extracted':True, 'visual_pixels_unchanged':True})
(root/'docs'/'ocr-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Bilingual OCR integration passed.')
