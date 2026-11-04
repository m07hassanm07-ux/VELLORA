"""Private child-process entry point; never accepts source code from requests."""
from pathlib import Path
from io import BytesIO
import json,os
from .projects import decode_snapshot,restore,protect_local,unprotect_local
from .core import atomic_write,PasswordRequired
from .ocr import JobCancelled,run_ocr


def run_job(directory):
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from .rendering import ensure_font_support,text_overlay
    app=QApplication.instance() or QApplication([]);ensure_font_support()
    folder=Path(directory);result={}
    def progress(done,total,message):
        if (folder/'cancel').exists():raise JobCancelled()
        atomic_write(folder/'progress.json',json.dumps({'done':done,'total':total,'message':message}).encode('utf-8'))
        return True
    try:
        request=json.loads(unprotect_local((folder/'request.bin').read_bytes()))
        kind=request['kind'];params=request['params'];progress(0,0,'جاري قراءة المستند…')
        state=decode_snapshot((folder/'state.bin').read_bytes());model=restore(state)
        if kind=='assemble':
            data=model.build_bytes(indexes=params.get('indexes'),password=params.get('password',''),
                owner_password=params.get('owner_password',''),permissions=params.get('permissions'),
                overlay_renderer=text_overlay,progress=progress,preview_context=params.get('preview_context'))
        elif kind=='search':
            from .textlayout import find_matches
            data=model.build_bytes(overlay_renderer=text_overlay,progress=progress)
            result['matches']=find_matches(data,params['query'],progress=progress);data=None
        elif kind=='ocr':
            data=model.build_bytes(overlay_renderer=text_overlay,progress=progress)
            data,result['report']=run_ocr(data,params.get('indexes'),params.get('language','ara+eng'),params.get('engine'),params.get('skip_text',True),progress,params.get('preprocess',True))
        elif kind=='import':
            from .conversion import convert_file
            path=Path(params['path']);password=params.get('password','')
            data=convert_file(path,lambda:progress(0,0,'جاري تحويل الملف…'))
            try:model.import_bytes(path.name,data,password)
            except PasswordRequired:
                result['needs_password']=True;data=None
        elif kind=='web':
            from .conversion import web_to_pdf
            data=web_to_pdf(params['url'],lambda:progress(0,0,'جاري تحويل صفحة الويب…'))
        elif kind=='review':
            from .review import apply_review
            data=model.build_bytes(overlay_renderer=text_overlay,progress=progress)
            data=apply_review(data,params['page'],params['action'],params.get('payload',{}))
        else:raise ValueError('نوع معالجة غير معروف.')
        progress(1,1,'اكتملت المعالجة')
        if data is not None:(folder/'output.bin').write_bytes(protect_local(data))
    except JobCancelled:result={'cancelled':True}
    except Exception as exc:result={'error':str(exc)}
    atomic_write(folder/'result.bin',protect_local(json.dumps(result,ensure_ascii=False).encode('utf-8')))
    return 0 if not result.get('error') else 1
