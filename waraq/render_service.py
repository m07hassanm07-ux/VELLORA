"""A persistent, isolated PDF renderer with encrypted temporary IPC."""
from dataclasses import asdict
from pathlib import Path
import hashlib,json,os,tempfile,time,uuid
from PySide6.QtCore import QObject,QProcess,QTimer,Signal
from .core import atomic_write
from .projects import protect_local,unprotect_local
from .tasks import TaskThread,worker_command


def pack(meta,data=b''):
    encoded=json.dumps(meta,ensure_ascii=False).encode('utf-8')
    return protect_local(len(encoded).to_bytes(4,'little')+encoded+data)


def unpack(data):
    data=unprotect_local(data);size=int.from_bytes(data[:4],'little')
    if size>len(data)-4:raise ValueError('رسالة عرض غير صالحة.')
    return json.loads(data[4:4+size]),data[4+size:]


class ProcessRenderer(QObject):
    def __init__(self,parent=None):
        super().__init__(parent);self.temp=None;self.process=None;self.pending={};self.ready=set();self.writing={};self.threads=set()
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.poll)

    def start(self):
        if self.process:return
        self.temp=tempfile.TemporaryDirectory(prefix='waraq-render-');self.folder=Path(self.temp.name)
        self.process=QProcess(self);command=worker_command('--render-server',self.folder)
        self.process.start(command[0],command[1:]);self.timer.start()

    def submit(self,source,reference,scale,callback,*,reading=False,index=0,total=1):
        self.start();kind='view' if reading else 'thumb'
        if reading:
            for token,entry in list(self.pending.items()):
                if entry['kind']=='view':
                    self.pending.pop(token);(self.folder/('request-'+token+'.bin')).unlink(missing_ok=True)
        token=uuid.uuid4().hex;name=hashlib.sha256(reference.source.encode()).hexdigest()+'.source'
        request={'source':name,'reference':asdict(reference),'scale':scale,'reading':reading,'index':index,'total':total,'token':token,'kind':kind,'created':time.time_ns()}
        self.pending[token]={'kind':kind,'callback':callback,'request':request}
        def dispatch():
            if token in self.pending:atomic_write(self.folder/('request-'+token+'.bin'),pack(request))
        if name in self.ready:dispatch()
        elif name in self.writing:self.writing[name].append(dispatch)
        else:
            self.writing[name]=[dispatch];folder=self.folder;data=source.data;password=source.password
            def write(report,cancelled):
                atomic_write(folder/name,pack({'password':password,'name':source.name},data))
            thread=TaskThread(write,self);self.threads.add(thread)
            def done():
                if self.temp and self.folder==folder:
                    self.ready.add(name)
                    for action in self.writing.pop(name,[]):action()
                self.threads.discard(thread);thread.deleteLater()
            def failed(message):
                for key,entry in list(self.pending.items()):
                    if entry['request']['source']==name:self.pending.pop(key);entry['callback']({'error':message},b'')
            thread.failed.connect(failed);thread.finished.connect(done);thread.start()
        return token

    def poll(self):
        if not self.temp:return
        for path in self.folder.glob('result-*.bin'):
            token=path.stem.removeprefix('result-');entry=self.pending.pop(token,None)
            try:
                meta,data=unpack(path.read_bytes())
                if entry:entry['callback'](meta,data)
            except Exception as exc:
                if entry:entry['callback']({'error':str(exc)},b'')
            finally:path.unlink(missing_ok=True)
        if self.process.state()==QProcess.ProcessState.NotRunning and self.pending:
            pending=list(self.pending.values());self.pending.clear()
            for entry in pending:entry['callback']({'error':'توقفت خدمة عرض PDF. أعد فتح المستند.'},b'')

    def close(self):
        self.timer.stop();self.pending.clear()
        for thread in list(self.threads):thread.wait()
        if self.process:
            (self.folder/'stop').touch();self.process.waitForFinished(1500)
            if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.kill();self.process.waitForFinished(1500)
            self.process.deleteLater();self.process=None
        if self.temp:self.temp.cleanup();self.temp=None
        self.ready.clear();self.writing.clear();self.threads.clear()


