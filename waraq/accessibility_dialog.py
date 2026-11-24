"""Review and repair accessibility tags in a standalone PDF copy."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .accessibility import AccessibilityDocument, TEXT_ROLES
from .core import atomic_write
from .ocr import JobCancelled
from .pdfua_validation import validate_pdfua
from .tasks import run_task


class AccessibilityDialog(QDialog):
    def __init__(self, parent, path, document):
        super().__init__(parent)
        self.path = path
        self.document = document
        self.setWindowTitle('مراجعة إمكانية الوصول — VELLORA')
        self.resize(760, 570)
        layout = QVBoxLayout(self)
        note = QLabel('راجع شجرة الوسوم بالترتيب الذي تتبعه قارئات الشاشة. هذا فحص مساعد لبعض الشروط، ويتطلب التوافق الكامل فحصًا مستقلًا ومراجعة بشرية.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['الوسم', 'الصفحة', 'الوصف البديل'])
        self.tree.setColumnWidth(0, 225)
        self.tree.setColumnWidth(1, 80)
        layout.addWidget(self.tree, 1)
        self.tree.currentItemChanged.connect(self.update_controls)
        review = QHBoxLayout()
        self.auto_button = QPushButton('إنشاء وسوم أولية…')
        self.auto_button.clicked.connect(self.auto_tag)
        review.addWidget(self.auto_button)
        validate = QPushButton('فحص PDF/UA عبر veraPDF…')
        validate.clicked.connect(self.validate)
        review.addWidget(validate)
        review.addStretch()
        layout.addLayout(review)
        row = QHBoxLayout()
        self.buttons = {}
        for key, label, handler in (
            ('meta', 'اللغة والعنوان', self.edit_metadata),
            ('alt', 'وصف بديل', self.edit_alt),
            ('role', 'فقرة أو عنوان', self.edit_role),
            ('up', 'نقل لأعلى', lambda: self.move(-1)),
            ('down', 'نقل لأسفل', lambda: self.move(1)),
            ('save', 'حفظ نسخة PDF…', self.save),
            ('close', 'إغلاق', self.reject),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
            self.buttons[key] = button
        layout.addLayout(row)
        self.reload()

    def reload(self, selection=None):
        tags = self.document.tags()
        self.tree.clear()
        items = {}
        for tag in tags:
            item = QTreeWidgetItem([tag.role, str(tag.page or '—'), tag.alt.replace('\n', ' ')])
            item.setData(0, Qt.ItemDataRole.UserRole, tag.path)
            item.setToolTip(2, tag.alt)
            parent = items.get(tag.path[:-1])
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            items[tag.path] = item
        self.tree.expandToDepth(1)
        if selection in items:
            self.tree.setCurrentItem(items[selection])
        issues = self.document.issues(tags)
        if self.document.signed:
            issues.insert(0, 'هذا المستند موقّع رقميًا، وهو مفتوح للمراجعة فقط.')
        self.summary.setText(
            f'الوسوم: {len(tags)}  |  اللغة: {self.document.language or "—"}  |  العنوان: {self.document.title or "—"}\n'
            + ('\n'.join(issues) if issues else 'لم تظهر مشكلات ضمن الفحوص المحدودة.')
        )
        self.update_controls()

    def path_selected(self):
        item = self.tree.currentItem()
        return tuple(item.data(0, Qt.ItemDataRole.UserRole)) if item is not None else None

    def update_controls(self, *_):
        if not self.buttons:
            return
        path = self.path_selected()
        editable = not self.document.signed
        self.buttons['meta'].setEnabled(editable)
        self.auto_button.setEnabled(editable and '/StructTreeRoot' not in self.document.root)
        self.buttons['alt'].setEnabled(editable and bool(path) and
                                      self.document.role(self.document.node(path)) in ('Figure', 'Formula'))
        self.buttons['role'].setEnabled(editable and bool(path) and
                                       str(self.document.node(path).get('/S')).lstrip('/') in TEXT_ROLES)
        self.buttons['up'].setEnabled(editable and bool(path))
        self.buttons['down'].setEnabled(editable and bool(path))
        self.buttons['save'].setEnabled(editable and self.document.changed)

    def edit_metadata(self):
        title, ok = QInputDialog.getText(self, 'عنوان المستند', 'العنوان:', text=self.document.title)
        if not ok:
            return
        language, ok = QInputDialog.getText(self, 'لغة المستند', 'رمز اللغة:', text=self.document.language or 'ar')
        if ok:
            self.apply(self.document.set_metadata, title, language.strip())

    def edit_alt(self):
        path = self.path_selected()
        current = str(self.document.node(path).get('/Alt', ''))
        text, ok = QInputDialog.getMultiLineText(self, 'الوصف البديل', 'صف معنى العنصر في سياق المستند:', current)
        if ok:
            self.apply(self.document.set_alt, path, text)

    def move(self, step):
        self.apply(self.document.move, self.path_selected(), step)

    def edit_role(self):
        path = self.path_selected()
        current = str(self.document.node(path).get('/S')).lstrip('/')
        labels = ['فقرة (P)'] + [f'عنوان مستوى {i} (H{i})' for i in range(1, 7)]
        selected, ok = QInputDialog.getItem(self, 'نوع الوسم', 'اختر نوع النص:', labels, TEXT_ROLES.index(current), False)
        if ok:
            self.apply(self.document.set_text_role, path, TEXT_ROLES[labels.index(selected)])

    def auto_tag(self):
        response = QMessageBox.question(
            self, 'إنشاء وسوم أولية',
            'ستُنشأ وسوم للنصوص والصور المباشرة في الملفات البسيطة وفق ترتيبها داخل الملف. '
            'راجع ترتيب القراءة والعناوين وأضف أوصاف الصور قبل الحفظ.',
            defaultButton=QMessageBox.StandardButton.No)
        if response == QMessageBox.StandardButton.Yes:
            self.apply(self.document.auto_tag)

    def validate(self):
        label, ok = QInputDialog.getItem(self, 'فحص PDF/UA', 'ملف التحقق:', ['PDF/UA-1', 'PDF/UA-2'], 0, False)
        if not ok:
            return
        launcher, _ = QFileDialog.getOpenFileName(self, 'اختر ملف تشغيل veraPDF المثبّت على جهازك', '',
                                                 'veraPDF CLI (*.bat *.cmd *.exe)')
        if not launcher:
            return
        try:
            data = self.document.validation_bytes()
            profile = 'ua1' if label.endswith('1') else 'ua2'
            passed, failures = run_task(self, 'فحص PDF/UA محليًا',
                                        lambda report, cancel: validate_pdfua(launcher, data, profile))
        except JobCancelled:
            return
        except Exception as exc:
            QMessageBox.warning(self, 'فحص PDF/UA', str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle(label)
        box.setText('نجحت الفحوص الآلية.' if passed else 'أظهر الفحص الآلي شروطًا غير مستوفاة.')
        box.setInformativeText('راجع يدويًا ترتيب القراءة ومعنى الوسوم والأوصاف البديلة.')
        if failures:
            box.setDetailedText('\n'.join(failures))
        box.exec()

    def apply(self, operation, *args):
        try:
            selected = self.path_selected()
            self.reload(operation(*args) or selected)
        except Exception as exc:
            QMessageBox.warning(self, 'إمكانية الوصول', str(exc))

    def save(self):
        default = self.path.with_name(self.path.stem + '-accessibility.pdf')
        target, _ = QFileDialog.getSaveFileName(self, 'حفظ نسخة الوصول', str(default), 'PDF (*.pdf)')
        if not target:
            return
        try:
            if Path(target).resolve() == self.path.resolve():
                raise ValueError('اختر اسمًا آخر لحفظ النسخة المصححة.')
            atomic_write(target, self.document.output())
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, 'إمكانية الوصول', str(exc))

    def reject(self):
        if self.document.changed:
            answer = QMessageBox.question(self, 'إغلاق المراجعة', 'إغلاق المراجعة والتخلي عن التعديلات غير المحفوظة؟',
                                          defaultButton=QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().reject()


def open_accessibility_review(window):
    filename, _ = QFileDialog.getOpenFileName(window, 'اختر ملف PDF الأصلي لمراجعة إمكانية الوصول', '', 'PDF (*.pdf)')
    if not filename:
        return
    path = Path(filename)
    try:
        document = AccessibilityDocument(path.read_bytes())
        AccessibilityDialog(window, path, document).exec()
    except Exception as exc:
        window.error(exc)
