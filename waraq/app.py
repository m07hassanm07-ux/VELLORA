from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import math
import sys
import traceback

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QItemSelectionModel, QRect
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStatusBar,
    QToolBar, QVBoxLayout, QWidget, QStyledItemDelegate, QStyle,
)
import pypdfium2 as pdfium
from pypdf import PdfWriter

from . import __version__
from .core import Document, Overlay, PasswordRequired, atomic_write, parse_pages
from .rendering import render_image, text_overlay, ensure_font_support


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
        for field in (self.password, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setEnabled(False)
        self.protect.toggled.connect(self.password.setEnabled)
        self.protect.toggled.connect(self.confirm.setEnabled)
        self.protect.setChecked(protected_input)
        form = QFormLayout()
        form.addRow(self.protect)
        form.addRow("كلمة المرور", self.password)
        form.addRow("تأكيد الكلمة", self.confirm)
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
        self.resize(1320, 850)
        self.setMinimumSize(980, 650)
        self.setWindowTitle("ورّاق PDF | Waraq PDF")
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
        self.refresh()

    def brand_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#157b67"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 64, 64, 14, 14)
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "و")
        painter.end()
        return QIcon(pixmap)

    def make_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame(objectName="header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        brand = QLabel("ورّاق PDF", objectName="brand")
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
        self.save_button = self.button("حفظ نسخة", self.save_document, primary=True)
        header_layout.addWidget(self.save_button)
        layout.addWidget(header)

        tools = QFrame(objectName="tools")
        tool_layout = QHBoxLayout(tools)
        tool_layout.setContentsMargins(18, 10, 18, 10)
        for key, title, handler in [
            ("add", "إضافة / دمج", self.add_dialog),
            ("extract", "استخراج صفحات", self.extract_pages),
            ("split", "تقسيم", self.split_document),
            ("text", "نص / علامة مائية", self.add_text),
            ("number", "ترقيم الصفحات", self.add_numbers),
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
        version = QLabel(f"Waraq PDF  {__version__}")
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
        layout.addWidget(bar)
        self.preview = PreviewArea()
        self.preview.setWidgetResizable(True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.resized.connect(lambda: self.preview_timer.start(140) if self.fit_mode else None)
        self.preview_surface = QWidget(objectName="previewSurface")
        preview_layout = QVBoxLayout(self.preview_surface)
        preview_layout.setContentsMargins(30, 26, 30, 26)
        preview_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.image_label = QLabel(objectName="pageImage")
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
        help_menu = menu.addMenu("مساعدة")
        for parent, key, title, shortcut, handler in [
            (files, "open", "فتح مستند…", "Ctrl+O", self.open_dialog),
            (files, "add", "إضافة ملفات…", "Ctrl+Shift+O", self.add_dialog),
            (files, "save", "حفظ نسخة…", "Ctrl+S", self.save_document),
            (files, "extract", "استخراج صفحات…", "Ctrl+E", self.extract_pages),
            (files, "blank", "إضافة صفحة فارغة", "Ctrl+N", self.add_blank),
            (files, "metadata", "خصائص المستند…", "", self.edit_metadata),
            (files, "close", "إغلاق مساحة العمل", "Ctrl+W", self.new_workspace),
            (edits, "undo", "تراجع", "Ctrl+Z", self.undo),
            (edits, "redo", "إعادة", "Ctrl+Shift+Z", self.redo),
            (edits, "select", "تحديد الكل", "Ctrl+A", self.pages.selectAll),
            (edits, "rotate", "تدوير الصفحات المحددة", "Ctrl+R", lambda: self.rotate(90)),
            (edits, "delete", "حذف الصفحات المحددة", "Delete", self.delete_pages),
            (edits, "cleartext", "إزالة النصوص المضافة من المحدد", "", self.clear_text),
            (view, "fit", "ملاءمة العرض", "Ctrl+0", self.fit_page),
            (view, "zoom", "الحجم الطبيعي", "Ctrl+1", self.actual_size),
            (help_menu, "about", "عن ورّاق PDF…", "", self.about),
        ]:
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            parent.addAction(action)
            self.actions[key] = action

    def error(self, message, exception=None):
        if exception is not None:
            traceback.print_exception(exception)
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
        for pdf in self.pdfs.values():
            pdf.close()
        self.pdfs.clear()
        self.thumbnail_cache.clear()

    def new_workspace(self):
        if not self.confirm_discard():
            return
        self.close_pdfs()
        self.document = Document()
        self.last_output = None
        self.refresh()

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "فتح مستندات PDF", "", "PDF (*.pdf)")
        if paths:
            self.import_paths(paths, append=False)

    def add_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "إضافة ملفات إلى المستند", "", "PDF (*.pdf)")
        if paths:
            self.import_paths(paths, append=True)

    def import_paths(self, paths, append=False):
        paths = [str(p) for p in paths if str(p).lower().endswith(".pdf")]
        if not paths:
            self.error("اختر ملفات بصيغة PDF.")
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
                    with self.busy("جاري قراءة الملف…"):
                        source_id = target.import_pdf(path, password)
                    signed |= target.sources[source_id].signed
                    imported += 1
                    break
                except PasswordRequired:
                    password, ok = QInputDialog.getText(self, "ملف محمي", f"كلمة مرور {Path(path).name}", QLineEdit.EchoMode.Password)
                    if not ok:
                        break
                except Exception as exc:
                    failures.append(f"{Path(path).name}: {exc}")
                    break
        if imported:
            if not append:
                self.close_pdfs()
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
        self.rebuilding = True
        self.thumb_timer.stop()
        self.pages.clear()
        for index, page in enumerate(self.document.pages):
            name = self.document.sources[page.source].name
            item = QListWidgetItem(f"صفحة {index + 1}\n{name[:25]}")
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
        self.setWindowTitle(f"{'● ' if self.document.dirty else ''}{title} — ورّاق PDF")
        self.save_button.setEnabled(bool(count))
        for key, button in self.buttons.items():
            button.setEnabled(bool(count) or key == "add")
        self.undo_button.setEnabled(self.document.can_undo)
        self.redo_button.setEnabled(self.document.can_redo)
        for key, action in self.actions.items():
            if key == "undo":
                action.setEnabled(self.document.can_undo)
            elif key == "redo":
                action.setEnabled(self.document.can_redo)
            elif key not in ("open", "add", "blank", "about", "close"):
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
        if not self.thumb_queue:
            self.thumb_timer.stop()
            return
        index = self.thumb_queue.pop(0)
        if index >= len(self.document.pages):
            return
        page = self.document.pages[index]
        key = (page.uid, page.rotation, page.overlays, index if any(o.numbering for o in page.overlays) else -1, len(self.document.pages))
        try:
            if key not in self.thumbnail_cache:
                pdf_page = self.pdf_for(page.source)[page.index]
                try:
                    width, height = pdf_page.get_size()
                finally:
                    pdf_page.close()
                if page.rotation in (90, 270):
                    width, height = height, width
                scale = min(128 / max(width, 1), 166 / max(height, 1))
                self.thumbnail_cache[key] = QIcon(QPixmap.fromImage(self.page_image(index, scale)))
                if len(self.thumbnail_cache) > 350:
                    self.thumbnail_cache.pop(next(iter(self.thumbnail_cache)))
            item = self.pages.item(index)
            if item:
                item.setIcon(self.thumbnail_cache[key])
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
            pdf_page = self.pdf_for(page.source)[page.index]
            try:
                width, height = pdf_page.get_size()
            finally:
                pdf_page.close()
            if page.rotation in (90, 270):
                width, height = height, width
            scale = self.zoom * 96 / 72
            if self.fit_mode:
                scale = max(0.1, (self.preview.viewport().width() - 72) / max(width, 1))
                self.zoom = scale * 72 / 96
            # Cap render allocation while retaining document quality in saved files.
            scale = min(scale, 2600 / max(width, height, 1))
            image = self.page_image(index, scale)
            pixmap = QPixmap.fromImage(image)
            self.image_label.setPixmap(pixmap)
            self.image_label.setFixedSize(pixmap.size())
            self.zoom_label.setText(f"{round(self.zoom * 100)}%")
            self.page_number.blockSignals(True)
            self.page_number.setValue(index + 1)
            self.page_number.blockSignals(False)
            self.update_status()
        except Exception as exc:
            self.image_label.clear()
            self.image_label.setText("تعذر عرض هذه الصفحة")
            self.status_label.setText(f"تعذر عرض الصفحة: {exc}")

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
            with self.busy("جاري إنشاء النسخة…"):
                self.document.save(path, indexes=indexes, password=options.output_password(), overlay_renderer=text_overlay)
            if indexes is None:
                self.document.mark_saved()
                self.last_output = Path(path)
                self.update_status()
            self.statusBar().showMessage(f"تم الحفظ: {path}", 12000)
            return True
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
                    self.document.save(path, indexes=list(range(start, end)), password=options.output_password(), overlay_renderer=text_overlay)
                    written.append(path)
            QMessageBox.information(self, "اكتمل التقسيم", f"تم إنشاء {len(written)} ملف PDF في:\n{folder}")
        except Exception as exc:
            self.error(f"توقف التقسيم بعد إنشاء {len(written)} ملف.\n{exc}", exc)

    def about(self):
        QMessageBox.about(self, "عن ورّاق PDF", f"<h2>ورّاق PDF · {__version__}</h2><p>تطبيق مستقل مفتوح المصدر لإدارة ملفات PDF محليًا.</p><p>كود التطبيق بترخيص MIT. المكتبات المرفقة لها تراخيصها الخاصة؛ راجع THIRD_PARTY_NOTICES وملفات التراخيص.</p><p>يدعم العرض وتنظيم الصفحات والدمج والتقسيم وإضافة النصوص. لا يدعم تعديل النص الأصلي أو OCR أو التوقيع الرقمي المعتمد في هذه النسخة.</p><p>ليس تابعًا لـ Adobe، ولا يستخدم كود Acrobat أو أدوات تفعيله.</p>")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths, append=bool(self.document.pages))
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.confirm_discard():
            self.thumb_timer.stop()
            self.preview_timer.stop()
            self.close_pdfs()
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    ensure_font_support()
    app.setApplicationName("Waraq PDF")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Waraq PDF")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    window = MainWindow()
    window.show()
    arguments = [p for p in sys.argv[1:] if p.lower().endswith(".pdf")]
    if arguments:
        QTimer.singleShot(0, lambda: window.import_paths(arguments))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
