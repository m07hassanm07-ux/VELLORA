"""Explicit isolated smoke check for a built executable; no physical print job."""
from io import BytesIO
from datetime import datetime,timedelta,timezone
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
    from .templates import builtin_template, encode_template, decode_template
    from .signatures import sign_pkcs12,validate_signatures
    from .preflight import preflight_pdf
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
        inline=PageEditorDialog(edited,embedded=True);assert inline.embedded and inline.font.count()>0;inline.close()
        template_name,template_pdf=builtin_template('report')
        restored_name,restored_template=decode_template(encode_template(template_pdf,template_name))
        assert restored_name==template_name and len(PdfReader(BytesIO(restored_template)).pages)==1
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
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509.oid import NameOID
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Waraqa Packaged Test')]);now=datetime.now(timezone.utc)
        certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
        pfx=pkcs12.serialize_key_and_certificates(b'waraqa',key,certificate,None,serialization.BestAvailableEncryption(b'packaged-test'))
        pfx_path=folder/'test-certificate.pfx';pfx_path.write_bytes(pfx)
        signed=sign_pkcs12(data,pfx_path,'packaged-test',reason='Packaged self-test')
        signatures=validate_signatures(signed);assert len(signatures)==1 and signatures[0].intact and signatures[0].valid
        (folder/'signed.pdf').write_bytes(signed);pfx_path.unlink()
        assert preflight_pdf(data).pages==2
        result.update({'passed':True,'merge_pages':2,'print_pages':2,'encrypted_roundtrip':True,
            'rendered':True,'text_replacement':True,'editor_dialog':True,'search':True,
            'project_roundtrip':True,'review_annotation':True,'worker_process':True})
        result.update({'inline_editor':True,'business_templates':True,'system_fonts':True,
            'digital_signature':True,'preflight':True})
    except Exception as exc:
        import traceback
        result['error']=str(exc) or repr(exc)
        result['traceback']=traceback.format_exc()
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1
