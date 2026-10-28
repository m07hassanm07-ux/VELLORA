"""Capture the selected direct-editing design using synthetic content only."""
from pathlib import Path
from io import BytesIO
import os,site,sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
root=Path(__file__).resolve().parents[1];site.addsitedir(str(root/'.deps'));sys.path[:0]=[str(root),str(root/'tests')]
from PySide6.QtCore import QRectF,Qt
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter
from waraq.app import MainWindow,STYLE
from waraq.editing import prepare_page,edit_page
from waraq.rendering import ensure_font_support

app=QApplication([]);ensure_font_support();app.setStyle('Fusion');app.setStyleSheet(STYLE);app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
writer=PdfWriter();writer.add_blank_page(595,842);stream=BytesIO();writer.write(stream)
data=prepare_page(stream.getvalue())
data=edit_page(data,text='تقرير تطوير بيئة العمل',rect=(55,55,485,65),size=28,bold=True,alignment='right')
data=edit_page(data,text='يتيح وضع التحرير المباشر تعديل النصوص والصور من داخل الصفحة مع الحفاظ على تجربة واضحة وسريعة للمستخدم.',rect=(55,175,485,95),size=17,alignment='right')
data=edit_page(data,text='أهداف المشروع',rect=(55,330,485,50),size=22,bold=True,alignment='right')
data=edit_page(data,text='• تحرير النص مباشرة\n• استخدام خطوط المؤسسة\n• حفظ الصفحات كقوالب قابلة لإعادة الاستخدام',rect=(55,410,485,130),size=16,alignment='right')
window=MainWindow();window.resize(1440,1024);window.document.import_bytes('تقرير-العمل.pdf',data);window.refresh();window.show();app.processEvents()
window.edit_page_content();app.processEvents();editor=window._page_editor
editor.group_mode.setCurrentIndex(2);app.processEvents();editor.pick_region(QRectF(45,160,505,120));app.processEvents()
out=root/'docs'/'screenshots';out.mkdir(parents=True,exist_ok=True);window.grab().save(str(out/'inline-editor.png'))
window.cancel_inline_edit();window.document.mark_saved();window.close()
print(out/'inline-editor.png')