def render_server(directory):
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QByteArray,QBuffer,QIODevice
    from .rendering import ensure_font_support,render_image,text_overlay
    from .core import Document,PageRef,Overlay,Source
    from .textlayout import character_map,display_rect
    from .review import list_review
    from pypdf import PdfReader
    from io import BytesIO
    import pypdfium2 as pdfium
    app=QApplication.instance() or QApplication([]);ensure_font_support()
    folder=Path(directory);cache={}
    try:
        while not (folder/'stop').exists():
            jobs=[]
            for path in folder.glob('request-*.bin'):
                try:request,_=unpack(path.read_bytes());jobs.append((request,path))
                except (OSError,ValueError):continue
            if not jobs:time.sleep(.025);continue
            request,path=min(jobs,key=lambda item:(item[0]['kind']!='view',-item[0]['created'] if item[0]['kind']=='view' else item[0]['created']))
            path.unlink(missing_ok=True);token=request['token'];png=b''
            try:
                source_name=request['source']
                if not source_name.endswith('.source') or len(source_name)!=71 or '/' in source_name or '\\' in source_name:raise ValueError('مصدر عرض غير صالح.')
                if source_name not in cache:
                    meta,data=unpack((folder/source_name).read_bytes());pdf=pdfium.PdfDocument(data,password=meta['password'] or None)
                    cache[source_name]=(meta,data,pdf)
                    if len(cache)>3:
                        key=next(k for k in cache if k!=source_name);cache.pop(key)[2].close()
                meta,data,pdf=cache[source_name];ref=request['reference'];extra=ref['rotation']
                temporary=None;page_index=ref['index']
                if ref['overlays']:
                    model=Document();reader=PdfReader(BytesIO(data))
                    if reader.is_encrypted:reader.decrypt(meta['password'])
                    model.sources['page']=Source(meta['name'],data,reader,meta['password'])
                    model.pages=[PageRef('page',page_index,extra,tuple(Overlay(**o) for o in ref['overlays']))]
                    view_data=model.build_bytes(overlay_renderer=text_overlay,preview_context=(request['index']+1,request['total']))
                    temporary=pdfium.PdfDocument(view_data);active=temporary;active_index=0;extra=0
                else:active=pdf;active_index=page_index;view_data=data
                try:
                    page=active[active_index]
                    try:width,height=page.get_size()
                    finally:page.close()
                    image=render_image(active,active_index,request['scale'],extra)
                    output=QByteArray();buffer=QBuffer(output);buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG');buffer.close();png=bytes(output)
                    glyphs=[]
                    annotations=[]
                    if request['reading']:
                        glyphs=[asdict(g) for g in character_map(view_data,active_index)[2]]
                        annotations=list_review(view_data,active_index,meta['password'] if active is pdf else '')
                        page=active[active_index]
                        try:
                            for annotation in annotations:annotation['rect']=display_rect(page,annotation['rect'])
                        finally:page.close()
                        if extra:
                            for glyph in glyphs+annotations:
                                x,y,w,h=glyph['rect']
                                glyph['rect']= {90:(height-y-h,x,h,w),180:(width-x-w,height-y-h,w,h),270:(y,width-x-w,h,w)}[extra]
                    result={'width':height if extra in (90,270) else width,'height':width if extra in (90,270) else height,'scale':request['scale'],'glyphs':glyphs,'annotations':annotations}
                finally:
                    if temporary:temporary.close()
            except Exception as exc:result={'error':str(exc)}
            atomic_write(folder/('result-'+token+'.bin'),pack(result,png))
    finally:
        for _,_,pdf in cache.values():pdf.close()
    return 0
