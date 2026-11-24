"""Saved, local batch workflows for repeatable PDF processing."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import re

from pypdf import PdfReader, PdfWriter

from .core import Overlay, atomic_write
from .rendering import text_overlay


def workflow_path() -> Path:
    override=os.environ.get('WARAQ_DATA_DIR')
    root=Path(override) if override else Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'VELLORA'
    return root/'batch-workflows.json'


def validate_workflow(value: dict) -> dict:
    if not isinstance(value,dict):raise ValueError('إعداد الإجراء غير صالح.')
    name=str(value.get('name','')).strip()
    if not name or len(name)>80:raise ValueError('اكتب اسمًا صالحًا للإجراء.')
    rotation=int(value.get('rotation',0))
    if rotation not in (0,90,180,270):raise ValueError('قيمة التدوير غير صالحة.')
    watermark=str(value.get('watermark','')).strip()
    if len(watermark)>300:raise ValueError('نص العلامة المائية طويل جدًا.')
    return {'name':name,'merge':bool(value.get('merge',False)),'rotation':rotation,
            'watermark':watermark,'numbering':bool(value.get('numbering',False))}


def load_workflows(path: Path | None=None) -> list[dict]:
    path=path or workflow_path()
    if not path.is_file():return []
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:raise ValueError('تعذر قراءة الإجراءات المحفوظة.') from exc
    if not isinstance(value,list):raise ValueError('ملف الإجراءات المحفوظة غير صالح.')
    return [validate_workflow(item) for item in value]


def save_workflows(workflows: list[dict],path: Path | None=None):
    path=path or workflow_path();validated=[validate_workflow(item) for item in workflows]
    names=[item['name'].casefold() for item in validated]
    if len(names)!=len(set(names)):raise ValueError('أسماء الإجراءات يجب أن تكون مختلفة.')
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic_write(path,json.dumps(validated,ensure_ascii=False,indent=2).encode('utf-8'))


def _safe_name(path: Path) -> str:
    return re.sub(r'[^\w\-. ]','_',path.stem,flags=re.UNICODE).strip(' .') or 'document'


def _process(reader: PdfReader, workflow: dict, start_number=1) -> tuple[PdfWriter,int]:
    writer=PdfWriter();number=start_number
    for source in reader.pages:
        writer.add_page(source);page=writer.pages[-1]
        if workflow['rotation']:page.rotate(workflow['rotation'])
        labels=[]
        if workflow['watermark']:labels.append(workflow['watermark'])
        if workflow['numbering']:labels.append(str(number))
        if labels:
            width,height=float(page.cropbox.width),float(page.cropbox.height)
            overlay=Overlay('  •  '.join(labels),'bottom',11,'#566b79',.75)
            page.merge_page(PdfReader(BytesIO(text_overlay(width,height,overlay))).pages[0])
        number+=1
    return writer,number


def execute_workflow(paths, output_dir, workflow, progress=None, cancelled=None) -> list[Path]:
    workflow=validate_workflow(workflow);sources=[Path(path) for path in paths];output_dir=Path(output_dir)
    if not sources:raise ValueError('اختر ملف PDF واحدًا على الأقل.')
    if len(sources)>500:raise ValueError('العملية الواحدة محدودة بخمسمائة ملف.')
    output_dir.mkdir(parents=True,exist_ok=True);outputs=[]
    if workflow['merge']:
        combined=PdfWriter();number=1
        for index,path in enumerate(sources,1):
            if cancelled and cancelled():raise RuntimeError('أُلغيت العملية الدفعية.')
            part,number=_process(PdfReader(path),workflow,number)
            for page in part.pages:combined.add_page(page)
            if progress:progress(index,len(sources),path.name)
        target=output_dir/(re.sub(r'[^\w\-. ]','_',workflow['name'])+'.pdf')
        stream=BytesIO();combined.write(stream);combined.close();atomic_write(target,stream.getvalue());outputs.append(target)
    else:
        for index,path in enumerate(sources,1):
            if cancelled and cancelled():raise RuntimeError('أُلغيت العملية الدفعية.')
            writer,_=_process(PdfReader(path),workflow,1);stream=BytesIO();writer.write(stream);writer.close()
            target=output_dir/(_safe_name(path)+'-processed.pdf');atomic_write(target,stream.getvalue());outputs.append(target)
            if progress:progress(index,len(sources),path.name)
    return outputs
