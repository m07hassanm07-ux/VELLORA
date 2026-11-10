"""Per-user encrypted storage for reusable visual signatures."""
from __future__ import annotations

from base64 import b64decode,b64encode
from datetime import datetime,timezone
import json,uuid
from pathlib import Path

from PySide6.QtCore import QByteArray,QBuffer,QIODevice
from PySide6.QtGui import QImage

from .core import atomic_write
from .projects import data_directory,protect_local,unprotect_local

MAGIC=b'VELLORA-SIGNATURES-1\n'


class SignatureStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else data_directory()/'signatures.vsig'

    def _read(self):
        if not self.path.exists():return {'version':1,'items':[]}
        raw=self.path.read_bytes()
        if not raw.startswith(MAGIC):raise ValueError('مكتبة التوقيعات غير صالحة.')
        try:data=json.loads(unprotect_local(raw[len(MAGIC):]).decode('utf-8'))
        except Exception as exc:raise ValueError('تعذر فتح مكتبة التوقيعات بهذا حساب Windows، أو أن الملف تالف.') from exc
        if data.get('version')!=1 or not isinstance(data.get('items'),list) or len(data['items'])>100:raise ValueError('بنية مكتبة التوقيعات غير مدعومة.')
        return data

    def _write(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        atomic_write(self.path,MAGIC+protect_local(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8')))

    def list(self):
        return [{'id':item['id'],'name':item['name'],'created':item.get('created','')} for item in self._read()['items']]

    def image(self,identifier):
        item=next((item for item in self._read()['items'] if item.get('id')==identifier),None)
        if item is None:raise ValueError('التوقيع المحفوظ غير موجود.')
        raw=b64decode(item['png'],validate=True)
        if len(raw)>8_000_000:raise ValueError('صورة التوقيع أكبر من الحد المسموح.')
        image=QImage.fromData(raw,'PNG')
        if image.isNull():raise ValueError('صورة التوقيع المحفوظة تالفة.')
        return image

    def save(self,name,image):
        name=' '.join(str(name).split())[:80]
        if not name:raise ValueError('اكتب اسمًا للتوقيع.')
        if image.isNull() or image.width()>4000 or image.height()>2000:raise ValueError('صورة التوقيع غير صالحة أو كبيرة جدًا.')
        data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG');buffer.close()
        state=self._read()
        if any(item['name'].casefold()==name.casefold() for item in state['items']):raise ValueError('يوجد توقيع محفوظ بهذا الاسم.')
        identifier=uuid.uuid4().hex;state['items'].append({'id':identifier,'name':name,'created':datetime.now(timezone.utc).isoformat(),'png':b64encode(bytes(data)).decode('ascii')})
        self._write(state);return identifier

    def delete(self,identifier):
        state=self._read();items=[item for item in state['items'] if item.get('id')!=identifier]
        if len(items)==len(state['items']):raise ValueError('التوقيع المحفوظ غير موجود.')
        state['items']=items;self._write(state)

    def rename(self,identifier,name):
        name=' '.join(str(name).split())[:80]
        if not name:raise ValueError('اكتب اسمًا للتوقيع.')
        state=self._read()
        if any(item.get('id')!=identifier and item['name'].casefold()==name.casefold() for item in state['items']):raise ValueError('يوجد توقيع محفوظ بهذا الاسم.')
        item=next((item for item in state['items'] if item.get('id')==identifier),None)
        if item is None:raise ValueError('التوقيع المحفوظ غير موجود.')
        item['name']=name;self._write(state)
