"""Create a small, entirely synthetic sample for UI and PDF-output checks."""
from pathlib import Path
import sys, os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'.deps'),str(root)]
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QColor, QTextOption
from PySide6.QtWidgets import QApplication

app=QApplication.instance() or QApplication([])
from waraq.rendering import ensure_font_support
ensure_font_support()
destination=root/'examples'
destination.mkdir(exist_ok=True)
pdf=QPdfWriter(str(destination/'welcome.pdf'))
pdf.setResolution(72)
pdf.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
pdf.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Point)
pdf.setTitle('Welcome to Waraq PDF')
pdf.setCreator('Waraq PDF sample generator')
painter=QPainter(pdf)
pages=[
    ('مساحة أهدأ لملفاتك', 'A calmer space for your PDFs', 'ابدأ بفتح الملف، ثم اختر الصفحات التي تريد تنظيمها.', 'OPEN  /  ORGANIZE  /  SAVE'),
    ('رتّب الصفحات بطريقتك', 'Make every page fit', 'ادمج مستنداتك، غيّر الترتيب، ودوّر الصفحات دون تغيير ملفاتك الأصلية.', 'MERGE  /  REORDER  /  ROTATE'),
    ('ملفاتك تبقى على جهازك', 'Local by design. Open by choice.', 'أضف نصًا عربيًا، رقّم الصفحات، واحفظ نسخة جديدة بكلمة مرور إذا أردت.', 'ARABIC TEXT  /  PAGE NUMBERS  /  PASSWORDS'),
]
for i,(arabic,english,description,tags) in enumerate(pages):
    if i: pdf.newPage()
    painter.fillRect(QRectF(0,0,595,842),QColor('#f6f9fb'))
    painter.fillRect(QRectF(0,0,595,13),QColor('#157b67'))
    painter.setPen(QColor('#157b67'));painter.setFont(QFont('Segoe UI',20,QFont.Weight.Bold))
    painter.drawText(QRectF(46,46,503,50),Qt.AlignmentFlag.AlignRight,'ورّاق PDF')
    painter.setPen(QColor('#c4e5db'));painter.setFont(QFont('Segoe UI',100,QFont.Weight.Bold))
    painter.drawText(QRectF(46,135,503,140),Qt.AlignmentFlag.AlignLeft,f'0{i+1}')
    option=QTextOption(Qt.AlignmentFlag.AlignRight);option.setTextDirection(Qt.LayoutDirection.RightToLeft);option.setWrapMode(QTextOption.WrapMode.WordWrap)
    painter.setPen(QColor('#173d4c'));painter.setFont(QFont('Segoe UI',30,QFont.Weight.Bold))
    painter.drawText(QRectF(46,300,503,100),arabic,option)
    painter.setPen(QColor('#4b7180'));painter.setFont(QFont('Segoe UI',17))
    painter.drawText(QRectF(46,405,503,60),Qt.AlignmentFlag.AlignRight,english)
    painter.setPen(QColor('#607888'));painter.setFont(QFont('Segoe UI',17))
    painter.drawText(QRectF(46,495,503,100),description,option)
    painter.fillRect(QRectF(46,645,503,1),QColor('#d9e5eb'))
    painter.setPen(QColor('#157b67'));painter.setFont(QFont('Segoe UI',11,QFont.Weight.DemiBold))
    painter.drawText(QRectF(46,668,503,30),Qt.AlignmentFlag.AlignLeft,tags)
    painter.setPen(QColor('#738b98'));painter.setFont(QFont('Segoe UI',10))
    painter.drawText(QRectF(46,770,503,25),Qt.AlignmentFlag.AlignLeft,'SYNTHETIC SAMPLE  /  MIT LICENSE  /  WAR AQ PDF'.replace('WAR AQ','WARAQ'))
painter.end();del pdf
print(destination/'welcome.pdf')
