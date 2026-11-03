from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import math
import sys
import traceback
import logging
import os

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QItemSelectionModel, QRect, QSettings
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog, QAbstractPrintDialog
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStatusBar,
    QToolBar, QVBoxLayout, QWidget, QStyledItemDelegate, QStyle, QProgressDialog,
)
import pypdfium2 as pdfium
from pypdf import PdfWriter

from . import __version__
from .core import Document, Overlay, PasswordRequired, atomic_write, parse_pages
from .rendering import render_image, text_overlay, ensure_font_support
from .printing import paint_pdf, requested_pages, PrintCancelled
from .merge_dialog import MergeDialog
from .conversion import (acquire_wia_image, convert_file, image_bytes_to_pdf,
                         web_to_pdf, export_pdf_office, SUPPORTED_TYPES, ConversionCancelled)
from .editor_dialog import PageEditorDialog
from .templates import encode_template, decode_template, builtin_template
from .professional import (add_attachment, attachment_bytes, list_attachments, remove_attachment,
                           add_form_field, export_page_images, extract_text, fill_form_fields,
                           inspect_signatures, list_form_fields, secure_redact_page, secure_redact_text)
from .preflight import preflight_pdf, sanitize_pdf
from .reading import PageImage, SearchDock, OcrDialog, ReviewDock
from .textlayout import Glyph, character_map, find_matches, normal_text, select_region
from .ocr import find_tesseract, run_ocr, JobCancelled
from .projects import snapshot, restore, encode_snapshot, decode_snapshot, RecoveryStore, LOCKED
from .tasks import TaskThread,run_task,process_job
from .render_service import ProcessRenderer
from .compare import compare_pdfs


STYLE = """
* { font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QDialog { background: #f4f7fa; color: #152c3b; }
QMenuBar, QMenu { background: #ffffff; color: #152c3b; }
QMenu::item:selected { background: #dff4ef; }
QFrame#header { background: #ffffff; border-bottom: 1px solid #dce5ec; }
QLabel#brand { font-size: 22pt; font-weight: 750; color: #123b48; }
QLabel#tagline, QLabel#subtle { color: #647989; }
QLabel#section { color: #274656; font-weight: 650; font-size: 11pt; }
QLabel#badge { background: #e0f4ee; color: #166950; padding: 6px 12px; border-radius: 12px; }
QFrame#tools { background: #ffffff; border-bottom: 1px solid #dce5ec; }
QPushButton { background: #ffffff; color: #234553; border: 1px solid #d5e1e8; border-radius: 8px; padding: 8px 13px; min-height: 19px; }
QPushButton:hover { background: #edf6f4; border-color: #81b5aa; }
QPushButton:pressed { background: #d8eee8; }
QPushButton:disabled { color: #a3afb6; background: #f5f7f9; border-color: #e2e8ed; }
QPushButton#primary { background: #157b67; border-color: #157b67; color: white; font-weight: 650; }
QPushButton#primary:hover { background: #106451; }
QPushButton#primary:disabled { background: #a3c5bd; border-color: #a3c5bd; color: white; }
QPushButton#danger { color: #b33e46; }
QPushButton#ghost { background: transparent; border: none; color: #416370; }
QFrame#sidebar { background: #ffffff; border-left: 1px solid #dce5ec; }
QListWidget { background: #f8fafc; border: none; outline: none; padding: 8px; }
QListWidget::item { border: 1px solid #dfe7ed; border-radius: 9px; margin: 5px 2px; padding: 9px; color: #3a5665; background: white; }
QListWidget::item:selected { background: #e5f5ef; border: 2px solid #24977c; color: #124f40; }
QListWidget::item:hover { border-color: #76b7a6; }
QScrollArea { border: none; background: #dfe7ed; }
QWidget#previewSurface { background: #dfe7ed; }
QLabel#pageImage { background: white; border: 1px solid #c7d2da; }
QFrame#viewerBar { background: #f9fbfc; border-bottom: 1px solid #dce5ec; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; color: #152c3b; border: 1px solid #cfdae2; border-radius: 6px; padding: 6px; min-height: 20px; }
QStatusBar { background: #ffffff; border-top: 1px solid #dce5ec; color: #5b7382; }
QLabel#emptyTitle { font-size: 30pt; font-weight: 750; color: #173d4c; }
QLabel#emptyText { font-size: 12pt; color: #67808f; }
QLabel#emptyMark { font-size: 54pt; font-weight: 750; background: #dff2ec; color: #167761; border-radius: 22px; }
QSplitter::handle { background: #dce5ec; width: 1px; }
QToolTip { background: #173d4c; color: white; border: none; padding: 5px; }
"""

DARK_STYLE = """
QMainWindow, QDialog { background: #17232b; color: #e8f0f4; }
QMenuBar, QMenu, QFrame#header, QFrame#tools, QFrame#sidebar, QStatusBar { background: #1d2c35; color: #e8f0f4; border-color: #38505d; }
QLabel#brand { color: #7ed8c0; } QLabel#tagline, QLabel#subtle { color: #aec0ca; }
QLabel#badge { background: #24463e; color: #9ae2cf; }
QPushButton { background: #263944; color: #e8f0f4; border-color: #49616e; }
QPushButton:hover { background: #31505a; } QPushButton:disabled { color: #70828b; background: #202e36; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget { background: #21323c; color: #edf4f7; border-color: #48606c; }
QListWidget::item { background: #263944; color: #dce8ed; border-color: #415963; }
QListWidget::item:selected { background: #245c50; color: white; border-color: #62c6ad; }
QWidget#previewSurface, QScrollArea { background: #10191f; }
QLabel#pageImage { background: white; }
"""


class PageDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor("#e5f5ef" if selected else "#ffffff"))
        painter.setPen(QColor("#24977c" if selected else "#dfe7ed"))
        painter.drawRoundedRect(rect, 9, 9)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(painter, QRect(rect.center().x() - 64, rect.top() + 9, 128, 166), Qt.AlignmentFlag.AlignCenter)
        painter.setPen(QColor("#124f40" if selected else "#3a5665"))
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").split("\n")
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(QRect(rect.left() + 5, rect.top() + 177, rect.width() - 10, 20), Qt.AlignmentFlag.AlignCenter, text[0])
        painter.setFont(QFont("Segoe UI", 8))
        if len(text) > 1:
            name = painter.fontMetrics().elidedText(text[1], Qt.TextElideMode.ElideMiddle, rect.width() - 15)
            painter.drawText(QRect(rect.left() + 5, rect.top() + 197, rect.width() - 10, 18), Qt.AlignmentFlag.AlignCenter, name)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, 225)


