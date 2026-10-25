"""Explicit isolated smoke check for a built executable; no physical print job."""
from io import BytesIO
from pathlib import Path
import json,os


def self_test(destination: str) -> int:
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPrintSupport import QPrinter
    from pypdf import PdfReader,PdfWriter
    import pypdfium2 as pdfium
    from . import __version__
    from .core import Document,Overlay
    from .rendering import text_overlay,render_image,ensure_font_support
    from .printing import paint_pdf
    from .editing import prepare_page, inspect_page, edit_page
    from .editor_dialog import PageEditorDialog
    from .projects import snapshot, encode_snapshot, decode_snapshot, restore
    from .tasks import process_job
    from .textlayout import find_matches
    from .review import apply_review, list_review
    folder=Path(destination);folder.mkdir(parents=True,exist_ok=True)
    result={'version':__version__,'passed':False}
    try:
        app=QApplication.instance() or QApplication([]);ensure_font_support()
        writer=PdfWriter();writer.add_blank_page(595,842);writer.add_blank_page(842,595)
        stream=BytesIO();writer.write(stream)
        model=Document();model.import_bytes('synthetic.pdf',stream.getvalue())
        model.add_overlay([0,1],Overlay('WARAQ PDF — اختبار الطباعة','center',24))
        data=model.build_bytes(overlay_renderer=text_overlay)
        (folder/'assembled.pdf').write_bytes(data)
        assert len(PdfReader(BytesIO(data)).pages)==2
        single=PdfWriter();single.add_blank_page(595,842);single_stream=BytesIO();single.write(single_stream)
        editable=edit_page(prepare_page(single_stream.getvalue()),text='ORIGINAL',rect=(40,100,400,50))
        selected=[entry.index for entry in inspect_page(editable)[2] if entry.kind=='text']
        edited=edit_page(editable,selected,text='EDITED',rect=(40,100,400,50))
        edited_text=PdfReader(BytesIO(edited)).pages[0].extract_text()
        assert 'ORIGINAL' not in edited_text and 'EDITED' in edited_text
        assert find_matches(edited, 'EDITED')
        dialog=PageEditorDialog(edited);assert dialog.entries;dialog.reject()
        (folder/'edited.pdf').write_bytes(edited)
        project=encode_snapshot(snapshot(model),password='diagnostic-project-password')
        restored=restore(decode_snapshot(project,'diagnostic-project-password'))
        assert restored.fingerprint()==model.fingerprint()
        reviewed=apply_review(edited,0,'note',{'point':(70,240),'text':'Diagnostic note'})
        assert any(item['text']=='Diagnostic note' for item in list_review(reviewed,0))
        assembled=process_job(snapshot(model,history=False),'assemble',
            {'indexes':[0,1],'password':None},lambda *_: True,lambda: False)['data']
        assert len(PdfReader(BytesIO(assembled)).pages)==2
        encrypted=model.build_bytes(password='diagnostic-only-password',overlay_renderer=text_overlay)
        check=PdfReader(BytesIO(encrypted));assert check.decrypt('diagnostic-only-password') and len(check.pages)==2
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setResolution(150)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(folder/'printed.pdf'))
        assert paint_pdf(printer,data,[0,1])==2
        assert len(PdfReader(folder/'printed.pdf').pages)==2
        with pdfium.PdfDocument(data) as pdf:
            image=render_image(pdf,0,0.5);assert not image.isNull();image.save(str(folder/'preview.png'))
        result.update({'passed':True,'merge_pages':2,'print_pages':2,'encrypted_roundtrip':True,
            'rendered':True,'text_replacement':True,'editor_dialog':True,'search':True,
            'project_roundtrip':True,'review_annotation':True,'worker_process':True})
    except Exception as exc:
        import traceback
        result['error']=str(exc) or repr(exc)
        result['traceback']=traceback.format_exc()
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1
