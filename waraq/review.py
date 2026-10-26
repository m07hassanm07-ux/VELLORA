"""Portable review annotations with their own vector appearance streams."""
from io import BytesIO
from datetime import datetime,timezone
import ctypes,math,uuid
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pypdf import PdfReader,PdfWriter
from pypdf.generic import (ArrayObject,DecodedStreamObject,DictionaryObject,FloatObject,NameObject,NumberObject,RectangleObject,TextStringObject)
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,QMarginsF,QRectF,QSizeF,Qt
from PySide6.QtGui import QColor,QFont,QPageLayout,QPageSize,QPainter,QPdfWriter
from .rendering import ensure_font_support

TYPES={'/Text':'ملاحظة','/Highlight':'تمييز','/Line':'سهم','/Stamp':'ختم','/FreeText':'نص توضيحي'}


def array(values):return ArrayObject([FloatObject(float(v)) for v in values])


def list_review(data,page_index,password=''):
    reader=PdfReader(BytesIO(data))
    if reader.is_encrypted:reader.decrypt(password)
    result=[]
    for ref in reader.pages[page_index].get('/Annots',[]):
        entry=ref.get_object();kind=str(entry.get('/Subtype',''))
        if kind not in TYPES:continue
        name=str(entry.get('/NM',''))
        result.append({'id':name,'kind':kind,'label':TYPES[kind],'text':str(entry.get('/Contents','')),
            'author':str(entry.get('/T','')),'rect':[float(v) for v in entry.get('/Rect',(0,0,0,0))],
            'managed':name.startswith('waraq-')})
    return result


def appearance(writer,stream,bbox,resources=None,matrix=None):
    obj=DecodedStreamObject();obj.set_data(stream)
    obj.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
        NameObject('/BBox'):RectangleObject(bbox),NameObject('/Resources'):resources or DictionaryObject()})
    if matrix:obj[NameObject('/Matrix')]=array(matrix)
    return DictionaryObject({NameObject('/N'):writer._add_object(obj)})


def stamp_pdf(width,height,text,color):
    if width<30 or height<18 or not text.strip():raise ValueError('اختر مساحة أكبر ونصًا غير فارغ للختم.')
    ensure_font_support();data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pdf=QPdfWriter(buffer);pdf.setResolution(72);pdf.setPageSize(QPageSize(QSizeF(width,height),QPageSize.Unit.Point));pdf.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Point)
    painter=QPainter(pdf)
    try:
        painter.setPen(QColor(color));painter.drawRoundedRect(QRectF(2,2,width-4,height-4),4,4)
        size=min(24,height*.5)
        while size>6:
            font=QFont('Segoe UI');font.setPointSizeF(size);font.setBold(True);painter.setFont(font)
            if painter.fontMetrics().horizontalAdvance(text)<width-12:break
            size-=1
        if painter.fontMetrics().horizontalAdvance(text)>width-12:raise ValueError('نص الختم أطول من المساحة. وسّع الختم أو اختصر النص.')
        painter.drawText(QRectF(6,4,width-12,height-8),int(Qt.AlignmentFlag.AlignCenter),text)
    finally:painter.end()
    del pdf;buffer.close();return bytes(data)


