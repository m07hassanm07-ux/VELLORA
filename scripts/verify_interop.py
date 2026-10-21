"""Synthetic integration samples for Office conversion and independent PDF engines."""
from pathlib import Path
from io import BytesIO
import json,os,site,subprocess,sys,time,zipfile
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'.deps')];site.addsitedir(str(root/'.deps'))
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
import pypdfium2 as pdfium
from waraq.core import Document,Overlay
from waraq.rendering import text_overlay,ensure_font_support,render_image
from waraq.conversion import convert_file,web_to_pdf,office_available,find_browser

app=QApplication([]);ensure_font_support()
folder=root/'tmp'/'interop';folder.mkdir(parents=True,exist_ok=True)
report={}
def inspect(path):
    reader=PdfReader(path)
    with pdfium.PdfDocument(str(path)) as doc:
        image=render_image(doc,0,0.65);image.save(str(path.with_suffix('.png')))
        if image.isNull():raise RuntimeError('Empty rendered page')
    return {'pages':len(reader.pages),'bytes':path.stat().st_size,'text':(reader.pages[0].extract_text() or '')[:140]}

document=Document()
for index in range(3):document.import_pdf(root/'examples'/'welcome.pdf')
document.rotate([3],90)
document.add_overlay(list(range(len(document.pages))),Overlay('',numbering=True))
merged=folder/'compatibility.pdf';document.save(merged,overlay_renderer=text_overlay)
report['merged_three_documents']=inspect(merged)
assert report['merged_three_documents']['pages']==9

html=folder/'web-sample.html'
html.write_text('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font:26px Segoe UI;padding:50px;color:#173d4c}h1{color:#157b67}</style><h1>اختبار ورّاق PDF</h1><p>WARAQ WEB CONVERSION TEST</p><p>ملفات PDF مستقلة وقابلة للتبادل.</p></html>',encoding='utf-8')
try:
    path=folder/'from-web.pdf';path.write_bytes(web_to_pdf(html.as_uri(),local_file=True))
    report['web_conversion']=inspect(path)
    assert 'WARAQ' in PdfReader(path).pages[0].extract_text()
except Exception as exc:report['web_conversion']={'error':str(exc)}

word=folder/'sample.docx'
with zipfile.ZipFile(word,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>WARAQ WORD CONVERSION TEST</w:t></w:r></w:p><w:p><w:r><w:t>اختبار تحويل مستند عربي مستقل.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
excel=folder/'sample.xlsx'
with zipfile.ZipFile(excel,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Waraq" sheetId="1" r:id="rId1"/></sheets></workbook>')
    z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="1" max="1" width="55" customWidth="1"/></cols><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>WARAQ EXCEL CONVERSION TEST</t></is></c></row><row r="2"><c r="A2"><v>12345</v></c></row></sheetData></worksheet>')
for source in [word,excel]:
    try:
        deadline=time.monotonic()+55
        output=folder/(source.stem+'-'+source.suffix[1:]+'.pdf')
        output.write_bytes(convert_file(source,lambda:time.monotonic()<deadline))
        report[source.suffix[1:]+'_conversion']=inspect(output)
        assert 'WARAQ' in PdfReader(output).pages[0].extract_text()
    except Exception as exc:report[source.suffix[1:]+'_conversion']={'error':str(exc)}

poppler=Path(r'C:\Users\Eng-Mohamed Hasan\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdfinfo.exe')
if poppler.is_file():
    result=subprocess.run([str(poppler),str(merged)],capture_output=True,text=True,timeout=30)
    report['poppler']={'returncode':result.returncode,'summary':[line for line in result.stdout.splitlines() if line.startswith(('Pages:','PDF version:','Page size:','Encrypted:'))]}
(root/'docs'/'compatibility-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
