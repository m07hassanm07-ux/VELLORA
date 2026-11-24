"""Capture the application's own Qt widgets for visual regression review."""
from pathlib import Path
import sys,os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'.deps'),str(root)]
from PySide6.QtCore import QEventLoop,QTimer,Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from waraq.app import MainWindow,STYLE
from waraq.rendering import ensure_font_support,render_image
from waraq.core import Overlay
import pypdfium2 as pdfium

app=QApplication([])
ensure_font_support()
app.setStyle('Fusion');app.setStyleSheet(STYLE);app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
out=root/'docs'/'screenshots';out.mkdir(parents=True,exist_ok=True)
window=MainWindow();window.show()
def wait_render():
    loop=QEventLoop();QTimer.singleShot(650,loop.quit);loop.exec()
wait_render();window.grab().save(str(out/'welcome.png'))
window.document.import_bytes('welcome.pdf',(root/'examples'/'welcome.pdf').read_bytes());window.refresh();wait_render()
window.render_current();window.grab().save(str(out/'workspace.png'))
window.document.add_overlay([0],Overlay('نسخة للمراجعة','center',34,'#b33e46',0.55))
window.document.add_overlay(list(range(3)),Overlay('',numbering=True))
window.refresh();wait_render();window.render_current()
window.grab().save(str(out/'arabic-overlay.png'))
from waraq.rendering import text_overlay
output=root/'tmp'/'qa-output.pdf';output.parent.mkdir(exist_ok=True)
window.document.save(output,overlay_renderer=text_overlay)
with pdfium.PdfDocument(str(output)) as pdf:
    render_image(pdf,0,0.9).save(str(out/'exported-page.png'))
window.brand_icon().pixmap(256,256).toImage().save(str(root/'tmp'/'icon.png'))
from PIL import Image
assets=root/'assets';assets.mkdir(exist_ok=True)
with Image.open(root/'tmp'/'icon.png') as icon:
    icon.save(assets/'vellora-v4-green.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
window.document.mark_saved();window.close()
print('Captured application and exported page in',out)
