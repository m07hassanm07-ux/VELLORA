"""Capture only synthetic editor content; never load private documents."""
from pathlib import Path
from io import BytesIO
import os, site, sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root/'.deps')]
if (root/'.deps').exists(): site.addsitedir(str(root/'.deps'))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter
import pypdfium2 as pdfium
from waraq.app import STYLE, MainWindow
from waraq.core import Document
from waraq.editing import edit_page, prepare_page
from waraq.editor_dialog import PageEditorDialog
from waraq.rendering import ensure_font_support, render_image

app = QApplication([]); ensure_font_support()
app.setStyle('Fusion'); app.setStyleSheet(STYLE); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
writer = PdfWriter(); writer.add_blank_page(595, 842); stream = BytesIO(); writer.write(stream)
data = prepare_page(stream.getvalue())
data = edit_page(data, text='مستند تجريبي للتحرير', rect=(35, 35, 525, 75), size=26, bold=True)
data = edit_page(data, text='ORIGINAL CONTENT', rect=(40, 165, 500, 50), size=20)
data = edit_page(data, text='هذه الفقرة تبقى كما هي بعد تعديل النص أعلاه.', rect=(40, 320, 500, 65), size=17)
out = root/'docs'/'screenshots'; out.mkdir(exist_ok=True)
dialog = PageEditorDialog(data); dialog.show(); app.processEvents()
dialog.pick_region(QRectF(30, 150, 520, 80))
assert dialog.selected_indexes()
dialog.text.setPlainText('المحتوى المعدّل — EDITED PDF')
dialog.set_rect(QRectF(40, 165, 500, 75))
dialog.preview_change(); assert dialog.draft is not None
app.processEvents(); dialog.grab().save(str(out/'page-editor.png'))
dialog.apply_change(); assert dialog.history
image = QImage(240, 120, QImage.Format.Format_ARGB32); image.fill(QColor('#dff2ec'))
painter = QPainter(image); painter.setPen(QColor('#127a65')); painter.drawEllipse(85, 25, 70, 70); painter.end()
dialog.mode = 'image'; dialog.image = image
dialog.set_rect(QRectF(40, 440, 220, 130)); dialog.apply_change()
dialog.new_text(); dialog.text.setPlainText('ملاحظة جديدة أُضيفت إلى الصفحة')
dialog.set_rect(QRectF(40, 610, 500, 65)); dialog.apply_change()
edited = dialog.data
assert 'ORIGINAL' not in ''.join(e.text for e in dialog.entries)
(root/'examples'/'editing-demo.pdf').write_bytes(edited)
with pdfium.PdfDocument(edited) as pdf:
    render_image(pdf, 0, 1).save(str(out/'edited-page.png'))
dialog.close()
window = MainWindow(); window.document.import_bytes('editing-demo.pdf', edited)
window.refresh(); window.show(); app.processEvents(); window.render_current()
window.grab().save(str(out/'editing-workspace.png'))
window.document.mark_saved(); window.close()
print('Synthetic editing screenshots and example generated.')
