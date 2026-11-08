"""Interactive text selection over the rendered page and a Unicode search dock."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget


class PageImage(QLabel):
    region_selected = Signal(QRectF)
    clear_requested = Signal()
    placement=Signal(object)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.start = None; self.band = None; self.ratio = 1
        self.selected_rects = []; self.search_rects = []
        self.review_rects=[];self.tool='select'
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self); painter.setPen(Qt.PenStyle.NoPen)
        for rects, color in ((self.search_rects,QColor(255,193,7,100)),(self.selected_rects,QColor(41,128,205,80))):
            painter.setBrush(color)
            for rect in rects:
                x,y,w,h=rect; painter.drawRect(QRectF(x*self.ratio,y*self.ratio,w*self.ratio,h*self.ratio))
        if self.band is not None:
            painter.setBrush(QColor(41,128,205,35)); painter.setPen(QPen(QColor('#2583bd'),1))
            painter.drawRect(self.band)
        painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#ca3647'),2))
        for x,y,w,h in self.review_rects:painter.drawRect(QRectF(x*self.ratio,y*self.ratio,w*self.ratio,h*self.ratio))
        painter.end()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.setFocus(); self.start=event.position(); self.band=None; event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.start is not None:
            self.band=QRectF(self.start,event.position()).normalized(); self.update(); event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.start is not None and event.button()==Qt.MouseButton.LeftButton:
            start=self.start;rect=QRectF(start,event.position()).normalized(); self.start=None; self.band=None
            if self.tool!='select':
                self.placement.emit({'tool':self.tool,'start':(start.x()/self.ratio,start.y()/self.ratio),'end':(event.position().x()/self.ratio,event.position().y()/self.ratio)})
            elif rect.width()<3 and rect.height()<3:
                self.clear_requested.emit()
            else:
                self.region_selected.emit(QRectF(rect.x()/self.ratio,rect.y()/self.ratio,rect.width()/self.ratio,rect.height()/self.ratio))
            self.update(); event.accept(); return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            self.tool='select';self.setCursor(Qt.CursorShape.IBeamCursor);self.clear_requested.emit(); return
        super().keyPressEvent(event)


class SearchDock(QDockWidget):
    search_requested=Signal(str)
    match_selected=Signal(int)

    def __init__(self,parent):
        super().__init__('البحث داخل المستند',parent)
        self.setObjectName('documentSearch')
        widget=QWidget(); layout=QVBoxLayout(widget)
        row=QHBoxLayout(); self.query=QLineEdit(); self.query.setPlaceholderText('ابحث بالعربية أو الإنجليزية…')
        row.addWidget(self.query); button=QPushButton('بحث'); row.addWidget(button); layout.addLayout(row)
        self.status=QLabel(''); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.results=QListWidget(); layout.addWidget(self.results)
        self.setWidget(widget); self.setMinimumWidth(280)
        self.query.returnPressed.connect(lambda:self.search_requested.emit(self.query.text()))
        button.clicked.connect(lambda:self.search_requested.emit(self.query.text()))
        self.results.currentRowChanged.connect(self.match_selected.emit)

    def set_results(self,matches):
        self.results.clear()
        for match in matches:
            self.results.addItem(f"صفحة {match['page']+1} — {match['text'][:90]}")
        self.status.setText(f'{len(matches)} نتيجة' if matches else 'لا توجد نتائج. المستندات المصورة تحتاج OCR أولًا.')
        if matches: self.results.setCurrentRow(0)


class OcrDialog(QDialog):
    def __init__(self,engine,parent=None):
        super().__init__(parent); self.setWindowTitle('التعرف على النص OCR'); self.resize(540,300)
        layout=QVBoxLayout(self)
        note=QLabel('التعرف يعمل محليًا عبر محرك Tesseract المثبت منفصلًا. بيانات العربية والإنجليزية مرفقة مع VELLORA. تُحفظ صورة الصفحة وتُضاف طبقة مخفية للبحث والنسخ.');note.setWordWrap(True);layout.addWidget(note)
        download=QPushButton('تنزيل محرك Tesseract من مصدره')
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        download.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://github.com/UB-Mannheim/tesseract/wiki')));layout.addWidget(download)
        form=QFormLayout(); self.language=QComboBox()
        for label,value in [('العربية والإنجليزية','ara+eng'),('العربية','ara'),('الإنجليزية','eng')]:self.language.addItem(label,value)
        form.addRow('اللغة',self.language)
        self.scope=QComboBox();self.scope.addItem('كل المستند',False);self.scope.addItem('الصفحات المحددة',True);form.addRow('الصفحات',self.scope)
        row=QHBoxLayout();self.engine=QLineEdit(str(engine) if engine else '');row.addWidget(self.engine)
        browse=QPushButton('اختيار…');row.addWidget(browse);browse.clicked.connect(self.choose_engine);form.addRow('محرك Tesseract',row)
        layout.addLayout(form);self.skip=QCheckBox('تخطي الصفحات التي تحتوي نصًا بالفعل');self.skip.setChecked(True);layout.addWidget(self.skip)
        self.preprocess=QCheckBox('تحسين المسح تلقائيًا: إزالة ضوضاء ورفع التباين');self.preprocess.setChecked(True);layout.addWidget(self.preprocess)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('بدء التعرف');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('إلغاء')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def choose_engine(self):
        path,_=QFileDialog.getOpenFileName(self,'اختيار tesseract.exe','','Tesseract (tesseract.exe)')
        if path:self.engine.setText(path)


class ReviewDock(QDockWidget):
    tool_requested=Signal(str)
    selected=Signal(int)
    edit_requested=Signal()
    delete_requested=Signal()

    def __init__(self,parent):
        super().__init__('الملاحظات والمراجعة',parent);self.setObjectName('reviewDock');self.setMinimumWidth(290)
        widget=QWidget();layout=QVBoxLayout(widget);self.author=QLineEdit();self.author.setPlaceholderText('اسم المراجع (اختياري)');layout.addWidget(self.author)
        row=QHBoxLayout()
        for label,kind in [('تمييز','highlight'),('ملاحظة','note'),('سهم','arrow'),('ختم','stamp')]:
            button=QPushButton(label);button.clicked.connect(lambda checked=False,k=kind:self.tool_requested.emit(k));row.addWidget(button)
        layout.addLayout(row);self.items=QListWidget();layout.addWidget(self.items)
        from PySide6.QtWidgets import QPlainTextEdit
        self.contents=QPlainTextEdit();self.contents.setReadOnly(True);self.contents.setMaximumHeight(160);layout.addWidget(self.contents)
        row=QHBoxLayout();self.edit=QPushButton('تعديل النص');self.delete=QPushButton('حذف التعليق');row.addWidget(self.edit);row.addWidget(self.delete);layout.addLayout(row)
        self.edit.setEnabled(False);self.delete.setEnabled(False);self.setWidget(widget)
        self.items.currentRowChanged.connect(self.selected.emit);self.edit.clicked.connect(self.edit_requested.emit);self.delete.clicked.connect(self.delete_requested.emit)

    def set_annotations(self,annotations):
        self.items.clear();self.contents.clear();self.edit.setEnabled(False);self.delete.setEnabled(False)
        for annotation in annotations:
            text=annotation['text'].replace('\n',' ')[:70]
            self.items.addItem(annotation['label']+(' — '+text if text else ''))