def apply_review(data,page_index,action,payload):
    reader=PdfReader(BytesIO(data))
    if not 0<=page_index<len(reader.pages):raise ValueError('صفحة المراجعة غير صالحة.')
    writer=PdfWriter();writer.append(reader,import_outline=False);page=writer.pages[page_index]
    with pdfium.PdfDocument(data) as document:
        active=document[page_index]
        try:
            width,height=active.get_size()
            def point(x,y):
                if not math.isfinite(x+y) or not 0<=x<=width or not 0<=y<=height:raise ValueError('ضع التعليق داخل الصفحة.')
                px,py=ctypes.c_double(),ctypes.c_double()
                if not raw.FPDF_DeviceToPage(active,0,0,round(width*20),round(height*20),0,round(x*20),round(y*20),ctypes.byref(px),ctypes.byref(py)):raise ValueError('تعذر تحديد موضع التعليق.')
                return px.value,py.value
            def box(rect):
                x,y,w,h=map(float,rect)
                if w<=0 or h<=0:raise ValueError('مساحة التعليق غير صالحة.')
                corners=[point(x,y),point(x+w,y),point(x,y+h),point(x+w,y+h)]
                return (min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners))
            def set_stamp(annotation,rect,text,color):
                x,y,w,h=rect;art=PdfReader(BytesIO(stamp_pdf(w,h,text,color))).pages[0]
                origin=point(x,y+h);right=point(x+w,y+h);top=point(x,y)
                matrix=((right[0]-origin[0])/w,(right[1]-origin[1])/w,(top[0]-origin[0])/h,(top[1]-origin[1])/h,*origin)
                annotation[NameObject('/AP')]=appearance(writer,art.get_contents().get_data(),(0,0,w,h),art['/Resources'].clone(writer),matrix)
            existing=list(page.get('/Annots',[]))
            if action in ('delete','update'):
                name=str(payload.get('id',''))
                if not name.startswith('waraq-'):raise ValueError('يمكن تعديل أو حذف تعليقات ورقة فقط؛ التعليقات الأخرى تُعرض للقراءة.')
                targets=[ref for ref in existing if str(ref.get_object().get('/NM',''))==name]
                if len(targets)!=1:raise ValueError('لم يعد التعليق المحدد موجودًا.')
                if action=='delete':
                    page[NameObject('/Annots')]=ArrayObject([ref for ref in existing if ref not in targets])
                else:
                    annotation=targets[0].get_object();text=str(payload.get('text',''))[:4000]
                    annotation[NameObject('/Contents')]=TextStringObject(text)
                    annotation[NameObject('/M')]=TextStringObject(datetime.now(timezone.utc).strftime('D:%Y%m%d%H%M%SZ'))
                    if annotation.get('/Subtype')=='/Stamp':set_stamp(annotation,payload['rect'],text[:60],'#b32936')
            else:
                color=QColor(payload.get('color','#db3444'))
                if not color.isValid():raise ValueError('لون التعليق غير صالح.')
                rgb=(color.redF(),color.greenF(),color.blueF());paint=' '.join(f'{v:.4f}' for v in rgb)
                annotation=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/F'):NumberObject(4),
                    NameObject('/NM'):TextStringObject('waraq-'+uuid.uuid4().hex),NameObject('/T'):TextStringObject(str(payload.get('author',''))[:200]),
                    NameObject('/Contents'):TextStringObject(str(payload.get('text',''))[:4000]),NameObject('/C'):array(rgb),
                    NameObject('/M'):TextStringObject(datetime.now(timezone.utc).strftime('D:%Y%m%d%H%M%SZ'))})
                if action=='highlight':
                    rects=payload.get('rects',[])
                    if not rects:raise ValueError('حدد النص أولًا ثم اختر التمييز.')
                    quads=[];coordinates=[];commands=['q /GS1 gs '+paint+' rg']
                    for rect in rects:
                        x,y,w,h=rect;a,b,c,d=point(x,y),point(x+w,y),point(x,y+h),point(x+w,y+h)
                        quads.extend((*a,*b,*c,*d));coordinates.extend((a,b,c,d))
                        commands.append(f'{a[0]} {a[1]} m {b[0]} {b[1]} l {d[0]} {d[1]} l {c[0]} {c[1]} l h f')
                    bbox=(min(p[0] for p in coordinates),min(p[1] for p in coordinates),max(p[0] for p in coordinates),max(p[1] for p in coordinates))
                    gs=DictionaryObject({NameObject('/Type'):NameObject('/ExtGState'),NameObject('/ca'):FloatObject(.35),NameObject('/BM'):NameObject('/Multiply')})
                    resources=DictionaryObject({NameObject('/ExtGState'):DictionaryObject({NameObject('/GS1'):gs})})
                    annotation.update({NameObject('/Subtype'):NameObject('/Highlight'),NameObject('/Rect'):RectangleObject(bbox),NameObject('/QuadPoints'):array(quads),NameObject('/CA'):FloatObject(.35),NameObject('/AP'):appearance(writer,('\n'.join(commands)+'\nQ').encode(),bbox,resources)})
                elif action=='arrow':
                    p1=point(*payload['start']);p2=point(*payload['end']);angle=math.atan2(p2[1]-p1[1],p2[0]-p1[0]);length=math.dist(p1,p2)
                    if length<3:raise ValueError('اسحب مسافة أكبر لرسم السهم.')
                    tip=min(10,length*.3);left=(p2[0]-tip*math.cos(angle-.45),p2[1]-tip*math.sin(angle-.45));right=(p2[0]-tip*math.cos(angle+.45),p2[1]-tip*math.sin(angle+.45))
                    bbox=(min(p1[0],p2[0],left[0],right[0])-2,min(p1[1],p2[1],left[1],right[1])-2,max(p1[0],p2[0],left[0],right[0])+2,max(p1[1],p2[1],left[1],right[1])+2)
                    commands=f'q {paint} RG 2 w 1 J {p1[0]} {p1[1]} m {p2[0]} {p2[1]} l S {left[0]} {left[1]} m {p2[0]} {p2[1]} l {right[0]} {right[1]} l S Q'
                    annotation.update({NameObject('/Subtype'):NameObject('/Line'),NameObject('/Rect'):RectangleObject(bbox),NameObject('/L'):array((*p1,*p2)),NameObject('/LE'):ArrayObject([NameObject('/None'),NameObject('/OpenArrow')]),NameObject('/AP'):appearance(writer,commands.encode(),bbox)})
                elif action=='note':
                    x,y=payload['point'];rect=(min(max(0,x),max(0,width-24)),min(max(0,y),max(0,height-24)),24,24);bbox=box(rect)
                    l,b,r,t=bbox;commands=f'q 1 .85 .2 rg {l} {b} {r-l} {t-b} re f .5 .35 0 RG 1 w {l} {b} {r-l} {t-b} re S Q'
                    annotation.update({NameObject('/Subtype'):NameObject('/Text'),NameObject('/Name'):NameObject('/Note'),NameObject('/Rect'):RectangleObject(bbox),NameObject('/AP'):appearance(writer,commands.encode(),bbox)})
                elif action=='stamp':
                    rect=payload['rect'];text=str(payload.get('text','للمراجعة'))[:60]
                    annotation.update({NameObject('/Subtype'):NameObject('/Stamp'),NameObject('/Name'):NameObject('/Approved'),NameObject('/Rect'):RectangleObject(box(rect))})
                    set_stamp(annotation,rect,text,color.name())
                else:raise ValueError('أداة المراجعة غير معروفة.')
                writer.add_annotation(page_index,annotation)
        finally:active.close()
    writer.pdf_header=max(writer.pdf_header,'%PDF-1.7');output=BytesIO();writer.write(output);writer.close();return output.getvalue()
