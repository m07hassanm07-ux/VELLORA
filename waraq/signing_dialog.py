"""Desktop interface for local signing requests and returned documents."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout)

from .core import atomic_write
from .ocr import JobCancelled
from .signatures import sign_pkcs12
from .signing_requests import RequestStore, create_request, draft_email, inspect_return, next_signer, request_fields
from .tasks import run_task


class SigningRequestsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.store = RequestStore()
        self.setWindowTitle('طلبات التوقيع')
        self.resize(690, 450)
        layout = QVBoxLayout(self)
        note = QLabel('احفظ مسودة البريد بالمرفق وأرسلها من برنامج البريد. استورد الرد الموقّع لفتح دور الموقّع التالي.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.requests = QListWidget()
        layout.addWidget(self.requests, 1)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.controls = {}
        for key, label, handler in (
            ('new', 'طلب من المستند الحالي', self.create),
            ('draft', 'حفظ مسودة بريد', self.export_draft),
            ('pdf', 'حفظ PDF', self.export_pdf),
            ('return', 'استلام PDF موقّع', self.import_return),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
            self.controls[key] = button
        layout.addLayout(row)
        self.controls['new'].setEnabled(bool(window.document.pages))
        self.requests.currentItemChanged.connect(self.update_details)
        self.reload()

    def reload(self, identifier=None):
        self.requests.clear()
        for key in self.store.ids():
            try:
                request = self.store.load(key)
                count = sum(signer['status'] == 'signed' for signer in request['signers'])
                caption = f'{request["title"]} ({count}/{len(request["signers"])})'
            except Exception:
                caption = 'طلب محفوظ تعذر فتحه'
            item = QListWidgetItem(caption)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.requests.addItem(item)
            if key == identifier:
                self.requests.setCurrentItem(item)
        if self.requests.currentItem() is None and self.requests.count():
            self.requests.setCurrentRow(0)
        self.update_details()

    def current(self):
        item = self.requests.currentItem()
        return self.store.load(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def update_details(self, *_):
        request = None
        try:
            request = self.current()
            labels = {'waiting': 'بانتظار الدور', 'drafted': 'أُعدت مسودة البريد', 'signed': 'استُلم التوقيع'}
            lines = [f'{i}. {signer["email"]} — {labels[signer["status"]]}'
                     for i, signer in enumerate(request['signers'], 1)] if request else []
            self.details.setText('\n'.join(lines) or 'لا توجد طلبات توقيع محفوظة.')
        except Exception as exc:
            self.details.setText(str(exc))
        active = bool(request and next_signer(request))
        self.controls['draft'].setEnabled(active)
        self.controls['return'].setEnabled(active)
        self.controls['pdf'].setEnabled(bool(request))

    def create(self):
        title, ok = QInputDialog.getText(self, 'طلب توقيع', 'عنوان الطلب:', text=self.window.document_name.text())
        if not ok:
            return
        recipients, ok = QInputDialog.getMultiLineText(self, 'ترتيب الموقّعين', 'أدخل عنوانًا لكل سطر، بدءًا بالموقّع الأول:')
        if not ok:
            return
        try:
            data = self.window.assembled_bytes('تجهيز المستند لطلب التوقيع')
            request = create_request(title, [line for line in recipients.splitlines() if line.strip()], data)
            self.store.save(request)
            self.reload(request['id'])
        except JobCancelled:
            pass
        except Exception as exc:
            self.warn(exc)

    def export_draft(self):
        try:
            request = self.current()
            path, _ = QFileDialog.getSaveFileName(self, 'حفظ مسودة البريد', 'Vellora-request.eml', 'Email (*.eml)')
            if not path:
                return
            atomic_write(path, draft_email(request))
            updated = deepcopy(request)
            next_signer(updated)['status'] = 'drafted'
            self.store.save(updated, previous=request)
            self.reload(request['id'])
        except Exception as exc:
            self.warn(exc)

    def export_pdf(self):
        try:
            request = self.current()
            path, _ = QFileDialog.getSaveFileName(self, 'حفظ نسخة الطلب', 'Vellora-request.pdf', 'PDF (*.pdf)')
            if path:
                atomic_write(path, request['pdf'])
        except Exception as exc:
            self.warn(exc)

    def import_return(self):
        path, _ = QFileDialog.getOpenFileName(self, 'اختيار النسخة المرتجعة', '', 'PDF (*.pdf)')
        if not path:
            return
        try:
            request = self.current()
            data = Path(path).read_bytes()
            subject, trusted = run_task(self, 'التحقق من النسخة الموقّعة',
                                        lambda report, cancel: inspect_return(request, data))
            signer = next_signer(request)
            trust = 'موثوقة محليًا' if trusted else 'غير موثوقة محليًا'
            answer = QMessageBox.question(
                self, 'مطابقة الموقّع',
                f'البريد المنتظر: {signer["email"]}\nصاحب الشهادة: {subject}\nالشهادة {trust}.\n'
                'هل تحققت من هوية صاحب الشهادة وتريد تسجيل الاستلام؟',
                defaultButton=QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            updated = deepcopy(request)
            next_signer(updated).update(status='signed', subject=subject, trusted=trusted)
            updated['pdf'] = data
            self.store.save(updated, previous=request)
            self.reload(request['id'])
        except JobCancelled:
            pass
        except Exception as exc:
            self.warn(exc)

    def warn(self, error):
        QMessageBox.warning(self, 'طلبات التوقيع', str(error))


def sign_incoming_request(window):
    path, _ = QFileDialog.getOpenFileName(window, 'اختيار ملف طلب التوقيع', '', 'PDF (*.pdf)')
    if not path:
        return
    try:
        data = Path(path).read_bytes()
        fields = request_fields(data)
        if not fields:
            raise ValueError('لا توجد حقول طلب توقيع متاحة في هذا الملف.')
        certificate, _ = QFileDialog.getOpenFileName(window, 'اختيار الشهادة', '', 'PKCS#12 (*.pfx *.p12)')
        if not certificate:
            return
        password, ok = QInputDialog.getText(window, 'الشهادة', 'كلمة مرور الشهادة:', QLineEdit.EchoMode.Password)
        if not ok:
            return
        output, _ = QFileDialog.getSaveFileName(window, 'حفظ النسخة الموقّعة',
                                                str(Path(path).with_suffix('.signed.pdf')), 'PDF (*.pdf)')
        if not output:
            return
        if Path(output).resolve() == Path(path).resolve():
            raise ValueError('اختر اسمًا مختلفًا للنسخة الموقّعة.')
        signed = run_task(window, 'توقيع ملف الطلب', lambda report, cancel:
                          sign_pkcs12(data, certificate, password, field_name=fields[0]))
        atomic_write(output, signed)
        window.statusBar().showMessage('حُفظت النسخة الموقّعة. أعدها إلى مرسل الطلب.', 12000)
    except JobCancelled:
        pass
    except Exception as exc:
        QMessageBox.warning(window, 'توقيع ملف طلب وارد', str(exc))
