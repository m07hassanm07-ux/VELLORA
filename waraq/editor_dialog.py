"""A page editor with explicit selection, draft preview and transactional apply."""
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImageReader, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QInputDialog,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from .editing import edit_page, inspect_page, prepare_page, insert_table
from .rendering import render_image, ensure_font_support
from .textlayout import group_text
from .fonts import install_font


class EditCanvas(QGraphicsView):
    region_selected = Signal(QRectF)
    rect_changed = Signal(QRectF)
    text_double_clicked = Signal(QPointF)
    delete_requested = Signal()

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
        self.handles = []
        self.drag_mode = None
        self.drag_origin = None
        self.drag_rect = None
        self.guide_items = []

    def set_page(self, data):
        with pdfium.PdfDocument(data) as pdf:
            page = pdf[0]
            try:
                width, height = page.get_size()
            finally:
                page.close()
            scale = min(1.5, 1500/max(width, height))
            image = render_image(pdf, 0, scale)
        self.scene().clear(); self.selection = None; self.handles = []; self.guide_items = []
        item = self.scene().addPixmap(QPixmap.fromImage(image)); item.setScale(1/scale)
        self.scene().setSceneRect(0, 0, width, height)
        self.fit_page_width()

    def fit_page_width(self):
        if self.sceneRect().width()<=0:return
        self.resetTransform()
        scale=max(.1,(self.viewport().width()-34)/self.sceneRect().width())
        self.scale(scale,scale)

    def highlight(self, rect):
        if self.selection is not None:
            self.scene().removeItem(self.selection)
            self.selection = None
        for handle in self.handles:
            if handle.scene() is not None:self.scene().removeItem(handle)
        self.handles=[]
        if rect and not rect.isEmpty():
            pen = QPen(QColor('#0e846c'), 0)
            self.selection = self.scene().addRect(rect, pen, QColor(19, 151, 120, 24))
            points=[rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight(),
                QPointF(rect.center().x(),rect.top()),QPointF(rect.center().x(),rect.bottom()),
                QPointF(rect.left(),rect.center().y()),QPointF(rect.right(),rect.center().y())]
            radius=max(2.5,5/self.transform().m11())
            for point in points:
                self.handles.append(self.scene().addEllipse(point.x()-radius,point.y()-radius,radius*2,radius*2,
                    QPen(QColor('#087a63'),0),QColor('white')))

    def clear_guides(self):
        for item in self.guide_items:
            if item.scene() is not None:self.scene().removeItem(item)
        self.guide_items=[]

    def snap_rect(self, rect):
        """Snap edges and centres to the page with temporary alignment guides."""
        self.clear_guides()
        threshold=max(2,7/self.transform().m11());page=self.sceneRect();pen=QPen(QColor('#e0404b'),0,Qt.PenStyle.DashLine)
        x_targets=[page.left(),page.center().x(),page.right()]
        x_values=[rect.left(),rect.center().x(),rect.right()]
        best=min(((abs(value-target),target-value,target) for value in x_values for target in x_targets),key=lambda item:item[0])
        if best[0]<=threshold:
            rect.translate(best[1],0);self.guide_items.append(self.scene().addLine(best[2],page.top(),best[2],page.bottom(),pen))
        y_targets=[page.top(),page.center().y(),page.bottom()]
        y_values=[rect.top(),rect.center().y(),rect.bottom()]
        best=min(((abs(value-target),target-value,target) for value in y_values for target in y_targets),key=lambda item:item[0])
        if best[0]<=threshold:
            rect.translate(0,best[1]);self.guide_items.append(self.scene().addLine(page.left(),best[2],page.right(),best[2],pen))
        return rect

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page_width()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point=self.mapToScene(event.position().toPoint())
            if self.selection is not None:
                rect=self.selection.rect();corners=[rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight()]
                tolerance=max(6,10/self.transform().m11())
                for index,corner in enumerate(corners):
                    if (corner-point).manhattanLength()<=tolerance:
                        self.drag_mode=('resize',index);self.drag_origin=point;self.drag_rect=QRectF(rect);event.accept();return
                if rect.contains(point):
                    self.drag_mode=('move',0);self.drag_origin=point;self.drag_rect=QRectF(rect);event.accept();return
            self.start = point
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_mode is not None:
            point=self.mapToScene(event.position().toPoint());rect=QRectF(self.drag_rect)
            if self.drag_mode[0]=='move':
                rect.translate(point-self.drag_origin)
                if rect.left()<0:rect.moveLeft(0)
                if rect.top()<0:rect.moveTop(0)
                if rect.right()>self.sceneRect().right():rect.moveRight(self.sceneRect().right())
                if rect.bottom()>self.sceneRect().bottom():rect.moveBottom(self.sceneRect().bottom())
                rect=self.snap_rect(rect)
            else:
                index=self.drag_mode[1]
                if index==0:rect.setTopLeft(point)
                elif index==1:rect.setTopRight(point)
                elif index==2:rect.setBottomLeft(point)
                else:rect.setBottomRight(point)
                rect=rect.normalized().intersected(self.sceneRect())
            if rect.width()>=3 and rect.height()>=3:self.highlight(rect)
            event.accept();return
        if self.start is not None:
            rect = QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized().intersected(self.sceneRect())
            self.highlight(rect); event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_mode is not None and event.button()==Qt.MouseButton.LeftButton:
            rect=QRectF(self.selection.rect()) if self.selection is not None else QRectF()
            self.drag_mode=None;self.drag_origin=None;self.drag_rect=None
            self.clear_guides()
            if rect.width()>=3 and rect.height()>=3:self.rect_changed.emit(rect)
            event.accept();return
        if self.start is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized().intersected(self.sceneRect())
            self.start = None
            self.region_selected.emit(rect); event.accept(); return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.selection is not None and event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            step=10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx=(-step if event.key()==Qt.Key.Key_Left else step if event.key()==Qt.Key.Key_Right else 0)
            dy=(-step if event.key()==Qt.Key.Key_Up else step if event.key()==Qt.Key.Key_Down else 0)
            rect=self.selection.rect().translated(dx,dy).intersected(self.sceneRect())
            self.highlight(rect);self.rect_changed.emit(rect);event.accept();return
        if self.selection is not None and event.key()==Qt.Key.Key_Delete:
            self.delete_requested.emit();event.accept();return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.text_double_clicked.emit(self.mapToScene(event.position().toPoint()))
            event.accept(); return
        super().mouseDoubleClickEvent(event)


