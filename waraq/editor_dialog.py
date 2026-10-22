"""A page editor with explicit selection, draft preview and transactional apply."""
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from .editing import edit_page, inspect_page, prepare_page
from .rendering import render_image


class EditCanvas(QGraphicsView):
    region_selected = Signal(QRectF)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor('#dfe8ed'))
        self.setMinimumWidth(350)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = None
        self.selection = None

    def set_page(self, data):
        with pdfium.PdfDocument(data) as pdf:
            page = pdf[0]
            try:
                width, height = page.get_size()
            finally:
                page.close()
            scale = min(1.5, 1500/max(width, height))
            image = render_image(pdf, 0, scale)
        self.scene().clear(); self.selection = None
        item = self.scene().addPixmap(QPixmap.fromImage(image)); item.setScale(1/scale)
        self.scene().setSceneRect(0, 0, width, height)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def highlight(self, rect):
        if self.selection is not None:
            self.scene().removeItem(self.selection)
            self.selection = None
        if rect and not rect.isEmpty():
            pen = QPen(QColor('#0e846c'), 0); pen.setStyle(Qt.PenStyle.DashLine)
            self.selection = self.scene().addRect(rect, pen, QColor(19, 151, 120, 35))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = self.mapToScene(event.position().toPoint())
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start is not None:
            rect = QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized().intersected(self.sceneRect())
            self.highlight(rect); event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized().intersected(self.sceneRect())
            self.start = None
            self.region_selected.emit(rect); event.accept(); return
        super().mouseReleaseEvent(event)


class PageEditorDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle('تعديل محتوى الصفحة — ورّاق PDF')
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1180, 820)
        self.data = prepare_page(data)
        self.initial_data = self.data
        self.history, self.future = [], []
        self.mode = 'select'
        self.image = None
        self.loading = False
        self.draft = None
        self.pending = False
        layout = QVBoxLayout(self)
        note = QLabel('اسحب حول النص أو اختر عناصر من القائمة، ثم عدّل النص واضغط «تطبيق على الصفحة». يمكنك أيضًا إضافة نص أو صورة في مكان جديد.')
        note.setWordWrap(True); layout.addWidget(note)
        toolbar = QHBoxLayout()
        for label, callback in [('تحديد عنصر', self.select_mode), ('نص جديد', self.new_text), ('إضافة صورة…', self.choose_image)]:
            button = QPushButton(label); button.clicked.connect(callback); toolbar.addWidget(button)
        self.undo_button = QPushButton('تراجع'); self.undo_button.clicked.connect(self.undo); toolbar.addWidget(self.undo_button)
        self.redo_button = QPushButton('إعادة'); self.redo_button.clicked.connect(self.redo); toolbar.addWidget(self.redo_button)
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = EditCanvas(); self.canvas.region_selected.connect(self.pick_region)
        panel = QWidget(); panel.setMaximumWidth(405); panel.setMinimumWidth(320)
        controls = QVBoxLayout(panel)
        self.status = QLabel(); self.status.setWordWrap(True); controls.addWidget(self.status)
        self.objects = QListWidget(); self.objects.setMaximumHeight(135)
        self.objects.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.objects.itemSelectionChanged.connect(self.object_selected); controls.addWidget(self.objects)
        self.text = QPlainTextEdit(); self.text.setPlaceholderText('اكتب النص الجديد هنا…')
        self.text.setMaximumHeight(125); self.text.textChanged.connect(self.mark_pending)
        controls.addWidget(self.text)
        form = QFormLayout()
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont('Segoe UI'))
        self.font.currentFontChanged.connect(self.mark_pending); form.addRow('الخط', self.font)
        self.size = QSpinBox(); self.size.setRange(4, 200); self.size.setValue(16)
        self.size.valueChanged.connect(self.mark_pending); form.addRow('حجم الخط', self.size)
        self.bold = QCheckBox('خط عريض'); self.bold.toggled.connect(self.mark_pending); form.addRow('', self.bold)
        self.color = QComboBox()
        for label, value in [('أسود', '#172a32'), ('أزرق', '#174b91'), ('أخضر', '#087a63'), ('أحمر', '#b62432')]:
            self.color.addItem(label, value)
        self.color.currentIndexChanged.connect(self.mark_pending); form.addRow('اللون', self.color)
        self.geometry = []
        for label, default in [('من اليسار %', 10), ('من أعلى %', 10), ('العرض %', 70), ('الارتفاع %', 12)]:
            spin = QDoubleSpinBox(); spin.setRange(0, 100); spin.setDecimals(2); spin.setValue(default)
            spin.valueChanged.connect(self.geometry_changed); self.geometry.append(spin); form.addRow(label, spin)
        controls.addLayout(form)
        preview = QPushButton('معاينة التعديل'); preview.clicked.connect(self.preview_change); controls.addWidget(preview)
        self.apply_button = QPushButton('تطبيق على الصفحة'); self.apply_button.clicked.connect(self.apply_change); controls.addWidget(self.apply_button)
        self.delete_button = QPushButton('حذف المحدد'); self.delete_button.clicked.connect(self.delete_selected); controls.addWidget(self.delete_button)
        controls.addStretch()
        hint = QLabel('استبدال النص يستخدم الخط الذي تختاره. بعض الملفات تقسّم الكلمة إلى عناصر؛ استخدم التحديد بالسحب أو Ctrl/Shift لتحديد أكثر من عنصر. الصور الممسوحة تحتاج OCR لتغيير نصها.')
        hint.setWordWrap(True); controls.addWidget(hint)
        splitter.addWidget(panel); splitter.addWidget(self.canvas); splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('إنهاء التعديل')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('إلغاء جميع تعديلات الصفحة')
        buttons.accepted.connect(self.finish); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.reload()

    def reload(self):
        self.loading = True
        self.width, self.height, self.entries = inspect_page(self.data)
        self.objects.clear()
        for entry in self.entries:
            label = ('نص: ' + (entry.text.replace('\n', ' ')[:90] or 'نص غير قابل للاستخراج')) if entry.kind == 'text' else 'صورة'
            item = QListWidgetItem(label); item.setToolTip(entry.text); self.objects.addItem(item)
        self.loading = False
        self.mode = 'select'; self.image = None; self.text.clear(); self.draft = None
        self.canvas.set_page(self.data)
        self.status.setText(f'{len(self.entries)} عنصرًا نصيًا أو صورة قابلًا للتحديد' if self.entries else 'لا توجد نصوص أو صور مستقلة قابلة للتعديل. يمكنك إضافة نص أو صورة؛ النص داخل المسح الضوئي يحتاج OCR.')
        self.delete_button.setEnabled(False)
        self.undo_button.setEnabled(bool(self.history)); self.redo_button.setEnabled(bool(self.future))
        self.pending = False

    def selected_entries(self):
        return [self.entries[self.objects.row(item)] for item in self.objects.selectedItems()]

    def selected_indexes(self):
        return [entry.index for entry in self.selected_entries()]

    def set_rect(self, rect):
        self.loading = True
        values = [rect.x()/self.width*100, rect.y()/self.height*100, rect.width()/self.width*100, rect.height()/self.height*100]
        for spin, value in zip(self.geometry, values):
            spin.setValue(value)
        self.loading = False
        self.canvas.highlight(self.rect())
        self.clear_draft()
        self.pending = True

    def rect(self):
        x, y, w, h = [spin.value() for spin in self.geometry]
        return QRectF(x*self.width/100, y*self.height/100, w*self.width/100, h*self.height/100)

    def geometry_changed(self, *_):
        if not self.loading:
            self.mark_pending(); self.canvas.highlight(self.rect())

    def mark_pending(self, *_):
        if not self.loading:
            self.clear_draft(); self.pending = True

    def clear_draft(self, *_):
        if self.loading:
            return
        if self.draft is not None:
            self.draft = None; self.canvas.set_page(self.data); self.canvas.highlight(self.rect())

    def object_selected(self):
        if self.loading:
            return
        self.clear_draft()
        selected = self.selected_entries()
        self.delete_button.setEnabled(bool(selected))
        if not selected:
            return
        self.mode = 'select'; self.image = None
        bounds = QRectF(*selected[0].rect)
        for entry in selected[1:]:
            bounds = bounds.united(QRectF(*entry.rect))
        text_entries = [entry for entry in selected if entry.kind == 'text']
        self.text.setPlainText(''.join(entry.text for entry in text_entries))
        if text_entries:
            size = max(4, min(200, round(text_entries[0].size)))
            self.size.setValue(size)
            # Glyph bounds exclude font ascenders/line leading; reserve room for
            # a complete newly shaped line. The exact box remains user-editable.
            bounds.setTop(max(0, bounds.top()-size*.25))
            bounds.setHeight(max(bounds.height(), size*1.9))
        bounds = bounds.intersected(QRectF(0, 0, self.width, self.height))
        self.set_rect(bounds)
        self.status.setText(f'تم تحديد {len(selected)} عنصر. الاستبدال أو الحذف يخص العناصر المحددة فقط.')
        self.pending = False

    def select_mode(self):
        self.clear_draft(); self.mode = 'select'; self.image = None
        self.status.setText('انقر عنصرًا، أو اسحب مستطيلًا حول النص لتحديد عدة عناصر.')

    def pick_region(self, rect):
        self.clear_draft()
        if self.mode in ('text', 'image'):
            if rect.width() < 3 or rect.height() < 3:
                current = self.rect(); current.moveTopLeft(rect.topLeft())
                rect = current.intersected(QRectF(0, 0, self.width, self.height))
            self.set_rect(rect); return
        if rect.width() < 3 and rect.height() < 3:
            point = rect.topLeft()
            hits = [i for i, e in enumerate(self.entries) if QRectF(*e.rect).adjusted(-2, -2, 2, 2).contains(point)]
            # Prefer a small text object over a background scan/image.
            hits.sort(key=lambda i: (self.entries[i].kind != 'text', self.entries[i].rect[2]*self.entries[i].rect[3]))
            chosen = hits[:1]
        else:
            chosen = [i for i, e in enumerate(self.entries) if e.kind == 'text' and rect.contains(QRectF(*e.rect).center())]
        self.loading = True; self.objects.clearSelection()
        for index in chosen:
            self.objects.item(index).setSelected(True)
        self.loading = False
        if chosen:
            self.object_selected()
        else:
            self.delete_button.setEnabled(False); self.canvas.highlight(None)
            self.status.setText('لم يقع نص قابل للتعديل داخل التحديد. اختر «نص جديد» لإضافة نص هنا.')

    def new_text(self):
        self.clear_draft(); self.objects.clearSelection(); self.mode = 'text'; self.image = None
        self.text.clear(); self.size.setValue(16)
        self.set_rect(QRectF(self.width*.1, self.height*.1, self.width*.7, self.height*.12))
        self.status.setText('نص جديد: ارسم مكانه على الصفحة، واكتب النص ثم عاين التعديل.')
        self.text.setFocus()

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'إضافة صورة', '', 'صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)')
        if not path:
            return
        reader = QImageReader(path); reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, 'الصورة', 'تعذر قراءة الصورة.'); return
        self.clear_draft(); self.objects.clearSelection(); self.mode = 'image'; self.image = image
        self.set_rect(QRectF(self.width*.1, self.height*.1, self.width*.4, self.height*.3))
        self.status.setText(f'الصورة: {Path(path).name}. ارسم مكانها ثم عاين التعديل؛ ستُحفظ نسبة أبعادها.')

    def make_change(self):
        indexes = self.selected_indexes() if self.mode == 'select' else []
        if self.mode == 'select' and not indexes:
            raise ValueError('حدد نصًا لتعديله، أو اختر «نص جديد» أو «إضافة صورة».')
        if self.mode == 'select' and any(e.kind != 'text' for e in self.selected_entries()):
            raise ValueError('لتغيير الصورة احذفها ثم أضف الصورة الجديدة. استبدال النص يتطلب تحديد نصوص فقط.')
        rect = self.rect()
        return edit_page(self.data, indexes, text=None if self.mode == 'image' else self.text.toPlainText(),
            image=self.image if self.mode == 'image' else None,
            rect=(rect.x(), rect.y(), rect.width(), rect.height()), size=self.size.value(),
            family=self.font.currentFont().family(), color=self.color.currentData(), bold=self.bold.isChecked())

    def preview_change(self):
        try:
            self.draft = self.make_change(); self.canvas.set_page(self.draft)
            self.status.setText('هذه معاينة فقط. اضغط «تطبيق على الصفحة» للاحتفاظ بها داخل المحرر.')
        except Exception as exc:
            QMessageBox.warning(self, 'تعذر التعديل', str(exc))

    def commit(self, data):
        self.history.append(self.data); self.history = self.history[-30:]
        self.future.clear(); self.data = data; self.reload()

    def apply_change(self):
        try:
            self.commit(self.draft if self.draft is not None else self.make_change())
        except Exception as exc:
            QMessageBox.warning(self, 'تعذر التعديل', str(exc))

    def delete_selected(self):
        indexes = self.selected_indexes()
        if indexes:
            try:
                self.commit(edit_page(self.data, indexes))
            except Exception as exc:
                QMessageBox.warning(self, 'تعذر الحذف', str(exc))

    def undo(self):
        if self.history:
            self.future.append(self.data); self.data = self.history.pop(); self.reload()

    def redo(self):
        if self.future:
            self.history.append(self.data); self.data = self.future.pop(); self.reload()

    def finish(self):
        if self.pending or self.draft is not None:
            question = QMessageBox(self)
            question.setWindowTitle('تعديل لم يُطبّق')
            question.setText('يوجد تعديل في أدوات التحرير لم يُطبّق على الصفحة بعد.')
            apply = question.addButton('تطبيق وإنهاء', QMessageBox.ButtonRole.AcceptRole)
            discard = question.addButton('تجاهل هذا التعديل وإنهاء', QMessageBox.ButtonRole.DestructiveRole)
            question.addButton('متابعة التحرير', QMessageBox.ButtonRole.RejectRole)
            question.exec()
            if question.clickedButton() == apply:
                try:
                    self.commit(self.draft if self.draft is not None else self.make_change())
                except Exception as exc:
                    QMessageBox.warning(self, 'تعذر التعديل', str(exc)); return
            elif question.clickedButton() != discard:
                return
        self.accept()
