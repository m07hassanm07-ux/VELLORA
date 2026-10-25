"""Versioned project archives and per-user encrypted crash recovery.

PDF passwords exist only inside an encrypted project/recovery payload. Never
store pickles or execute project content. Sources are embedded, not path-linked.
"""
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import ctypes
import json
import os
import uuid
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pypdf import PdfReader
from .core import Document, Overlay, PageRef, Source, atomic_write

PLAIN=b'WARAQ-P1\n'; LOCKED=b'WARAQ-E1\n'; LOCAL=b'WARAQ-D1\n'


def snapshot(document,history=True):
    def state(pages,metadata):return {'pages':[asdict(p) for p in pages],'metadata':dict(metadata)}
    current=state(document.pages,document.metadata)
    undo=[state(*s) for s in document._undo] if history else [];redo=[state(*s) for s in document._redo] if history else []
    used={p['source'] for s in [current]+undo+redo for p in s['pages']}
    sources={sid:{'name':s.name,'data':s.data,'password':s.password,'path':str(s.path) if s.path else None}
        for sid,s in document.sources.items() if sid in used}
    saved={'pages':[asdict(p) for p in document._saved[0]],'metadata':dict(document._saved[1])}
    return {'version':1,'current':current,'undo':undo,'redo':redo,'sources':sources,'saved':saved}


def restore(state):
    if state.get('version')!=1:raise ValueError('إصدار ملف المشروع غير مدعوم.')
    model=Document()
    for sid,entry in state['sources'].items():
        data=entry['data'];password=entry.get('password','');reader=PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(password):raise ValueError('تعذر فتح مصدر محمي داخل المشروع.')
        model.sources[sid]=Source(entry['name'],data,reader,password,Path(entry['path']) if entry.get('path') else None)
    def page(value):
        p=PageRef(value['source'],int(value['index']),int(value.get('rotation',0)),
            tuple(Overlay(**o) for o in value.get('overlays',[])),value['uid'])
        if p.source not in model.sources or not 0<=p.index<len(model.sources[p.source].reader.pages) or p.rotation not in (0,90,180,270):
            raise ValueError('مرجع صفحة غير صالح داخل المشروع.')
        return p
    def decode(s):
        pages=[page(p) for p in s['pages']]
        if len({p.uid for p in pages})!=len(pages):raise ValueError('معرفات صفحات مكررة داخل المشروع.')
        return pages,{str(k):str(v) for k,v in s['metadata'].items()}
    model.pages,model.metadata=decode(state['current'])
    model._undo=[decode(s) for s in state.get('undo',[])][-30:]
    model._redo=[decode(s) for s in state.get('redo',[])][-30:]
    # Saved fingerprint can reference history already pruned from the archive;
    # only equality is needed, never dereference those page sources.
    saved=state.get('saved')
    if saved:
        saved_pages=tuple(PageRef(p['source'],int(p['index']),int(p.get('rotation',0)),tuple(Overlay(**o) for o in p.get('overlays',[])),p['uid']) for p in saved['pages'])
        model._saved=(saved_pages,tuple(sorted(saved['metadata'].items())))
    else:model.mark_saved()
    return model


def protect_local(data):
    import win32crypt
    return win32crypt.CryptProtectData(data,'Waraq PDF local recovery',None,None,None,1)


def unprotect_local(data):
    import win32crypt
    try:return win32crypt.CryptUnprotectData(data,None,None,None,1)[1]
    except Exception as exc:raise ValueError('ملف الاستعادة محمي بحساب Windows الذي أنشأه، أو أن الملف تالف.') from exc


def encode_snapshot(state,password='',local=False,compress=True):
    protected=any(s.get('password') or PdfReader(BytesIO(s['data'])).is_encrypted for s in state['sources'].values())
    if protected and not (password or local):
        raise ValueError('هذا المشروع يحتوي مصادر محمية. اختر كلمة مرور للمشروع حتى لا تُحفظ كلمات مرور المصادر دون حماية.')
    manifest={k:v for k,v in state.items() if k!='sources'};manifest['sources']={}
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED,compresslevel=3 if compress else None) as archive:
        for number,(sid,entry) in enumerate(state['sources'].items()):
            filename=f'sources/{number}.pdf';archive.writestr(filename,entry['data'])
            manifest['sources'][sid]={k:v for k,v in entry.items() if k!='data'}|{'file':filename}
        archive.writestr('project.json',json.dumps(manifest,ensure_ascii=False).encode('utf-8'))
    payload=output.getvalue()
    if local:return LOCAL+protect_local(payload)
    if password:
        salt=os.urandom(16);nonce=os.urandom(12);key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode('utf-8'))
        return LOCKED+salt+nonce+AESGCM(key).encrypt(nonce,payload,LOCKED)
    return PLAIN+payload


def decode_snapshot(data,password=''):
    if data.startswith(LOCAL):payload=unprotect_local(data[len(LOCAL):])
    elif data.startswith(LOCKED):
        if not password:raise ValueError('المشروع يحتاج كلمة مرور.')
        value=data[len(LOCKED):];salt,nonce,cipher=value[:16],value[16:28],value[28:]
        try:
            key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode('utf-8'))
            payload=AESGCM(key).decrypt(nonce,cipher,LOCKED)
        except Exception as exc:raise ValueError('كلمة مرور المشروع غير صحيحة أو الملف تالف.') from exc
    elif data.startswith(PLAIN):payload=data[len(PLAIN):]
    else:raise ValueError('هذا الملف ليس مشروع ورّاق صالحًا.')
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        entries=archive.infolist()
        if len(entries)>20000 or sum(i.file_size for i in entries)>4_000_000_000 or len({i.filename for i in entries})!=len(entries):raise ValueError('حجم أو بنية المشروع غير مدعومين.')
        if archive.getinfo('project.json').file_size>32_000_000:raise ValueError('بيانات المشروع أكبر من الحد المسموح.')
        state=json.loads(archive.read('project.json'))
        for entry in state['sources'].values():
            filename=entry.pop('file')
            if not filename.startswith('sources/') or not filename.endswith('.pdf') or '..' in filename:raise ValueError('اسم مصدر غير صالح.')
            entry['data']=archive.read(filename)
    return state


def data_directory():
    override=os.environ.get('WARAQ_DATA_DIR')
    if override:return Path(override)
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WaraqPDF'


def process_alive(pid):
    if os.name!='nt':return pid==os.getpid()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return False
    code=ctypes.c_ulong()
    try:return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(ctypes.c_void_p(handle))


class RecoveryStore:
    def __init__(self,root=None):
        self.root=Path(root) if root else data_directory()/'recovery'
        self.session=uuid.uuid4().hex;self.path=self.root/(self.session+'.recovery')

    def write(self,state):
        payload=encode_snapshot(state,local=True)
        self.root.mkdir(parents=True,exist_ok=True);atomic_write(self.path,payload)
        atomic_write(self.path.with_suffix('.json'),json.dumps({'pid':os.getpid(),'session':self.session}).encode())

    def clear(self):
        self.path.unlink(missing_ok=True);self.path.with_suffix('.json').unlink(missing_ok=True)

    def candidates(self):
        if not self.root.exists():return []
        result=[]
        for path in sorted(self.root.glob('*.recovery'),key=lambda p:p.stat().st_mtime,reverse=True):
            if path==self.path:continue
            try:meta=json.loads(path.with_suffix('.json').read_text())
            except (OSError,ValueError):meta={}
            if not process_alive(meta.get('pid',0)):result.append(path)
        return result