class PageList(QListWidget):
    externalFiles = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(128, 166))
        self.setSpacing(3)
        self.setItemDelegate(PageDelegate(self))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.externalFiles.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class PreviewArea(QScrollArea):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class TextDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("إضافة نص أو علامة مائية")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        note = QLabel("يُضاف النص كطبقة جديدة؛ النص الأصلي يبقى كما هو.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.text = QLineEdit()
        self.text.setMaxLength(200)
        self.text.setPlaceholderText("اكتب بالعربية أو الإنجليزية")
        self.position = QComboBox()
        for title, value in [("أسفل الصفحة", "bottom"), ("وسط الصفحة", "center"), ("أعلى الصفحة", "top")]:
            self.position.addItem(title, value)
        self.size = QSpinBox()
        self.size.setRange(8, 96)
        self.size.setValue(18)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.1, 1)
        self.opacity.setSingleStep(0.1)
        self.opacity.setValue(0.9)
        self.color = QComboBox()
        for title, value in [("أخضر داكن", "#123b48"), ("رمادي", "#657786"), ("أحمر", "#bc4148"), ("أسود", "#111111")]:
            self.color.addItem(title, value)
        self.all_pages = QCheckBox("تطبيق على جميع الصفحات")
        for label, widget in [("النص", self.text), ("الموضع", self.position), ("حجم الخط", self.size), ("العتامة", self.opacity), ("اللون", self.color)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(self.all_pages)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("إضافة")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SaveDialog(QDialog):
    def __init__(self, parent, title="حفظ نسخة PDF", protected_input=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        description = QLabel("تُنشأ نسخة من الصفحات الحالية. الحماية الأصلية لا تنتقل تلقائيًا؛ فعّل الخيار أدناه لحماية النسخة الجديدة.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.protect = QCheckBox("حماية النسخة بكلمة مرور")
        self.password = QLineEdit()
        self.confirm = QLineEdit()
        self.owner = QLineEdit()
        for field in (self.password, self.confirm, self.owner):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setEnabled(False)
        self.protect.toggled.connect(self.password.setEnabled)
        self.protect.toggled.connect(self.confirm.setEnabled)
        self.protect.toggled.connect(self.owner.setEnabled)
        self.protect.setChecked(protected_input)
        form = QFormLayout()
        form.addRow(self.protect)
        form.addRow("كلمة المرور", self.password)
        form.addRow("تأكيد الكلمة", self.confirm)
        form.addRow("كلمة مرور المسؤول", self.owner)
        self.allow_print=QCheckBox('السماح بالطباعة');self.allow_print.setChecked(True)
        self.allow_copy=QCheckBox('السماح بالنسخ واستخراج النص');self.allow_copy.setChecked(True)
        self.allow_modify=QCheckBox('السماح بالتعديل والتجميع والتعليقات');self.allow_modify.setChecked(True)
        for option in (self.allow_print,self.allow_copy,self.allow_modify):
            option.setEnabled(False);self.protect.toggled.connect(option.setEnabled);form.addRow(option)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("اختيار مكان الحفظ")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        if self.protect.isChecked() and (len(self.password.text()) < 8 or self.password.text() != self.confirm.text()):
            QMessageBox.information(self, "كلمة المرور", "استخدم 8 أحرف على الأقل، وتأكد من تطابق الكلمتين.")
            return
        self.accept()

    def output_password(self):
        return self.password.text() if self.protect.isChecked() else ""

    def security_options(self):
        if not self.protect.isChecked():return {'password':'','owner_password':'','permissions':None}
        reserved=sum(1 << bit for bit in range(6,32));permissions=reserved
        if self.allow_print.isChecked():permissions|=4|2048
        if self.allow_copy.isChecked():permissions|=16|512
        if self.allow_modify.isChecked():permissions|=8|32|256|1024
        return {'password':self.password.text(),'owner_password':self.owner.text() or self.password.text(),'permissions':permissions}


class PrintOptionsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('خيارات الطباعة المتقدمة');self.setMinimumWidth(390)
        layout=QVBoxLayout(self);note=QLabel('إعدادات الورق والاتجاه والوجهين والنسخ تُضبط من نافذة طابعة Windows.');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();self.nup=QComboBox()
        for title,value in [('صفحة واحدة في الورقة',1),('صفحتان في الورقة',2),('أربع صفحات في الورقة',4)]:self.nup.addItem(title,value)
        self.grayscale=QCheckBox('طباعة بتدرج رمادي')
        form.addRow('تخطيط الورقة',self.nup);form.addRow(self.grayscale);layout.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('متابعة الطباعة');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('إلغاء')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.pdfs: dict[str, pdfium.PdfDocument] = {}
        self.thumbnail_cache: dict[tuple, QIcon] = {}
        self.zoom = 1.0
        self.fit_mode = True
        self.rebuilding = False
        self.last_output: Path | None = None
        self.project_path=None;self.project_password='';self.recovery=RecoveryStore();self._autosave_fingerprint=None
        self.reading_key = None; self.current_glyphs = []; self.selected_text = ''
        self.renderer=ProcessRenderer(self);self._view_serial=0;self._thumb_inflight=False;self._autosave_thread=None
        self.selection_rects = []; self.selection_char_ids = []; self.search_matches = []; self.pending_match = None
        self.review_annotations=[];self._stamp_label='للمراجعة'
        self._pending_form_field=None
        self.settings=QSettings();self.dark_mode=str(self.settings.value('ui/dark_mode','false')).lower()=='true'
        self._page_editor=None;self._editing_page=-1
        self.resize(1320, 850)
        self.setMinimumSize(980, 650)
        self.setWindowTitle("ورقة | Waraqa")
        self.setAcceptDrops(True)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowIcon(self.brand_icon())
        self.buttons = {}
        self.actions = {}
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.render_current)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setInterval(20)
        self.thumb_timer.timeout.connect(self.next_thumbnail)
        self.thumb_queue: list[int] = []
        self.make_ui()
        self.make_menu()
        self.apply_theme(self.dark_mode)
        self.search_dock = SearchDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.search_dock); self.search_dock.hide()
        self.search_dock.search_requested.connect(self.search_document)
        self.search_dock.match_selected.connect(self.show_search_match)
        self.review_dock=ReviewDock(self);self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.review_dock);self.review_dock.hide()
        self.review_dock.tool_requested.connect(self.begin_review);self.review_dock.selected.connect(self.select_review)
        self.review_dock.edit_requested.connect(self.edit_review);self.review_dock.delete_requested.connect(self.delete_review)
        self.autosave_timer=QTimer(self);self.autosave_timer.setInterval(30000);self.autosave_timer.timeout.connect(self.autosave_now)
        if QApplication.platformName()!='offscreen' or os.environ.get('WARAQ_DATA_DIR'):self.autosave_timer.start()
        self.refresh()

    def brand_icon(self):
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        icon = QIcon(str(root / 'waraqa-icon.png'))
        if not icon.isNull():
            return icon
        return QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / 'waraqa-icon.png'))

    def make_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame(objectName="header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        brand = QLabel("ورقة", objectName="brand")
        brand_column = QVBoxLayout()
        brand_column.setSpacing(1)
        brand_column.addWidget(brand)
        brand_column.addWidget(QLabel("ملفاتك، مرتّبة على طريقتك", objectName="tagline"))
        header_layout.addLayout(brand_column)
        header_layout.addStretch()
        header_layout.addWidget(QLabel("محلي بالكامل  •  مفتوح المصدر", objectName="badge"))
        open_button = self.button("فتح PDF", self.open_dialog, primary=True)
        open_button.setToolTip("فتح مستند جديد · Ctrl+O")
        header_layout.addWidget(open_button)
        header_layout.addWidget(self.button("إنشاء PDF", self.create_pdf_dialog))
        self.edit_button = self.button("تعديل PDF", self.edit_page_content)
        self.edit_button.setToolTip("تعديل نص الصفحة وإضافة النصوص والصور · Ctrl+Shift+E")
        header_layout.addWidget(self.edit_button)
        self.print_button = self.button("طباعة", self.print_document)
        self.print_button.setToolTip("الطباعة عبر طابعات Windows · Ctrl+P")
        header_layout.addWidget(self.print_button)
        self.save_button = self.button("حفظ نسخة", self.save_document, primary=True)
        header_layout.addWidget(self.save_button)
        layout.addWidget(header)

        tools = QFrame(objectName="tools")
        tool_layout = QHBoxLayout(tools)
        tool_layout.setContentsMargins(18, 10, 18, 10)
        for key, title, handler in [
            ("add", "دمج ملفات", self.merge_dialog),
            ("extract", "استخراج صفحات", self.extract_pages),
            ("split", "تقسيم", self.split_document),
            ("text", "نص / علامة مائية", self.add_text),
            ("number", "ترقيم الصفحات", self.add_numbers),
            ("web", "صفحة ويب", self.import_web),
            ("templates", "قوالب", self.insert_template),
        ]:
            self.buttons[key] = self.button(title, handler)
            tool_layout.addWidget(self.buttons[key])
        tool_layout.addStretch()
        self.undo_button = self.button("تراجع", self.undo)
        self.redo_button = self.button("إعادة", self.redo)
        tool_layout.addWidget(self.undo_button)
        tool_layout.addWidget(self.redo_button)
        layout.addWidget(tools)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.stack.addWidget(self.empty_workspace())
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self.page_sidebar())
        self.splitter.addWidget(self.viewer())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 1050])
        self.stack.addWidget(self.splitter)
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("جاهز  •  لا يتم رفع ملفاتك إلى أي خادم")
        status.addWidget(self.status_label, 1)
        version = QLabel(f"Waraqa  {__version__}")
        version.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        status.addPermanentWidget(version)

    def button(self, title, handler, primary=False):
        button = QPushButton(title)
        button.clicked.connect(handler)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            button.setObjectName("primary")
        return button

    def empty_workspace(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)
        mark = QLabel("و", objectName="emptyMark")
        mark.setFixedSize(108, 108)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("مساحة أهدأ لملفات PDF", objectName="emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        text = QLabel("اعرض صفحاتك، رتّبها، واجمعها في نسخة جديدة.\nكل العمل يتم على جهازك.", objectName="emptyText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet("line-height: 1.6;")
        layout.addWidget(text)
        open_button = self.button("اختيار ملفات PDF", self.open_dialog, primary=True)
        open_button.setFixedWidth(240)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = QLabel("أو اسحب الملفات إلى هنا  •  Ctrl+O", objectName="subtle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        features = QLabel("دمج وتقسيم   /   ترتيب وتدوير   /   نص عربي وترقيم", objectName="subtle")
        features.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(features)
        return widget

    def page_sidebar(self):
        sidebar = QFrame(objectName="sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(350)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(16, 15, 16, 12)
        self.page_count = QLabel("الصفحات", objectName="section")
        top_layout.addWidget(self.page_count)
        hint = QLabel("اسحب لترتيب الصفحات • Ctrl لتحديد متعدد", objectName="subtle")
        hint.setWordWrap(True)
        top_layout.addWidget(hint)
        layout.addWidget(top)
        self.pages = PageList()
        self.pages.currentRowChanged.connect(self.schedule_preview)
        self.pages.itemSelectionChanged.connect(self.update_status)
        self.pages.model().rowsMoved.connect(self.pages_moved)
        self.pages.externalFiles.connect(lambda paths: self.import_paths(paths, append=bool(self.document.pages)))
        layout.addWidget(self.pages, 1)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(12, 10, 12, 12)
        first_row = QHBoxLayout()
        first_row.addWidget(self.button("تدوير يمين", lambda: self.rotate(90)))
        first_row.addWidget(self.button("تدوير يسار", lambda: self.rotate(-90)))
        second_row = QHBoxLayout()
        second_row.addWidget(self.button("تكرار", self.duplicate))
        delete = self.button("حذف", self.delete_pages)
        delete.setObjectName("danger")
        second_row.addWidget(delete)
        third_row = QHBoxLayout()
        third_row.addWidget(self.button("نقل للأعلى", lambda: self.move_pages(-1)))
        third_row.addWidget(self.button("نقل للأسفل", lambda: self.move_pages(1)))
        controls_layout.addLayout(first_row)
        controls_layout.addLayout(second_row)
        controls_layout.addLayout(third_row)
        layout.addWidget(controls)
        return sidebar

    def viewer(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QFrame(objectName="viewerBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(15, 9, 15, 9)
        self.document_name = QLabel("المستند", objectName="section")
        self.document_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar_layout.addWidget(self.document_name, 1)
        self.page_number = QSpinBox()
        self.page_number.setMinimum(1)
        self.page_number.setFixedWidth(85)
        self.page_number.valueChanged.connect(self.go_to_page)
        self.page_number.setToolTip("الانتقال إلى صفحة")
        bar_layout.addWidget(QLabel("صفحة"))
        bar_layout.addWidget(self.page_number)
        bar_layout.addWidget(self.button("−", lambda: self.change_zoom(0.8)))
        self.zoom_label = QLabel("ملاءمة")
        self.zoom_label.setMinimumWidth(55)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar_layout.addWidget(self.zoom_label)
        bar_layout.addWidget(self.button("+", lambda: self.change_zoom(1.25)))
        bar_layout.addWidget(self.button("ملاءمة العرض", self.fit_page))
        bar_layout.addWidget(self.button('بحث',self.open_search))
        bar_layout.addWidget(self.button('مراجعة',self.open_review))
        layout.addWidget(bar)
        self.preview = PreviewArea()
        self.preview.setWidgetResizable(True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.resized.connect(lambda: self.preview_timer.start(140) if self.fit_mode else None)
        self.preview_surface = QWidget(objectName="previewSurface")
        preview_layout = QVBoxLayout(self.preview_surface)
        preview_layout.setContentsMargins(30, 26, 30, 26)
        preview_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.image_label = PageImage(objectName="pageImage")
        self.image_label.region_selected.connect(self.select_page_text)
        self.image_label.clear_requested.connect(self.clear_text_selection)
        self.image_label.placement.connect(self.place_review)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.image_label)
        self.preview.setWidget(self.preview_surface)
        layout.addWidget(self.preview, 1)
        return widget

    def make_menu(self):
        menu = self.menuBar()
        files = menu.addMenu("ملف")
        edits = menu.addMenu("تحرير")
        view = menu.addMenu("عرض")
        tools = menu.addMenu('أدوات')
        review = menu.addMenu('مراجعة')
        help_menu = menu.addMenu("مساعدة")
        for parent, key, title, shortcut, handler in [
            (files, "open", "فتح مستند…", "Ctrl+O", self.open_dialog),
            (files, 'openproject', 'فتح مشروع ورقة…', 'Ctrl+Alt+O', self.open_project),
            (files, 'saveproject', 'حفظ مشروع للاستكمال…', 'Ctrl+Shift+S', self.save_project),
            (files, "add", "إضافة ملفات…", "Ctrl+Shift+O", self.add_dialog),
            (files, "merge", "دمج عدة ملفات…", "Ctrl+M", self.merge_dialog),
            (files, "create", "إنشاء PDF من ملف…", "", self.create_pdf_dialog),
            (files, "web", "إنشاء PDF من صفحة ويب…", "", self.import_web),
            (files, "save", "حفظ نسخة…", "Ctrl+S", self.save_document),
            (files, "print", "طباعة…", "Ctrl+P", self.print_document),
            (files, "printpreview", "معاينة الطباعة…", "Ctrl+Shift+P", self.print_preview),
            (files, "extract", "استخراج صفحات…", "Ctrl+E", self.extract_pages),
            (files, "blank", "إضافة صفحة فارغة", "Ctrl+N", self.add_blank),
            (files, "inserttemplate", "إدراج صفحة من قالب…", "Ctrl+Alt+T", self.insert_template),
            (files, "savetemplate", "حفظ الصفحة الحالية كقالب…", "", self.save_current_template),
            (files, "metadata", "خصائص المستند…", "", self.edit_metadata),
            (files, "close", "إغلاق مساحة العمل", "Ctrl+W", self.new_workspace),
            (edits, "undo", "تراجع", "Ctrl+Z", self.undo),
            (edits, "redo", "إعادة", "Ctrl+Shift+Z", self.redo),
            (edits, "select", "تحديد الكل", "Ctrl+A", self.pages.selectAll),
            (edits, "editcontent", "تعديل محتوى الصفحة…", "Ctrl+Shift+E", self.edit_page_content),
            (edits, "copytext", "نسخ النص المحدد", "Ctrl+C", self.copy_selected_text),
            (edits, "copypage", "نسخ نص الصفحة", "Ctrl+Shift+C", self.copy_page_text),
            (edits, "search", "بحث داخل المستند…", "Ctrl+F", self.open_search),
            (edits, "rotate", "تدوير الصفحات المحددة", "Ctrl+R", lambda: self.rotate(90)),
            (edits, "delete", "حذف الصفحات المحددة", "Delete", self.delete_pages),
            (edits, "cleartext", "إزالة النصوص المضافة من المحدد", "", self.clear_text),
            (view, "fit", "ملاءمة العرض", "Ctrl+0", self.fit_page),
            (view, "zoom", "الحجم الطبيعي", "Ctrl+1", self.actual_size),
            (tools, 'ocr', 'التعرف على النص OCR…', '', self.ocr_document),
            (tools, 'forms', 'تعبئة حقول النموذج…', 'Ctrl+Alt+F', self.fill_pdf_form),
            (tools, 'createform', 'إنشاء حقل نموذج…', '', self.begin_create_form_field),
            (tools, 'signatures', 'فحص التوقيعات…', '', self.check_signatures),
            (tools, 'visualsignature', 'إضافة توقيع مرئي…', '', self.begin_visual_signature),
            (tools, 'exporttext', 'تصدير النص…', '', self.export_text_file),
            (tools, 'exportimages', 'تصدير الصفحات كصور…', '', self.export_page_images_dialog),
            (tools, 'exportoffice', 'تصدير إلى Word / Excel / PowerPoint…', '', self.export_office_dialog),
            (tools, 'addattachment', 'إضافة مرفق إلى PDF…', '', self.add_pdf_attachment),
            (tools, 'extractattachment', 'استخراج مرفق…', '', self.extract_pdf_attachment),
            (tools, 'removeattachment', 'حذف مرفق…', '', self.remove_pdf_attachment),
            (tools, 'compare', 'مقارنة مع نسخة أخرى…', 'Ctrl+Alt+C', self.compare_with_pdf),
            (tools, 'bookmark', 'إضافة أو تعديل إشارة مرجعية…', 'Ctrl+B', self.edit_bookmark),
            (tools, 'clearbookmark', 'حذف الإشارة المرجعية للصفحة', '', self.clear_bookmark),
            (tools, 'scanner', 'مسح صفحة من الماسح الضوئي…', '', self.scan_page),
            (tools, 'preflight', 'فحص المستند قبل النشر…', '', self.preflight_document),
            (tools, 'sanitize', 'تنظيف البيانات الخفية…', '', self.sanitize_document),
            (tools, 'redactsearch', 'تنقيح نص في جميع الصفحات…', '', self.redact_text_everywhere),
            (tools, 'redact', 'تنقيح آمن…', 'Ctrl+Alt+D', self.begin_secure_redaction),
            (review,'reviewpanel','لوحة المراجعة…','Ctrl+Alt+R',self.open_review),
            (review,'highlight','تمييز النص المحدد','Ctrl+Shift+H',lambda:self.begin_review('highlight')),
            (review,'note','إضافة ملاحظة','Ctrl+Shift+N',lambda:self.begin_review('note')),
            (review,'arrow','رسم سهم','',lambda:self.begin_review('arrow')),
            (review,'stamp','إضافة ختم','',lambda:self.begin_review('stamp')),
            (help_menu, "about", "عن ورقة…", "", self.about),
        ]:
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            parent.addAction(action)
            self.actions[key] = action
        view.addSeparator();dark=QAction('الوضع الداكن',self);dark.setCheckable(True);dark.setChecked(self.dark_mode);dark.triggered.connect(self.toggle_dark_mode);view.addAction(dark);self.actions['dark']=dark
        files.addSeparator();self.recent_menu=files.addMenu('الملفات الحديثة');self.refresh_recent_menu()

    def apply_theme(self,dark):
        QApplication.instance().setStyleSheet(STYLE+(DARK_STYLE if dark else ''))

    def toggle_dark_mode(self,checked):
        self.dark_mode=bool(checked);self.settings.setValue('ui/dark_mode',self.dark_mode);self.apply_theme(self.dark_mode)

    def recent_paths(self):
        value=self.settings.value('recent/files',[]) or []
        if isinstance(value,str):value=[value]
        return [str(path) for path in value if str(path).strip()][:10]

    def remember_recent(self,paths):
        recent=self.recent_paths()
        for raw in paths:
            path=str(Path(raw).resolve())
            if not Path(path).is_file():continue
            recent=[item for item in recent if item.casefold()!=path.casefold()];recent.insert(0,path)
        self.settings.setValue('recent/files',recent[:10]);self.refresh_recent_menu()

    def refresh_recent_menu(self):
        if not hasattr(self,'recent_menu'):return
        self.recent_menu.clear();paths=self.recent_paths()
        for path in paths:
            action=self.recent_menu.addAction(Path(path).name);action.setToolTip(path);action.triggered.connect(lambda checked=False,p=path:self.open_recent(p))
        if not paths:
            action=self.recent_menu.addAction('لا توجد ملفات حديثة');action.setEnabled(False)
        else:
            self.recent_menu.addSeparator();clear=self.recent_menu.addAction('مسح القائمة');clear.triggered.connect(lambda:self.clear_recent())

    def clear_recent(self):
        self.settings.remove('recent/files');self.refresh_recent_menu()

    def open_recent(self,path):
        if Path(path).is_file():self.import_paths([path],append=False)
        else:
            self.settings.setValue('recent/files',[item for item in self.recent_paths() if item.casefold()!=path.casefold()]);self.refresh_recent_menu();self.error('لم يعد الملف موجودًا في هذا المكان.')

    def error(self, message, exception=None):
        if exception is not None:
            traceback.print_exception(exception)
            logging.getLogger('waraqa').exception('Operation failed',exc_info=exception)
        QMessageBox.warning(self, "تعذر إكمال العملية", str(message))

    @contextmanager
    def busy(self, message):
        self.thumb_timer.stop()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_label.setText(message)
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
            self.update_status()
            if self.thumb_queue:
                self.thumb_timer.start()

    def confirm_discard(self):
        if not self.document.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("تغييرات غير محفوظة")
        box.setText("هل تريد حفظ التغييرات قبل مغادرة مساحة العمل؟")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Save).setText("حفظ نسخة")
        box.button(QMessageBox.StandardButton.Discard).setText("تجاهل التغييرات")
        box.button(QMessageBox.StandardButton.Cancel).setText("إلغاء")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        result = box.exec()
        if result == QMessageBox.StandardButton.Save:
            return self.save_document()
        return result == QMessageBox.StandardButton.Discard

    def close_pdfs(self):
        self.renderer.close();self._thumb_inflight=False;self._view_serial+=1
        for pdf in self.pdfs.values():
            pdf.close()
        self.pdfs.clear()
        self.thumbnail_cache.clear()

    def new_workspace(self):
        if self._page_editor is not None:
            self._page_editor.finish()
            if self._page_editor is not None:return
        if not self.confirm_discard():
            return
        self.close_pdfs()
        self.document = Document()
        self.last_output = None
        self.clear_recovery();self.project_path=None;self.project_password='';self._autosave_fingerprint=None
        self.refresh()

    def autosave_now(self):
        if self._autosave_thread and self._autosave_thread.isRunning():return
        if not self.document.pages or not self.document.dirty:
            self.recovery.clear();self._autosave_fingerprint=None;return
        fingerprint=self.document.fingerprint()
        if fingerprint==self._autosave_fingerprint:return
        state=snapshot(self.document);store=self.recovery
        thread=TaskThread(lambda report,cancelled:store.write(state),self);self._autosave_thread=thread
        def saved(_):
            if self.document.fingerprint()==fingerprint:self._autosave_fingerprint=fingerprint
            self.statusBar().showMessage('حُفظت نسخة استعادة محلية مشفرة.',4000)
        def done():
            if self._autosave_thread is thread:self._autosave_thread=None
            thread.deleteLater()
        thread.succeeded.connect(saved);thread.failed.connect(lambda _:self.statusBar().showMessage('تعذر الحفظ التلقائي. احفظ المشروع يدويًا.',10000))
        thread.finished.connect(done);thread.start()

    def clear_recovery(self):
        if self._autosave_thread and self._autosave_thread.isRunning():self._autosave_thread.wait()
        self.recovery.clear();self._autosave_fingerprint=None

    def save_project(self):
        if not self.document.pages:return False
        path,_=QFileDialog.getSaveFileName(self,'حفظ مشروع ورقة',str(self.project_path or 'مشروع.waraq'),'Waraqa project (*.waraq)')
        if not path:return False
        if not path.lower().endswith('.waraq'):
            path+='.waraq'
            if Path(path).exists() and QMessageBox.question(self,'ملف موجود','المشروع موجود بالفعل. هل تريد استبداله؟',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return False
        password,ok=QInputDialog.getText(self,'حماية المشروع','كلمة مرور للمشروع (اختيارية، وإلزامية عند وجود مصادر PDF محمية):',QLineEdit.EchoMode.Password,text=self.project_password)
        if not ok:return False
        try:
            state=snapshot(self.document)
            def save(report,cancelled):
                report(0,0,'جاري حفظ المشروع ومصادره…');data=encode_snapshot(state,password=password)
                if cancelled():raise JobCancelled()
                atomic_write(path,data)
            run_task(self,'حفظ المشروع',save)
            self.project_path=Path(path);self.project_password=password;self.document.mark_saved();self.clear_recovery();self.update_status()
            self.statusBar().showMessage('حُفظ المشروع مع مصادره وسجل التراجع. يمكنك استكماله لاحقًا.',10000);return True
        except JobCancelled:return False
        except Exception as exc:self.error(exc);return False

    def open_project(self,path=None):
        if isinstance(path,bool):path=None
        if not path:
            path,_=QFileDialog.getOpenFileName(self,'فتح مشروع ورقة','','Waraqa project (*.waraq)')
        if not path or not self.confirm_discard():return
        try:
            data=Path(path).read_bytes();password=''
            if data.startswith(LOCKED):
                password,ok=QInputDialog.getText(self,'مشروع محمي','كلمة مرور المشروع:',QLineEdit.EchoMode.Password)
                if not ok:return
            document=run_task(self,'فتح المشروع',lambda report,cancelled:restore(decode_snapshot(data,password)));document.mark_saved()
            self.close_pdfs();self.clear_recovery();self.document=document;self.project_path=Path(path);self.project_password=password;self.last_output=None
            self._autosave_fingerprint=None;self.refresh()
        except JobCancelled:pass
        except Exception as exc:self.error(exc)

    def offer_recovery(self):
        try:
            candidates=self.recovery.candidates()
            if not candidates:return
            path=candidates[0]
            answer=QMessageBox.question(self,'استعادة العمل','توجد جلسة لم تُغلق بصورة طبيعية. هل تريد استعادة آخر نسخة محفوظة تلقائيًا؟',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.Yes)
            if answer!=QMessageBox.StandardButton.Yes:return
            if not self.confirm_discard():return
            document=restore(decode_snapshot(path.read_bytes()))
            self.close_pdfs();self.document=document;self.recovery.path=path;self.recovery.session=path.stem
            self._autosave_fingerprint=None;self.project_path=None;self.project_password='';self.last_output=None;self.refresh();self.autosave_now()
        except Exception as exc:self.error(f'تعذر استعادة الجلسة: {exc}')

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "فتح مستندات PDF", "", "PDF (*.pdf)")
        if paths:
            self.import_paths(paths, append=False)

    def add_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "إضافة ملفات إلى المستند", "", "PDF (*.pdf)")
        if paths:
            self.import_paths(paths, append=True)

    def merge_dialog(self):
        dialog = MergeDialog(self, bool(self.document.pages))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_paths(dialog.paths(), append=dialog.append_current.isChecked())

    def create_pdf_dialog(self):
        filters = "الملفات المدعومة (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.rtf *.txt *.odt *.ods *.odp *.html *.htm);;PDF (*.pdf);;صور (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;Office (*.doc *.docx *.xls *.xlsx *.ppt *.pptx *.rtf *.odt *.ods *.odp)"
        paths, _ = QFileDialog.getOpenFileNames(self, "إنشاء PDF من ملفات", "", filters)
        if paths:
            self.import_paths(paths, append=bool(self.document.pages))

    def conversion_progress(self, label):
        progress = QProgressDialog(label, "إلغاء", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        def tick():
            QApplication.processEvents()
            return not progress.wasCanceled()
        return progress, tick

    def import_web(self):
        url, ok = QInputDialog.getText(self, "حفظ صفحة ويب كملف PDF", "رابط الصفحة (http أو https):\nيستخدم متصفحًا مثبتًا وملف تعريف مؤقتًا؛ لا يسجل الدخول بحسابك.")
        if not ok or not url.strip():
            return
        try:
            data=self.document_job('تحويل صفحة الويب','web',{'url':url.strip()})['data']
            current = len(self.document.pages)
            self.document.import_bytes("صفحة ويب.pdf", data)
            self.refresh(current)
        except (ConversionCancelled,JobCancelled):
            pass
        except Exception as exc:
            self.error(exc)

    def import_paths(self, paths, append=False):
        paths = [str(p) for p in paths if Path(p).suffix.lower() in SUPPORTED_TYPES]
        if not paths:
            self.error("اختر ملفات PDF أو صورًا أو مستندات من الصيغ المدعومة.")
            return
        if not append and not self.confirm_discard():
            return
        # Keep the old workspace until at least one new file has been read.
        target = self.document if append else Document()
        first_index = len(target.pages)
        imported = 0
        signed = False
        failures = []
        for path in paths:
            password = ""
            while True:
                try:
                    empty=snapshot(Document())
                    result=run_task(self,'فتح '+Path(path).name,lambda report,cancelled:process_job(empty,'import',{'path':path,'password':password},report,cancelled))
                    if result.get('needs_password'):raise PasswordRequired()
                    name=Path(path).name if Path(path).suffix.lower()=='.pdf' else Path(path).stem+'.pdf'
                    source_id=target.import_bytes(name,result['data'],password,path=Path(path))
                    signed |= target.sources[source_id].signed
                    imported += 1
                    break
                except PasswordRequired:
                    password, ok = QInputDialog.getText(self, "ملف محمي", f"كلمة مرور {Path(path).name}", QLineEdit.EchoMode.Password)
                    if not ok:
                        break
                except (ConversionCancelled,JobCancelled):
                    break
                except Exception as exc:
                    failures.append(f"{Path(path).name}: {exc}")
                    break
        if imported:
            self.remember_recent(paths)
            if not append:
                self.close_pdfs()
                self.clear_recovery();self.project_path=None;self.project_password='';self._autosave_fingerprint=None
                self.document = target
                self.last_output = None
                if imported == 1:
                    target.mark_saved()
            self.refresh(first_index)
            if signed:
                QMessageBox.information(self, "مستند موقّع", "الحفظ هنا يعيد إنشاء PDF ولا يحافظ على صلاحية التوقيع الرقمي الأصلي. احتفظ بالملف الأصلي.")
        if failures:
            self.error("\n\n".join(failures))

    def selected(self):
        indexes = sorted(self.pages.row(item) for item in self.pages.selectedItems())
        if not indexes and self.pages.currentRow() >= 0:
            indexes = [self.pages.currentRow()]
        return indexes

    def refresh(self, current=0, selected_ids=None):
        self.reading_key = None; self.current_glyphs = []; self.clear_text_selection()
        self.pending_match = None; self.search_matches = []
        self.review_annotations=[];self.image_label.review_rects=[];self.image_label.tool='select'
        if hasattr(self,'review_dock'):self.review_dock.set_annotations([])
        if hasattr(self,'search_dock'): self.search_dock.results.clear()
        self.rebuilding = True
        self.thumb_timer.stop()
        self.pages.clear()
        for index, page in enumerate(self.document.pages):
            name = self.document.sources[page.source].name
            bookmark=f"  ★ {page.bookmark[:20]}" if page.bookmark else ''
            item = QListWidgetItem(f"صفحة {index + 1}{bookmark}\n{name[:25]}")
            item.setData(Qt.ItemDataRole.UserRole, page.uid)
            item.setSizeHint(QSize(200, 225))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(f"{name}\nالصفحة الأصلية: {page.index + 1}\nتدوير إضافي: {page.rotation}°")
            self.pages.addItem(item)
            if selected_ids and page.uid in selected_ids:
                item.setSelected(True)
        count = len(self.document.pages)
        self.stack.setCurrentIndex(1 if count else 0)
        self.page_count.setText(f"الصفحات  /  {count}")
        self.page_number.blockSignals(True)
        self.page_number.setMaximum(max(1, count))
        self.page_number.blockSignals(False)
        self.rebuilding = False
        if count:
            flags = QItemSelectionModel.SelectionFlag.NoUpdate if selected_ids else QItemSelectionModel.SelectionFlag.ClearAndSelect
            self.pages.setCurrentRow(min(max(0, current), count - 1), flags)
            self.schedule_preview()
        self.thumb_queue = list(range(count))
        if count:
            self.thumb_timer.start()
        self.update_status()

    def update_status(self):
        count = len(self.document.pages)
        source_count = len({p.source for p in self.document.pages})
        selected = len(self.selected())
        self.status_label.setText(f"{count} صفحة  •  {source_count} ملف  •  {selected} محدد  •  العمل محلي على جهازك" if count else "جاهز  •  اسحب ملف PDF أو اختر فتح")
        names = list(dict.fromkeys(self.document.sources[p.source].name for p in self.document.pages))
        title = names[0] if len(names) == 1 else f"مستند مدمج من {len(names)} ملفات" if names else "مساحة العمل"
        self.document_name.setText(title)
        self.setWindowTitle(f"{'● ' if self.document.dirty else ''}{title} — ورقة")
        self.save_button.setEnabled(bool(count))
        self.print_button.setEnabled(bool(count))
        self.edit_button.setEnabled(bool(count))
        for key, button in self.buttons.items():
            button.setEnabled(bool(count) or key in ("add", "web", "templates"))
        self.undo_button.setEnabled(self.document.can_undo)
        self.redo_button.setEnabled(self.document.can_redo)
        for key, action in self.actions.items():
            if key == "undo":
                action.setEnabled(self.document.can_undo)
            elif key == "redo":
                action.setEnabled(self.document.can_redo)
            elif key not in ("open", "openproject", "add", "blank", "inserttemplate", "about", "close", "merge", "create", "web", "dark"):
                action.setEnabled(bool(count))

    def pdf_for(self, source_id):
        if source_id not in self.pdfs:
            source = self.document.sources[source_id]
            self.pdfs[source_id] = pdfium.PdfDocument(source.data, password=source.password or None)
        return self.pdfs[source_id]

    def page_image(self, index, scale):
        page = self.document.pages[index]
        if page.overlays:
            data = self.document.build_bytes([index], overlay_renderer=text_overlay, preview_context=(index + 1, len(self.document.pages)))
            with pdfium.PdfDocument(data) as pdf:
                return render_image(pdf, 0, scale)
        return render_image(self.pdf_for(page.source), page.index, scale, page.rotation)

    def next_thumbnail(self):
        if self._thumb_inflight:return
        if not self.thumb_queue:
            self.thumb_timer.stop()
            return
        index = self.thumb_queue.pop(0)
        if index >= len(self.document.pages):
            return
        page = self.document.pages[index]
        key = (page.uid, page.source, page.index, page.rotation, page.overlays, index if any(o.numbering for o in page.overlays) else -1, len(self.document.pages))
        try:
            if key in self.thumbnail_cache:
                self.pages.item(index).setIcon(self.thumbnail_cache[key]);return
            width,height=self.display_size(page);scale=min(128/max(width,1),166/max(height,1))
            self._thumb_inflight=True;self.thumb_timer.stop()
            def completed(meta,png):
                self._thumb_inflight=False
                if not meta.get('error'):
                    image=QImage.fromData(png,'PNG');self.thumbnail_cache[key]=QIcon(QPixmap.fromImage(image))
                    if len(self.thumbnail_cache)>350:self.thumbnail_cache.pop(next(iter(self.thumbnail_cache)))
                    if index<len(self.document.pages) and self.document.pages[index]==page:self.pages.item(index).setIcon(self.thumbnail_cache[key])
                if self.thumb_queue:self.thumb_timer.start()
            self.renderer.submit(self.document.sources[page.source],page,scale,completed,index=index,total=len(self.document.pages))
        except Exception:
            # A failed thumbnail must not prevent saving or manipulating the document.
            pass

    def schedule_preview(self, *_):
        if not self.rebuilding:
            self.preview_timer.start(60)

    def render_current(self):
        index = self.pages.currentRow()
        if index < 0 or index >= len(self.document.pages):
            return
        try:
            page = self.document.pages[index]
            width,height=self.display_size(page)
            scale = self.zoom * 96 / 72
            if self.fit_mode:
                scale = max(0.1, (self.preview.viewport().width() - 72) / max(width, 1))
                self.zoom = scale * 72 / 96
            # Cap render allocation while retaining document quality in saved files.
            scale = min(scale, 2600 / max(width, height, 1))
            key=(page,len(self.document.pages))
            if self.reading_key != key:
                self.current_glyphs=[];self.clear_text_selection();self.image_label.clear();self.image_label.setText('جاري عرض الصفحة…')
            self._view_serial+=1;serial=self._view_serial
            def completed(meta,png):
                if serial!=self._view_serial or index!=self.pages.currentRow() or index>=len(self.document.pages) or self.document.pages[index]!=page:return
                if meta.get('error'):
                    self.image_label.setText('تعذر عرض الصفحة');self.status_label.setText(meta['error']);return
                image=QImage.fromData(png,'PNG');pixmap=QPixmap.fromImage(image)
                self.image_label.setPixmap(pixmap);self.image_label.setFixedSize(pixmap.size());self.image_label.ratio=scale
                changed=self.reading_key!=key
                self.current_glyphs=[Glyph(g['index'],g['text'],tuple(g['rect']),g['object_index']) for g in meta['glyphs']]
                self.reading_key=key
                if changed:
                    self.review_annotations=meta.get('annotations',[]);self.review_dock.set_annotations(self.review_annotations)
                self.image_label.search_rects=self.pending_match[1] if self.pending_match and self.pending_match[0]==index else []
                self.image_label.update();self.zoom_label.setText(f'{round(self.zoom*100)}%')
                self.page_number.blockSignals(True);self.page_number.setValue(index+1);self.page_number.blockSignals(False);self.update_status()
            self.renderer.submit(self.document.sources[page.source],page,scale,completed,reading=True,index=index,total=len(self.document.pages))
        except Exception as exc:
            self.image_label.clear()
            self.image_label.setText("تعذر عرض هذه الصفحة")
            self.status_label.setText(f"تعذر عرض الصفحة: {exc}")

    def display_size(self,reference):
        page=self.document.sources[reference.source].reader.pages[reference.index]
        unit=float(page.get('/UserUnit',1));width,height=float(page.cropbox.width)*unit,float(page.cropbox.height)*unit
        return (height,width) if (page.rotation+reference.rotation)%180 else (width,height)

    def document_job(self,label,kind,params):
        state=snapshot(self.document,history=False)
        return run_task(self,label,lambda report,cancelled:process_job(state,kind,params,report,cancelled))

    def write_pdf_background(self,path,indexes,security):
        state=snapshot(self.document,history=False)
        def save(report,cancelled):
            result=process_job(state,'assemble',{'indexes':indexes,**security},report,cancelled)
            report(0,0,'جاري حفظ النسخة…')
            if cancelled():raise JobCancelled()
            atomic_write(path,result['data'])
        return run_task(self,'حفظ PDF',save)

    def clear_text_selection(self):
        self.selected_text='';self.selection_rects=[];self.selection_char_ids=[]
        if hasattr(self,'image_label'):
            self.image_label.selected_rects=[];self.image_label.update()

    def select_page_text(self,rect):
        self.selected_text,self.selection_rects,self.selection_char_ids=select_region(self.current_glyphs,(rect.x(),rect.y(),rect.width(),rect.height()))
        self.image_label.selected_rects=self.selection_rects;self.image_label.update()
        self.statusBar().showMessage(f'{len(self.selected_text)} حرف محدد — Ctrl+C للنسخ' if self.selected_text else 'لا يوجد نص في هذا التحديد. قد تحتاج الصفحة المصورة إلى OCR.',10000)

    def copy_selected_text(self):
        if self.selected_text:
            QApplication.clipboard().setText(self.selected_text);self.statusBar().showMessage('نُسخ النص المحدد.',5000)

    def copy_page_text(self):
        text=normal_text(''.join(g.text for g in self.current_glyphs))
        if text.strip():QApplication.clipboard().setText(text);self.statusBar().showMessage('نُسخ نص الصفحة.',5000)
        else:self.statusBar().showMessage('لا يوجد نص قابل للنسخ. استخدم OCR للصفحات المصورة.',10000)

    def open_search(self):
        self.review_dock.hide()
        self.search_dock.show();self.search_dock.raise_();self.search_dock.query.setFocus();self.search_dock.query.selectAll()

    def open_review(self):
        self.search_dock.hide();self.review_dock.show();self.review_dock.raise_()

    def begin_review(self,kind):
        if not self.document.pages:return
        self.open_review()
        if kind=='highlight':
            if not self.selection_rects:
                self.statusBar().showMessage('حدد النص بالسحب على الصفحة أولًا ثم اختر «تمييز».',12000);return
            self.apply_review_action('highlight',{'rects':self.selection_rects,'text':self.selected_text,'color':'#ffdc20'});return
        if kind=='stamp':
            label,ok=QInputDialog.getItem(self,'نص الختم','اختر الختم أو اكتب نصًا قصيرًا:',['معتمد','للمراجعة','مسودة','سري'],0,True)
            if not ok or not label.strip():return
            self._stamp_label=label.strip()[:60]
        self.image_label.tool=kind;self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('انقر مكان الملاحظة على الصفحة.' if kind=='note' else 'اسحب على الصفحة لتحديد موضع السهم أو الختم. Esc للإلغاء.',15000)

    def place_review(self,gesture):
        kind=gesture['tool'];self.image_label.tool='select';self.image_label.setCursor(Qt.CursorShape.IBeamCursor)
        if not self.document.pages or self.reading_key!=(self.document.pages[self.pages.currentRow()],len(self.document.pages)):return
        start,end=gesture['start'],gesture['end'];payload={}
        if kind=='form':
            x,y=min(start[0],end[0]),min(start[1],end[1]);w,h=abs(end[0]-start[0]),abs(end[1]-start[1])
            spec=self._pending_form_field;self._pending_form_field=None
            if spec is None:return
            try:
                data=self.assembled_bytes('إنشاء حقل النموذج')
                result=add_form_field(data,self.pages.currentRow(),spec['kind'],spec['name'],(x,y,w,h),value=spec['value'],options=spec['options'])
                self.document.replace_document(result,'نموذج PDF.pdf');self.refresh(self.pages.currentRow())
                self.statusBar().showMessage(f'تم إنشاء الحقل «{spec["name"]}». اختر «حفظ نسخة» لحفظ النموذج.',12000)
            except JobCancelled:pass
            except Exception as exc:self.error(exc,exc)
            return
        if kind=='redact':
            x,y=min(start[0],end[0]),min(start[1],end[1]);w,h=abs(end[0]-start[0]),abs(end[1]-start[1])
            if w<4 or h<4:self.statusBar().showMessage('اسحب مساحة أكبر للتنقيح.',8000);return
            if QMessageBox.warning(self,'تنقيح آمن',
                'سيُحذف كل المحتوى الأصلي داخل الصفحة المحددة بتحويل الصفحة إلى صورة ثابتة، '
                'ولا يمكن استعادة النص أو العناصر منها بعد حفظ النسخة. هل تريد التطبيق؟',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            try:
                data=self.assembled_bytes('تجهيز التنقيح الآمن')
                result=secure_redact_page(data,self.pages.currentRow(),[(x,y,w,h)])
                self.document.replace_document(result,'مستند منقح.pdf');self.refresh(self.pages.currentRow())
                self.statusBar().showMessage('تم التنقيح الآمن. اختر «حفظ نسخة» لإنشاء الملف النهائي.',12000)
            except JobCancelled:pass
            except Exception as exc:self.error(exc,exc)
            return
        if kind=='note':
            text,ok=QInputDialog.getMultiLineText(self,'ملاحظة','نص الملاحظة:')
            if not ok or not text.strip():return
            payload={'point':start,'text':text}
        elif kind=='arrow':payload={'start':start,'end':end}
        elif kind=='stamp':
            x,y=min(start[0],end[0]),min(start[1],end[1]);w,h=abs(end[0]-start[0]),abs(end[1]-start[1])
            width,height=self.display_size(self.document.pages[self.pages.currentRow()])
            if w<40 or h<25:w,h=min(180,width),min(65,height)
            x=max(0,min(x,width-w));y=max(0,min(y,height-h))
            payload={'rect':(x,y,w,h),'text':self._stamp_label}
        else:return
        self.apply_review_action(kind,payload)

    def begin_secure_redaction(self):
        if not self.document.pages:return
        self.image_label.tool='redact';self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('اسحب مستطيلًا فوق المعلومات الحساسة. سيطلب ورقة تأكيدًا قبل الحذف الدائم.',15000)

    def begin_create_form_field(self):
        if not self.document.pages:return
        labels=['حقل نص','مربع اختيار','قائمة اختيار'];kinds=['text','checkbox','choice']
        label,ok=QInputDialog.getItem(self,'إنشاء حقل نموذج','نوع الحقل:',labels,0,False)
        if not ok:return
        kind=kinds[labels.index(label)]
        name,ok=QInputDialog.getText(self,'إنشاء حقل نموذج','اسم داخلي فريد للحقل:')
        if not ok or not name.strip():return
        value='';options=[]
        if kind=='text':
            value,ok=QInputDialog.getText(self,'القيمة الافتراضية','القيمة الافتراضية (اختيارية):')
            if not ok:return
        elif kind=='checkbox':value='Off'
        else:
            raw,ok=QInputDialog.getMultiLineText(self,'خيارات القائمة','اكتب كل خيار في سطر مستقل:')
            if not ok:return
            options=[line.strip() for line in raw.splitlines() if line.strip()]
            if not options:self.error('أضف خيارًا واحدًا على الأقل للقائمة.');return
            value=options[0]
        self._pending_form_field={'kind':kind,'name':name.strip(),'value':value,'options':options}
        self.image_label.tool='form';self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('اسحب على الصفحة لتحديد مكان وحجم الحقل الجديد. Esc للإلغاء.',15000)

    def begin_visual_signature(self):
        if not self.document.pages:return
        signer,ok=QInputDialog.getText(self,'توقيع مرئي','اسم الموقّع:')
        if not ok or not signer.strip():return
        from datetime import datetime
        self._stamp_label=f'توقيع: {signer.strip()} — {datetime.now().strftime("%Y-%m-%d")}'[:60]
        self.image_label.tool='stamp';self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('اسحب لتحديد مكان التوقيع المرئي. هذا توقيع بصري وليس شهادة رقمية.',15000)

    def apply_review_action(self,action,payload):
        index=self.pages.currentRow()
        if index<0:return
        payload=dict(payload);payload['author']=self.review_dock.author.text().strip()
        try:
            result=self.document_job('حفظ تعليق المراجعة','review',{'page':index,'action':action,'payload':payload})
            self.document.replace_document(result['data'],'مستند للمراجعة.pdf');self.refresh(index);self.open_review()
        except JobCancelled:pass
        except Exception as exc:self.error(exc)

    def select_review(self,row):
        if not 0<=row<len(self.review_annotations):
            self.image_label.review_rects=[];self.image_label.update();return
        annotation=self.review_annotations[row]
        self.review_dock.contents.setPlainText((annotation['author']+'\n' if annotation['author'] else '')+annotation['text'])
        self.review_dock.edit.setEnabled(annotation['managed']);self.review_dock.delete.setEnabled(annotation['managed'])
        self.image_label.review_rects=[annotation['rect']];self.image_label.update()

    def edit_review(self):
        row=self.review_dock.items.currentRow()
        if not 0<=row<len(self.review_annotations):return
        annotation=self.review_annotations[row]
        if not annotation['managed']:return
        text,ok=QInputDialog.getMultiLineText(self,'تعديل التعليق','نص التعليق:',text=annotation['text'])
        if ok:self.apply_review_action('update',{'id':annotation['id'],'text':text,'rect':annotation['rect']})

    def delete_review(self):
        row=self.review_dock.items.currentRow()
        if 0<=row<len(self.review_annotations) and self.review_annotations[row]['managed']:
            self.apply_review_action('delete',{'id':self.review_annotations[row]['id']})

    def search_document(self,query):
        if not query.strip() or not self.document.pages:return
        try:
            self.search_matches=self.document_job('البحث داخل المستند','search',{'query':query})['matches']
            self.search_dock.set_results(self.search_matches)
        except JobCancelled:pass
        except Exception as exc:self.error(exc)

    def show_search_match(self,row):
        if 0<=row<len(self.search_matches):
            match=self.search_matches[row];self.pending_match=(match['page'],match['rects'])
            self.go_to_page(match['page']+1);self.schedule_preview()

    def ocr_document(self):
        if not self.document.pages:return
        settings=QSettings();configured=settings.value('ocr/engine','')
        dialog=OcrDialog(find_tesseract(configured),self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        engine=dialog.engine.text().strip()
        if engine:settings.setValue('ocr/engine',engine)
        indexes=self.selected() if dialog.scope.currentData() else list(range(len(self.document.pages)))
        try:
            job=self.document_job('التعرف على النص OCR','ocr',{'indexes':indexes,'language':dialog.language.currentData(),'engine':engine,'skip_text':dialog.skip.isChecked()})
            result,report=job['data'],job['report']
            if report['recognized']:
                current=self.pages.currentRow();self.document.replace_document(result,'مستند OCR.pdf');self.refresh(current)
            self.statusBar().showMessage(f"اكتمل OCR: {len(report['recognized'])} صفحة، وتُخطّيت {len(report['skipped'])} صفحة تحتوي نصًا.",15000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc)

    def go_to_page(self, number):
        if not self.rebuilding and number - 1 != self.pages.currentRow():
            self.pages.setCurrentRow(number - 1)

    def change_zoom(self, factor):
        self.fit_mode = False
        self.zoom = min(3, max(0.15, self.zoom * factor))
        self.schedule_preview()

    def fit_page(self):
        self.fit_mode = True
        self.schedule_preview()

    def actual_size(self):
        self.zoom = 1.0
        self.fit_mode = False
        self.schedule_preview()

    def rotate(self, degrees):
        indexes = self.selected()
        if indexes:
            self.document.rotate(indexes, degrees)
            self.refresh(indexes[0], {self.document.pages[i].uid for i in indexes})

    def duplicate(self):
        indexes = self.selected()
        if indexes:
            self.document.duplicate(indexes)
            self.refresh(indexes[0])

    def delete_pages(self):
        indexes = self.selected()
        if indexes:
            try:
                self.document.remove(indexes)
                self.refresh(min(indexes[0], len(self.document.pages) - 1))
            except ValueError as exc:
                self.error(exc)

    def move_pages(self, delta):
        indexes = self.selected()
        if not indexes:
            return
        if delta < 0 and indexes[0] == 0 or delta > 0 and indexes[-1] == len(self.document.pages) - 1:
            return
        ids = [p.uid for p in self.document.pages]
        chosen = {ids[i] for i in indexes}
        for index in (indexes if delta < 0 else reversed(indexes)):
            ids[index], ids[index + delta] = ids[index + delta], ids[index]
        self.document.reorder(ids)
        self.refresh(indexes[0] + delta, chosen)

    def pages_moved(self, *_):
        if not self.rebuilding:
            ids = [self.pages.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pages.count())]
            selected_ids = {item.data(Qt.ItemDataRole.UserRole) for item in self.pages.selectedItems()}
            self.document.reorder(ids)
            QTimer.singleShot(0, lambda: self.refresh(self.pages.currentRow(), selected_ids))

    def undo(self):
        current = self.pages.currentRow()
        self.document.undo()
        self.refresh(current)

    def redo(self):
        current = self.pages.currentRow()
        self.document.redo()
        self.refresh(current)

    def add_blank(self):
        writer = PdfWriter()
        writer.add_blank_page(595.28, 841.89)
        data = BytesIO()
        writer.write(data)
        writer.close()
        index = len(self.document.pages)
        self.document.import_bytes("صفحة فارغة A4", data.getvalue())
        self.refresh(index)

    def save_current_template(self):
        if not self.document.pages:return
        index=max(0,self.pages.currentRow())
        path,_=QFileDialog.getSaveFileName(self,'حفظ قالب ورقة','قالب-ورقة.waraqt','قالب ورقة (*.waraqt)')
        if not path:return
        if not path.lower().endswith('.waraqt'):path += '.waraqt'
        try:
            data=self.document_job('تجهيز القالب','assemble',{'indexes':[index]})['data']
            from .core import atomic_write
            atomic_write(path,encode_template(data,Path(path).stem))
            self.statusBar().showMessage('حُفظ القالب. يمكنك إدراجه لاحقًا في أي مستند.',10000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc)

    def insert_template(self):
        choices=['تقرير عمل','خطاب رسمي','محضر اجتماع','فتح قالب محفوظ…']
        choice,ok=QInputDialog.getItem(self,'قوالب ورقة','اختر قالبًا لإضافته كصفحة جديدة:',choices,0,False)
        if not ok:return
        try:
            if choice=='فتح قالب محفوظ…':
                path,_=QFileDialog.getOpenFileName(self,'إدراج قالب ورقة','','قالب ورقة (*.waraqt)')
                if not path:return
                name,data=decode_template(Path(path).read_bytes())
            else:
                name,data=builtin_template({'تقرير عمل':'report','خطاب رسمي':'letter','محضر اجتماع':'meeting'}[choice])
            index=len(self.document.pages);self.document.import_bytes(name+'.pdf',data)
            self.refresh(index);self.statusBar().showMessage(f'أُدرج القالب: {name}',10000)
        except Exception as exc:self.error(exc)

    def add_text(self):
        if not self.document.pages:
            return
        dialog = TextDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.text.text().strip():
            return
        indexes = list(range(len(self.document.pages))) if dialog.all_pages.isChecked() else self.selected()
        overlay = Overlay(dialog.text.text().strip(), dialog.position.currentData(), dialog.size.value(), dialog.color.currentData(), dialog.opacity.value())
        self.document.add_overlay(indexes, overlay)
        self.refresh(indexes[0])

    def edit_page_content(self):
        if not self.document.pages:
            return
        if self._page_editor is not None:
            self.stack.setCurrentWidget(self._page_editor)
            return
        index = max(0, self.pages.currentRow())
        try:
            data=self.document_job('تجهيز الصفحة للتحرير','assemble',{'indexes':[index],'preview_context':(index+1,len(self.document.pages))})['data']
            editor = PageEditorDialog(data, self, embedded=True)
            self._page_editor=editor;self._editing_page=index
            self.stack.addWidget(editor);self.stack.setCurrentWidget(editor)
            editor.accepted.connect(self.finish_inline_edit)
            editor.rejected.connect(self.cancel_inline_edit)
            self.edit_button.setText('جارٍ التحرير')
            self.statusBar().showMessage('وضع التحرير المباشر: اختر النص أو الصورة من الصفحة، ثم عدّل الخصائص من اللوحة اليمنى.')
        except JobCancelled:pass
        except Exception as exc:
            self.error(exc)

    def finish_inline_edit(self):
        editor=self._page_editor
        if editor is None:return
        index=self._editing_page;changed=editor.data!=editor.initial_data
        self.stack.setCurrentWidget(self.splitter);self.stack.removeWidget(editor)
        editor.deleteLater();self._page_editor=None;self._editing_page=-1;self.edit_button.setText('تعديل PDF')
        if changed:self.document.replace_page(index,editor.data)
        self.refresh(index)
        self.statusBar().showMessage('طُبّقت تعديلات الصفحة. اختر «حفظ نسخة» لحفظ المستند المعدّل.',12000)

    def cancel_inline_edit(self):
        editor=self._page_editor
        if editor is None:return
        index=self._editing_page;self.stack.setCurrentWidget(self.splitter);self.stack.removeWidget(editor)
        editor.deleteLater();self._page_editor=None;self._editing_page=-1;self.edit_button.setText('تعديل PDF')
        self.refresh(max(0,index));self.statusBar().showMessage('أُلغيت تعديلات الصفحة.',8000)

    def add_numbers(self):
        if self.document.pages:
            self.document.add_overlay(list(range(len(self.document.pages))), Overlay("", "bottom", 12, "#566b79", 1, True))
            self.refresh(self.pages.currentRow())

    def clear_text(self):
        indexes = self.selected()
        if indexes:
            self.document.clear_overlays(indexes)
            self.refresh(indexes[0])

    def edit_metadata(self):
        if not self.document.pages:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("خصائص المستند")
        dialog.setMinimumWidth(430)
        form = QFormLayout(dialog)
        title = QLineEdit(self.document.metadata.get("/Title", ""))
        author = QLineEdit(self.document.metadata.get("/Author", ""))
        form.addRow("العنوان", title)
        form.addRow("المؤلف", author)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.document.set_metadata(title.text(), author.text())
            self.update_status()

    def assembled_bytes(self, title='تجهيز المستند'):
        """Build the current workspace through the cancellable worker."""
        return self.document_job(title, 'assemble', {})['data']

    def fill_pdf_form(self):
        if not self.document.pages:return
        try:
            data=self.assembled_bytes('قراءة حقول النموذج')
            fields=list_form_fields(data)
            if not fields:
                QMessageBox.information(self,'حقول النموذج','لا يحتوي المستند على حقول نموذج PDF قياسية قابلة للتعبئة.')
                return
            supported=[field for field in fields if field.kind in ('/Tx','/Ch','/Btn')]
            lines=[]
            for field in supported:
                value=field.value
                if value in ('/Off','None'):value=''
                lines.append(f'{field.name}={value}')
            text,ok=QInputDialog.getMultiLineText(
                self,'تعبئة نموذج PDF',
                'عدّل القيمة بعد علامة = لكل حقل. لمربعات الاختيار استخدم Yes أو Off.\n'
                'لا تغيّر اسم الحقل قبل علامة =:', '\n'.join(lines))
            if not ok:return
            values={}
            for number,line in enumerate(text.splitlines(),1):
                if not line.strip():continue
                if '=' not in line:raise ValueError(f'السطر {number} لا يحتوي على علامة =.')
                name,value=line.split('=',1);name=name.strip()
                if not name:raise ValueError(f'اسم الحقل مفقود في السطر {number}.')
                values[name]=value
            result=fill_form_fields(data,values)
            self.document.replace_document(result,'نموذج معبأ.pdf')
            self.refresh(self.pages.currentRow())
            self.statusBar().showMessage(f'تم تحديث {len(values)} حقلًا. اختر «حفظ نسخة» لحفظ النتيجة.',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def check_signatures(self):
        if not self.document.pages:return
        try:
            signatures=inspect_signatures(self.assembled_bytes('فحص التوقيعات'))
            if not signatures:
                QMessageBox.information(self,'فحص التوقيعات','لا يحتوي المستند على حقول توقيع رقمي.')
                return
            rows=[]
            for index,signature in enumerate(signatures,1):
                state='توجد بيانات توقيع' if signature.has_cryptographic_value else 'حقل توقيع فارغ'
                rows.append(f'{index}. {signature.name} — {state}\nالموقّع: {signature.signer or "غير مذكور"}\nالسبب: {signature.reason or "غير مذكور"}')
            QMessageBox.information(self,'فحص التوقيعات','\n\n'.join(rows)+'\n\nملاحظة: يعرض ورقة بيانات التوقيع المضمنة، ولا يمنح شهادة ثقة قانونية دون سلسلة شهادات موثوقة.')
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def export_text_file(self):
        if not self.document.pages:return
        path,_=QFileDialog.getSaveFileName(self,'تصدير نص المستند',str(Path(self.default_name('text')).with_suffix('.txt')),'Text (*.txt)')
        if not path:return
        if not path.lower().endswith('.txt'):path+='.txt'
        try:
            text=extract_text(self.assembled_bytes('استخراج النص'))
            atomic_write(path,('\ufeff'+text).encode('utf-8'))
            self.statusBar().showMessage(f'تم تصدير النص: {path}',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def export_page_images_dialog(self):
        if not self.document.pages:return
        folder=QFileDialog.getExistingDirectory(self,'اختيار مجلد صور الصفحات')
        if not folder:return
        dpi,ok=QInputDialog.getInt(self,'دقة الصور','الدقة بالنقطة لكل بوصة (DPI):',150,72,600,25)
        if not ok:return
        try:
            paths=export_page_images(self.assembled_bytes('تجهيز صور الصفحات'),folder,dpi=dpi)
            QMessageBox.information(self,'اكتمل التصدير',f'تم إنشاء {len(paths)} صورة PNG في:\n{folder}')
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def export_office_dialog(self):
        if not self.document.pages:return
        labels=['Word (.docx)','Excel (.xlsx)','PowerPoint (.pptx)'];kinds=['docx','xlsx','pptx']
        label,ok=QInputDialog.getItem(self,'تصدير إلى Office','اختر صيغة التصدير:',labels,0,False)
        if not ok:return
        kind=kinds[labels.index(label)];suffix='.'+kind
        path,_=QFileDialog.getSaveFileName(self,'حفظ ملف Office',str(Path(self.default_name('export')).with_suffix(suffix)),f'{label} (*{suffix})')
        if not path:return
        if not path.lower().endswith(suffix):path+=suffix
        try:
            data=self.assembled_bytes('تجهيز المستند للتصدير')
            def operation(report,cancelled):
                return export_pdf_office(data,path,kind,lambda:(report(0,0,'جاري التصدير بواسطة Microsoft Office…') and not cancelled()))
            result=run_task(self,'تصدير إلى '+label,operation)
            self.statusBar().showMessage(f'تم التصدير: {result}',15000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def choose_attachment(self,title):
        data=self.assembled_bytes('قراءة مرفقات المستند');items=list_attachments(data)
        if not items:
            QMessageBox.information(self,'مرفقات PDF','لا يحتوي المستند على مرفقات.');return data,None
        labels=[f'{item.name} — {item.size:,} بايت' for item in items]
        label,ok=QInputDialog.getItem(self,title,'اختر المرفق:',labels,0,False)
        return data,(items[labels.index(label)].name if ok else None)

    def add_pdf_attachment(self):
        if not self.document.pages:return
        path,_=QFileDialog.getOpenFileName(self,'اختيار ملف لإرفاقه')
        if not path:return
        try:
            source=Path(path)
            result=add_attachment(self.assembled_bytes('إضافة المرفق'),source.name,source.read_bytes())
            self.document.replace_document(result,'مستند بمرفقات.pdf');self.refresh(self.pages.currentRow())
            self.statusBar().showMessage(f'تم إرفاق {source.name}. اختر «حفظ نسخة» لحفظ النتيجة.',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def extract_pdf_attachment(self):
        if not self.document.pages:return
        try:
            data,name=self.choose_attachment('استخراج مرفق')
            if not name:return
            path,_=QFileDialog.getSaveFileName(self,'حفظ المرفق',str(Path.home()/'Documents'/name))
            if not path:return
            atomic_write(path,attachment_bytes(data,name));self.statusBar().showMessage(f'تم استخراج المرفق: {path}',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def remove_pdf_attachment(self):
        if not self.document.pages:return
        try:
            data,name=self.choose_attachment('حذف مرفق')
            if not name:return
            if QMessageBox.question(self,'حذف المرفق',f'حذف المرفق «{name}» من النسخة الحالية؟',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            result=remove_attachment(data,name);self.document.replace_document(result,'مستند بدون المرفق.pdf');self.refresh(self.pages.currentRow())
            self.statusBar().showMessage('تم حذف المرفق. اختر «حفظ نسخة» لحفظ النتيجة.',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def compare_with_pdf(self):
        if not self.document.pages:return
        path,_=QFileDialog.getOpenFileName(self,'اختيار نسخة PDF للمقارنة','','PDF (*.pdf)')
        if not path:return
        try:
            first=self.assembled_bytes('تجهيز النسخة الحالية للمقارنة');second=Path(path).read_bytes()
            results=run_task(self,'مقارنة المستندين',lambda report,cancelled:compare_pdfs(first,second,progress=report))
            dialog=QDialog(self);dialog.setWindowTitle('نتيجة مقارنة المستندين');dialog.resize(620,520)
            layout=QVBoxLayout(dialog);changed=[item for item in results if item.status!='same']
            summary=QLabel(f'عدد الصفحات: {len(results)}  •  الصفحات المختلفة: {len(changed)}');summary.setWordWrap(True);layout.addWidget(summary)
            items=QListWidget();labels={'same':'متطابقة','changed':'معدّلة','added':'مضافة في النسخة الأخرى','removed':'محذوفة من النسخة الأخرى'}
            for item in results:
                items.addItem(f'صفحة {item.page}: {labels[item.status]}  •  تشابه النص {item.text_similarity*100:.1f}%  •  اختلاف بصري {item.visual_difference*100:.2f}%')
            layout.addWidget(items);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);buttons.accepted.connect(dialog.accept);layout.addWidget(buttons);dialog.exec()
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def edit_bookmark(self):
        index=self.pages.currentRow()
        if index<0:return
        current=self.document.pages[index].bookmark
        title,ok=QInputDialog.getText(self,'إشارة مرجعية',f'عنوان الإشارة للصفحة {index+1}:',text=current)
        if ok and title.strip():
            self.document.set_bookmark(index,title);self.refresh(index);self.statusBar().showMessage('تم تحديث الإشارة المرجعية.',8000)

    def clear_bookmark(self):
        index=self.pages.currentRow()
        if index>=0 and self.document.pages[index].bookmark:
            self.document.set_bookmark(index,'');self.refresh(index);self.statusBar().showMessage('تم حذف الإشارة المرجعية.',8000)

    def scan_page(self):
        try:
            image=acquire_wia_image();data=image_bytes_to_pdf(image);index=len(self.document.pages)
            self.document.import_bytes('صفحة ممسوحة ضوئيًا.pdf',data);self.refresh(index)
            self.statusBar().showMessage('تمت إضافة الصفحة الممسوحة. يمكنك تشغيل OCR لجعل نصها قابلًا للبحث.',12000)
        except ConversionCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def preflight_document(self):
        if not self.document.pages:return
        try:
            report=preflight_pdf(self.assembled_bytes('فحص المستند قبل النشر'))
            dialog=QDialog(self);dialog.setWindowTitle('فحص المستند قبل النشر');dialog.resize(650,520)
            layout=QVBoxLayout(dialog)
            summary=QLabel(f'PDF {report.version}  •  {report.pages} صفحة  •  {report.fields} حقل نموذج  •  {report.attachments} مرفق')
            summary.setWordWrap(True);layout.addWidget(summary);items=QListWidget()
            labels={'warning':'تحذير','info':'معلومة','error':'خطأ'}
            if report.issues:
                for issue in report.issues:items.addItem(f'{labels.get(issue.severity,issue.severity)} — {issue.message}')
            else:items.addItem('لم يكتشف الفحص مشكلات أساسية.')
            layout.addWidget(items);note=QLabel('هذا فحص بنيوي مساعد، وليس شهادة اعتماد PDF/A أو PDF/UA.');note.setWordWrap(True);layout.addWidget(note)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);buttons.accepted.connect(dialog.accept);layout.addWidget(buttons);dialog.exec()
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def sanitize_document(self):
        if not self.document.pages:return
        if QMessageBox.warning(self,'تنظيف البيانات الخفية','سيزيل ورقة البيانات الوصفية والمرفقات وJavaScript وإجراءات الفتح من النسخة الحالية. احتفظ بالأصل. هل تريد المتابعة؟',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:
            result=sanitize_pdf(self.assembled_bytes('تنظيف البيانات الخفية'))
            self.document.replace_document(result,'مستند منظف.pdf');self.refresh(self.pages.currentRow())
            self.statusBar().showMessage('تم تنظيف البيانات الخفية. اختر «حفظ نسخة» لحفظ النتيجة.',12000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def redact_text_everywhere(self):
        if not self.document.pages:return
        query,ok=QInputDialog.getText(self,'تنقيح نص في جميع الصفحات','النص الحساس المطلوب حذفه نهائيًا:')
        if not ok or not query.strip():return
        if QMessageBox.warning(self,'تنقيح دفعي آمن','ستتحول كل صفحة تحتوي النص إلى صورة ثابتة مع حذف مواضع النص نهائيًا. لن تبقى النصوص في تلك الصفحات قابلة للتحرير. هل تريد المتابعة؟',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:
            data=self.assembled_bytes('تجهيز التنقيح الدفعي')
            result,count=run_task(self,'تنقيح النص',lambda report,cancelled:secure_redact_text(data,query,dpi=200,progress=report))
            self.document.replace_document(result,'مستند منقح.pdf');self.refresh(self.pages.currentRow())
            self.statusBar().showMessage(f'تم تنقيح {count} موضعًا. اختر «حفظ نسخة» لحفظ النتيجة.',15000)
        except JobCancelled:pass
        except Exception as exc:self.error(exc,exc)

    def default_name(self, suffix="edited"):
        if self.last_output:
            return str(self.last_output if suffix == "edited" else self.last_output.with_name(self.last_output.stem + "-" + suffix + ".pdf"))
        if self.document.pages:
            source = self.document.sources[self.document.pages[0].source]
            if source.path:
                return str(source.path.with_name(f"{source.path.stem}-{suffix}.pdf"))
        return str(Path.home() / "Documents" / f"Waraq-{suffix}.pdf")

    def save_document(self, *_):
        if not self.document.pages:
            return False
        return self.export(None)

    def print_document(self):
        if not self.document.pages:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        printer.setDocName(self.document_name.text())
        printer.setFromTo(1, len(self.document.pages))
        dialog = QPrintDialog(printer, self)
        dialog.setMinMax(1, len(self.document.pages))
        dialog.setOption(QAbstractPrintDialog.PrintDialogOption.PrintPageRange, True)
        dialog.setOption(QAbstractPrintDialog.PrintDialogOption.PrintSelection, True)
        dialog.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options=PrintOptionsDialog(self)
        if options.exec()!=QDialog.DialogCode.Accepted:return
        progress = QProgressDialog("جاري تجهيز الطباعة…", "إلغاء", 0, len(self.document.pages), self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        def tick(done, total):
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()
        try:
            with self.busy("جاري تجهيز الصفحات للطباعة…"):
                data=self.document_job('تجهيز الطباعة','assemble',{})['data']
                indexes = requested_pages(printer, len(self.document.pages), self.pages.currentRow(), self.selected())
                count = paint_pdf(printer, data, indexes, tick,pages_per_sheet=options.nup.currentData(),grayscale=options.grayscale.isChecked())
            self.statusBar().showMessage(f"تم إرسال {count} صفحة إلى الطابعة.", 12000)
        except (PrintCancelled,JobCancelled):
            self.statusBar().showMessage("تم إلغاء الطباعة. قد تكون الصفحات التي أُرسلت بالفعل في قائمة انتظار الطابعة.", 15000)
        except Exception as exc:
            self.error(exc)
        finally:
            progress.close()

    def print_preview(self):
        if not self.document.pages:
            return
        try:
            data=self.document_job('تجهيز معاينة الطباعة','assemble',{})['data']
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setResolution(150)
            printer.setDocName(self.document_name.text())
            dialog = QPrintPreviewDialog(printer, self)
            dialog.setWindowTitle("معاينة الطباعة — ورقة")
            dialog.resize(1000, 760)
            def paint(target):
                try:
                    paint_pdf(target, data, list(range(len(self.document.pages))))
                except Exception as exc:
                    self.error(exc)
            dialog.paintRequested.connect(paint)
            dialog.exec()
        except JobCancelled:pass
        except Exception as exc:
            self.error(exc)

    def export(self, indexes=None):
        chosen = range(len(self.document.pages)) if indexes is None else indexes
        encrypted = any(self.document.sources[self.document.pages[i].source].reader.is_encrypted for i in chosen)
        options = SaveDialog(self, "استخراج صفحات" if indexes is not None else "حفظ نسخة PDF", encrypted)
        if options.exec() != QDialog.DialogCode.Accepted:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "حفظ PDF", self.default_name("pages" if indexes is not None else "edited"), "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
            if Path(path).exists():
                result = QMessageBox.question(self, "استبدال ملف موجود؟", f"الملف موجود بالفعل:\n{path}\nهل تريد استبداله؟", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if result != QMessageBox.StandardButton.Yes:
                    return False
        try:
            self.write_pdf_background(path,indexes,options.security_options())
            if indexes is None:
                self.document.mark_saved()
                self.last_output = Path(path)
                self.update_status()
            self.statusBar().showMessage(f"تم الحفظ: {path}", 12000)
            return True
        except JobCancelled:return False
        except Exception as exc:
            self.error(f"لم يتم حفظ النسخة.\n{exc}", exc)
            return False

    def extract_pages(self):
        if not self.document.pages:
            return
        default = ", ".join(str(i + 1) for i in self.selected())
        expression, ok = QInputDialog.getText(self, "استخراج صفحات", f"الصفحات المطلوبة من 1 إلى {len(self.document.pages)}\nمثال: 1-3, 5, 8", text=default)
        if ok:
            try:
                self.export(parse_pages(expression, len(self.document.pages)))
            except ValueError as exc:
                self.error(exc)

    def split_document(self):
        if not self.document.pages:
            return
        size, ok = QInputDialog.getInt(self, "تقسيم المستند", "عدد الصفحات في كل ملف جديد:", 1, 1, len(self.document.pages))
        if not ok:
            return
        encrypted = any(self.document.sources[p.source].reader.is_encrypted for p in self.document.pages)
        options = SaveDialog(self, "حماية ملفات التقسيم", encrypted)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(self, "اختيار مجلد الملفات الناتجة")
        if not folder:
            return
        written = []
        try:
            with self.busy("جاري تقسيم المستند…"):
                for start in range(0, len(self.document.pages), size):
                    end = min(start + size, len(self.document.pages))
                    base = f"Waraq-pages-{start + 1:03d}-{end:03d}"
                    path = Path(folder) / (base + ".pdf")
                    suffix = 2
                    while path.exists():
                        path = Path(folder) / f"{base}-{suffix}.pdf"
                        suffix += 1
                    self.write_pdf_background(path,list(range(start,end)),options.security_options())
                    written.append(path)
            QMessageBox.information(self, "اكتمل التقسيم", f"تم إنشاء {len(written)} ملف PDF في:\n{folder}")
        except JobCancelled:self.statusBar().showMessage(f'أُلغي التقسيم بعد إنشاء {len(written)} ملف مكتمل.',12000)
        except Exception as exc:
            self.error(f"توقف التقسيم بعد إنشاء {len(written)} ملف.\n{exc}", exc)

    def about(self):
        QMessageBox.about(self, "عن ورقة", f"<h2>ورقة · {__version__}</h2><p>تطبيق مستقل مفتوح المصدر لإدارة ملفات PDF محليًا.</p><p>كود التطبيق بترخيص MIT. المكتبات وبيانات OCR المرفقة لها تراخيصها الخاصة؛ راجع THIRD_PARTY_NOTICES وملفات التراخيص.</p><p>يدعم التحرير على مستوى الكلمات والفقرات، وOCR عربي/إنجليزي عبر Tesseract محلي، والبحث والنسخ، ومشروعات الاستعادة، وأدوات المراجعة. لا يوفر توقيعًا رقميًا معتمدًا أو إعادة تنسيق المستند مثل برنامج Word.</p><p>ليس تابعًا لـ Adobe، ولا يستخدم كود Acrobat أو أدوات تفعيله.</p>")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths, append=bool(self.document.pages))
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self._page_editor is not None:
            self._page_editor.finish()
            if self._page_editor is not None:
                event.ignore();return
        if self.confirm_discard():
            self.autosave_timer.stop();self.clear_recovery()
            self.thumb_timer.stop()
            self.preview_timer.stop()
            self.close_pdfs()
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    ensure_font_support()
    from .fonts import load_user_fonts
    load_user_fonts()
    app.setApplicationName("ورقة")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Waraqa")
    app.setStyle("Fusion")
    from .logging_setup import configure_logging
    configure_logging()
    app.setStyleSheet(STYLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    window = MainWindow()
    window.show()
    arguments = [p for p in sys.argv[1:] if not p.startswith('--') and Path(p).suffix.lower() in SUPPORTED_TYPES]
    if arguments:
        def open_arguments():
            window.import_paths(arguments)
            if '--print' in sys.argv and window.document.pages:
                window.print_document()
        QTimer.singleShot(0, open_arguments)
    else:
        project=next((p for p in sys.argv[1:] if Path(p).suffix.lower()=='.waraq'),None)
        if project:QTimer.singleShot(0,lambda:window.open_project(project))
        else:QTimer.singleShot(500,window.offer_recovery)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