class PageEditorDialog(QDialog):
    ocr_requested = Signal()

    def __init__(self, data, parent=None, embedded=False):
        super().__init__(parent)
        ensure_font_support()
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('تعديل محتوى الصفحة — ورقة')
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1180, 820)
        self.data = prepare_page(data)
        self.initial_data = self.data
        self.history, self.future = [], []
        self.mode = 'select'
        self.image = None; self.table_rows = None
        self.loading = False
        self.draft = None
        self.pending = False
        layout = QVBoxLayout(self)
        note = QLabel('حرّر النص والصور مباشرة داخل الصفحة؛ انقر العنصر أو اسحب حوله ثم استخدم لوحة الخصائص.')
        note.setWordWrap(True); layout.addWidget(note)
        toolbar = QHBoxLayout()
        for label, callback in [('تحديد عنصر', self.select_mode), ('نص جديد', self.new_text), ('إضافة صورة…', self.choose_image),
                                ('استبدال الصورة…', self.replace_selected_image), ('إدراج جدول…', self.new_table)]:
            button = QPushButton(label); button.clicked.connect(callback); toolbar.addWidget(button)
        self.ocr_button=QPushButton('OCR لهذه الصفحة');self.ocr_button.clicked.connect(self.ocr_requested.emit);toolbar.addWidget(self.ocr_button)
        self.undo_button = QPushButton('تراجع'); self.undo_button.clicked.connect(self.undo); toolbar.addWidget(self.undo_button)
        self.redo_button = QPushButton('إعادة'); self.redo_button.clicked.connect(self.redo); toolbar.addWidget(self.redo_button)
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = EditCanvas(); self.canvas.region_selected.connect(self.pick_region)
        self.canvas.rect_changed.connect(self.set_rect)
        self.canvas.text_double_clicked.connect(self.direct_pick)
        self.canvas.delete_requested.connect(self.delete_selected)
        self.direct_editor = None
        self.direct_proxy = None
        self.direct_toolbar_proxy = None
        self._direct_sync = False
        panel = QWidget(); panel.setMaximumWidth(395); panel.setMinimumWidth(300)
        controls = QVBoxLayout(panel)
        self.status = QLabel(); self.status.setWordWrap(True); controls.addWidget(self.status)
        self.group_mode = QComboBox()
        for label, value in [('تحديد فقرة', 'paragraph'), ('تحديد كلمة', 'word'), ('تحديد العنصر الأصلي', 'object')]:
            self.group_mode.addItem(label, value)
        self.group_mode.currentIndexChanged.connect(self.reload)
        controls.addWidget(self.group_mode)
        self.objects = QListWidget(); self.objects.setMaximumHeight(135)
        self.objects.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.objects.itemSelectionChanged.connect(self.object_selected); controls.addWidget(self.objects)
        self.text = QPlainTextEdit(); self.text.setPlaceholderText('اكتب النص الجديد هنا…')
        self.text.setMaximumHeight(125); self.text.textChanged.connect(self.mark_pending)
        controls.addWidget(self.text)
        form = QFormLayout()
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont('Segoe UI'))
        self.font.currentFontChanged.connect(self.mark_pending); form.addRow('الخط', self.font)
        import_font = QPushButton('استيراد خط TTF / OTF…'); import_font.clicked.connect(self.import_font)
        form.addRow('', import_font)
        self.size = QDoubleSpinBox(); self.size.setRange(4, 200); self.size.setDecimals(1); self.size.setValue(16)
        self.size.valueChanged.connect(self.mark_pending); form.addRow('حجم الخط', self.size)
        self.bold = QCheckBox('خط عريض'); self.bold.toggled.connect(self.mark_pending); form.addRow('', self.bold)
        self.auto_fit = QCheckBox('ملاءمة النص تلقائيًا داخل المساحة'); self.auto_fit.setChecked(True)
        self.auto_fit.toggled.connect(self.mark_pending); form.addRow('', self.auto_fit)
        self.color = QComboBox()
        for label, value in [('أسود', '#172a32'), ('أزرق', '#174b91'), ('أخضر', '#087a63'), ('أحمر', '#b62432')]:
            self.color.addItem(label, value)
        self.color.currentIndexChanged.connect(self.mark_pending); form.addRow('اللون', self.color)
        self.alignment = QComboBox()
        for label, value in [('تلقائي', 'auto'), ('يمين', 'right'), ('وسط', 'center'), ('يسار', 'left')]: self.alignment.addItem(label, value)
        self.alignment.currentIndexChanged.connect(self.mark_pending); form.addRow('المحاذاة', self.alignment)
        self.geometry = []
        for label, default in [('من اليسار %', 10), ('من أعلى %', 10), ('العرض %', 70), ('الارتفاع %', 12)]:
            spin = QDoubleSpinBox(); spin.setRange(0, 100); spin.setDecimals(2); spin.setValue(default)
            spin.valueChanged.connect(self.geometry_changed); self.geometry.append(spin); form.addRow(label, spin)
        controls.addLayout(form)
        preview = QPushButton('معاينة التعديل'); preview.clicked.connect(self.preview_change); controls.addWidget(preview)
        self.before_after_button=QPushButton('عرض قبل / بعد');self.before_after_button.setEnabled(False)
        self.before_after_button.clicked.connect(self.toggle_before_after);controls.addWidget(self.before_after_button)
        self.showing_after=True
        self.apply_button = QPushButton('تطبيق على الصفحة'); self.apply_button.clicked.connect(self.apply_change); controls.addWidget(self.apply_button)
        self.delete_button = QPushButton('حذف المحدد'); self.delete_button.clicked.connect(self.delete_selected); controls.addWidget(self.delete_button)
        controls.addStretch()
        hint = QLabel('تجميع الكلمات والفقرات تقديري. يُختار الخط الأصلي إذا كان متاحًا، وإلا يُستخدم بديل. راجع المعاينة قبل التطبيق.')
        hint.setWordWrap(True); controls.addWidget(hint)
        # Keep the detailed model controls available internally, but expose the
        # common formatting commands as a compact floating-style bar above the
        # page. Text itself is edited in place on the PDF canvas.
        quick = QHBoxLayout()
        quick.addWidget(QLabel('الخط')); quick.addWidget(self.font, 2)
        quick.addWidget(QLabel('الحجم')); quick.addWidget(self.size)
        quick.addWidget(self.bold); quick.addWidget(self.color)
        quick.addWidget(self.alignment); quick.addWidget(self.auto_fit)
        quick.addStretch(); quick.addWidget(preview);quick.addWidget(self.before_after_button);quick.addWidget(self.delete_button); quick.addWidget(self.apply_button)
        layout.addLayout(quick)
        # Retain non-visual selection/geometry controls as state holders without
        # showing the former side panel.
        panel.setParent(self); panel.hide()
        splitter.addWidget(self.canvas); splitter.setStretchFactor(0, 1)
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('إنهاء التعديل')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('إلغاء جميع تعديلات الصفحة')
        buttons.accepted.connect(self.finish); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.font.currentFontChanged.connect(self.update_direct_style)
        self.size.valueChanged.connect(self.update_direct_style)
        self.bold.toggled.connect(self.update_direct_style)
        self.shortcuts = []
        for keys, callback in [('Ctrl+Return', self.apply_change), ('Ctrl+Enter', self.apply_change),
                               ('Ctrl+Z', self.undo), ('Ctrl+Shift+Z', self.redo),
                               ('Ctrl+Y', self.redo), ('Escape', self.discard_direct_edit)]:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback); self.shortcuts.append(shortcut)
        self.reload()

    def import_font(self):
        path, _ = QFileDialog.getOpenFileName(self, 'استيراد خط', '', 'ملفات الخطوط (*.ttf *.otf *.ttc)')
        if not path:
            return
        try:families=install_font(path)
        except Exception as exc:
            QMessageBox.warning(self,'استيراد الخط',str(exc));return
        self.font.setCurrentFont(QFont(families[0]))
        self.status.setText(f'تم استيراد الخط: {families[0]}. سيظهر بعد إعادة تشغيل ورقة؛ تأكد من امتلاك ترخيص استخدامه وتوزيعه.')

    def reload(self):
        self.loading = True
        self.width, self.height, self.entries = inspect_page(self.data)
        self.entries = group_text(self.data, self.entries, self.group_mode.currentData())
        self.objects.clear()
        for entry in self.entries:
            label = ('نص: ' + (entry.text.replace('\n', ' ')[:90] or 'نص غير قابل للاستخراج')) if entry.kind == 'text' else 'صورة'
            item = QListWidgetItem(label); item.setToolTip(entry.text); self.objects.addItem(item)
        self.loading = False
        self.mode = 'select'; self.image = None; self.text.clear(); self.draft = None
        self.canvas.set_page(self.data)
        self.direct_editor = None; self.direct_proxy = None; self.direct_toolbar_proxy = None
        self.status.setText(f'{len(self.entries)} عنصرًا نصيًا أو صورة قابلًا للتحديد' if self.entries else 'لا توجد نصوص أو صور مستقلة قابلة للتعديل. يمكنك إضافة نص أو صورة؛ النص داخل المسح الضوئي يحتاج OCR.')
        self.ocr_button.setVisible(not bool(self.entries))
        self.delete_button.setEnabled(False)
        self.undo_button.setEnabled(bool(self.history)); self.redo_button.setEnabled(bool(self.future))
        self.pending = False

    def selected_entries(self):
        return [self.entries[self.objects.row(item)] for item in self.objects.selectedItems()]

    def selected_indexes(self):
        return list(dict.fromkeys(index for entry in self.selected_entries() for index in (entry.indices or (entry.index,))))

    def selected_chars(self):
        return tuple(dict.fromkeys(index for entry in self.selected_entries() for index in entry.chars))

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
        self.before_after_button.setEnabled(False);self.before_after_button.setText('عرض قبل / بعد');self.showing_after=True

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
            sample = text_entries[0]
            size = max(4, min(200, sample.size))
            self.size.setValue(size)
            family = sample.family.split('+')[-1]
            aliases = {'Helvetica': 'Arial', 'Times-Roman': 'Times New Roman', 'Courier': 'Courier New'}
            family = aliases.get(family, family)
            available = {name.casefold(): name for name in QFontDatabase.families()}
            family = available.get(family.casefold(), 'Segoe UI')
            self.font.setCurrentFont(QFont(family)); self.bold.setChecked(sample.bold)
            color_index = self.color.findData(sample.color)
            if color_index < 0:
                self.color.addItem('اللون الأصلي', sample.color); color_index = self.color.count()-1
            self.color.setCurrentIndex(color_index)
            self.alignment.setCurrentIndex(max(0, self.alignment.findData(sample.alignment)))
            # Glyph bounds exclude font ascenders/line leading; reserve room for
            # a complete newly shaped line. The exact box remains user-editable.
            bounds.setTop(max(0, bounds.top()-size*.25))
            bounds.setHeight(max(bounds.height(), size*1.9))
        bounds = bounds.intersected(QRectF(0, 0, self.width, self.height))
        self.set_rect(bounds)
        self.status.setText(f'تم تحديد {len(selected)} عنصر. الاستبدال أو الحذف يخص العناصر المحددة فقط.')
        self.pending = False
        if text_entries:
            self.open_direct_editor()

    def direct_pick(self, point):
        """Open the text beneath a double click directly on the page."""
        self.pick_region(QRectF(point, point))
        if self.selected_entries() and self.selected_entries()[0].kind == 'text':
            self.open_direct_editor()

    def open_direct_editor(self):
        """Place an editor over the original text box and grow it as needed."""
        if not self.selected_entries() and self.mode != 'text':
            return
        if self.direct_proxy is not None and self.direct_proxy.scene() is not None:
            self.canvas.scene().removeItem(self.direct_proxy)
        rect = self.rect()
        rect.setWidth(max(rect.width(), self.size.value() * 4))
        rect.setHeight(max(rect.height(), self.size.value() * 1.9))
        rect = rect.intersected(QRectF(0, 0, self.width, self.height))
        self.set_rect(rect)
        editor = QPlainTextEdit()
        editor.setPlainText(self.text.toPlainText())
        editor.setFrameStyle(0)
        editor.setStyleSheet('QPlainTextEdit { background: rgba(255,255,255,238); border: 2px solid #c9343e; padding: 5px; selection-background-color: #ef9aa1; }')
        proxy = self.canvas.scene().addWidget(editor)
        proxy.setGeometry(rect)
        proxy.setZValue(20)
        self.direct_editor, self.direct_proxy = editor, proxy
        editor.textChanged.connect(self.direct_text_changed)
        editor.document().documentLayout().documentSizeChanged.connect(self.grow_direct_editor)
        self.update_direct_style()
        floating = QWidget()
        floating.setStyleSheet('QWidget { background: #24323d; color: white; } QPushButton { min-height: 24px; padding: 3px 10px; }')
        floating_layout = QHBoxLayout(floating); floating_layout.setContentsMargins(4, 3, 4, 3); floating_layout.setSpacing(4)
        mini_font = QFontComboBox(); mini_font.setCurrentFont(self.font.currentFont()); mini_font.setMaximumWidth(145)
        mini_font.setToolTip('الخط'); mini_font.currentFontChanged.connect(self.font.setCurrentFont); floating_layout.addWidget(mini_font)
        mini_size = QDoubleSpinBox(); mini_size.setRange(4,200); mini_size.setValue(self.size.value()); mini_size.setMaximumWidth(65)
        mini_size.setToolTip('حجم الخط'); mini_size.valueChanged.connect(self.size.setValue); floating_layout.addWidget(mini_size)
        mini_bold = QPushButton('B'); mini_bold.setCheckable(True); mini_bold.setChecked(self.bold.isChecked()); mini_bold.setMaximumWidth(36)
        mini_bold.setToolTip('خط عريض'); mini_bold.toggled.connect(self.bold.setChecked); floating_layout.addWidget(mini_bold)
        mini_align = QComboBox(); mini_align.addItem('يمين','right'); mini_align.addItem('وسط','center'); mini_align.addItem('يسار','left')
        mini_align.setCurrentIndex(max(0,mini_align.findData(self.alignment.currentData())));mini_align.setToolTip('المحاذاة')
        mini_align.currentIndexChanged.connect(lambda *_:self.alignment.setCurrentIndex(max(0,self.alignment.findData(mini_align.currentData()))))
        floating_layout.addWidget(mini_align)
        save = QPushButton('✓ تطبيق'); save.clicked.connect(self.apply_change); floating_layout.addWidget(save)
        cancel = QPushButton('إلغاء'); cancel.clicked.connect(self.discard_direct_edit); floating_layout.addWidget(cancel)
        toolbar_proxy = self.canvas.scene().addWidget(floating); toolbar_proxy.setZValue(21)
        floating.adjustSize()
        toolbar_y = rect.top() - floating.sizeHint().height() - 4
        if toolbar_y < 0: toolbar_y = rect.bottom() + 4
        toolbar_proxy.setPos(rect.left(), toolbar_y)
        self.direct_toolbar_proxy = toolbar_proxy
        editor.setFocus(); editor.selectAll()
        self.status.setText('عدّل النص في مكانه. انقر خارج المربع للحفظ تلقائيًا، أو استخدم Ctrl+Enter للتطبيق وEsc للإلغاء.')

    def direct_text_changed(self):
        if self._direct_sync or self.direct_editor is None:
            return
        self._direct_sync = True
        self.text.setPlainText(self.direct_editor.toPlainText())
        self._direct_sync = False
        self.mark_pending()

    def grow_direct_editor(self, size):
        """Grow the in-page box for longer text without imposing a fixed size."""
        if self.direct_proxy is None or self.direct_proxy.scene() is None:
            return
        rect = self.direct_proxy.geometry()
        wanted_height = max(rect.height(), size.height() + 14)
        rect.setHeight(min(wanted_height, self.height - rect.top()))
        self.direct_proxy.setGeometry(rect)
        self.set_rect(rect)

    def update_direct_style(self, *_):
        if self.direct_editor is None:
            return
        font = QFont(self.font.currentFont())
        font.setPointSizeF(self.size.value()); font.setBold(self.bold.isChecked())
        self.direct_editor.setFont(font)

    def discard_direct_edit(self):
        if self.direct_editor is not None:
            self.reload()

    def select_mode(self):
        self.clear_draft(); self.mode = 'select'; self.image = None
        self.status.setText('انقر عنصرًا، أو اسحب مستطيلًا حول النص لتحديد عدة عناصر.')

    def pick_region(self, rect):
        if (self.direct_proxy is not None and self.pending
                and not self.direct_proxy.geometry().contains(rect.center())):
            try:
                self.commit(self.draft if self.draft is not None else self.make_change())
            except Exception as exc:
                QMessageBox.warning(self, 'تعذر التعديل', str(exc)); return
        self.clear_draft()
        if self.mode in ('text', 'image', 'table'):
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
        self.open_direct_editor()

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

    def replace_selected_image(self):
        selected=self.selected_entries()
        if len(selected)!=1 or selected[0].kind!='image':
            QMessageBox.information(self,'استبدال الصورة','حدد صورة واحدة داخل الصفحة أولًا.');return
        path,_=QFileDialog.getOpenFileName(self,'استبدال الصورة','', 'صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)')
        if not path:return
        reader=QImageReader(path);reader.setAutoTransform(True);image=reader.read()
        if image.isNull():QMessageBox.warning(self,'الصورة','تعذر قراءة الصورة.');return
        self.clear_draft();self.mode='replace_image';self.image=image
        self.status.setText('تم اختيار الصورة البديلة. حرّك الإطار أو غيّر حجمه ثم اضغط «تطبيق على الصفحة».')

    def new_table(self):
        raw,ok=QInputDialog.getMultiLineText(self,'إدراج أو تحرير جدول','اكتب صفوف الجدول؛ افصل الخلايا بزر Tab. يمكنك إضافة الأسطر أو حذفها وإعادة ترتيبها:','العنوان 1\tالعنوان 2\nقيمة 1\tقيمة 2')
        if not ok:return
        rows=[[cell.strip() for cell in line.split('\t')] for line in raw.splitlines() if line.strip()]
        if not rows:QMessageBox.warning(self,'الجدول','أضف صفًا واحدًا على الأقل.');return
        self.clear_draft();self.objects.clearSelection();self.mode='table';self.image=None;self.table_rows=rows
        self.set_rect(QRectF(self.width*.1,self.height*.15,self.width*.8,min(self.height*.6,max(80,len(rows)*35))))
        self.status.setText('اسحب لتحديد مساحة الجدول ثم عاينه. النص والخطوط ستبقى عناصر متجهة داخل PDF.')

    def make_change(self):
        if self.mode=='table':
            rect=self.rect();return insert_table(self.data,(rect.x(),rect.y(),rect.width(),rect.height()),self.table_rows,
                family=self.font.currentFont().family(),size=self.size.value(),rtl=True)
        indexes = self.selected_indexes() if self.mode in ('select','replace_image') else []
        if self.mode == 'select' and not indexes:
            raise ValueError('حدد نصًا لتعديله، أو اختر «نص جديد» أو «إضافة صورة».')
        if self.mode == 'select' and any(e.kind != 'text' for e in self.selected_entries()):
            raise ValueError('لتغيير الصورة احذفها ثم أضف الصورة الجديدة. استبدال النص يتطلب تحديد نصوص فقط.')
        rect = self.rect()
        return edit_page(self.data, indexes, text=None if self.mode in ('image','replace_image') else self.text.toPlainText(),
            image=self.image if self.mode in ('image','replace_image') else None,
            rect=(rect.x(), rect.y(), rect.width(), rect.height()), size=self.size.value(),
            family=self.font.currentFont().family(), color=self.color.currentData(), bold=self.bold.isChecked(),
            alignment=self.alignment.currentData(), selected_chars=self.selected_chars() if self.mode == 'select' else None,
            auto_fit=self.auto_fit.isChecked())

    def preview_change(self):
        try:
            self.draft = self.make_change(); self.canvas.set_page(self.draft)
            self.showing_after=True;self.before_after_button.setEnabled(True);self.before_after_button.setText('عرض الأصل')
            self.status.setText('هذه معاينة فقط. اضغط «تطبيق على الصفحة» للاحتفاظ بها داخل المحرر.')
        except Exception as exc:
            QMessageBox.warning(self, 'تعذر التعديل', str(exc))

    def toggle_before_after(self):
        if self.draft is None:return
        self.showing_after=not self.showing_after
        self.canvas.set_page(self.draft if self.showing_after else self.data)
        self.before_after_button.setText('عرض الأصل' if self.showing_after else 'عرض التعديل')

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
                self.commit(edit_page(self.data, indexes, selected_chars=self.selected_chars() or None))
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
