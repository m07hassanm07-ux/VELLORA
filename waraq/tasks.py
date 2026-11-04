"""Responsive task orchestration; PDFium/Qt PDF work runs in child processes."""
from pathlib import Path
import json, os, subprocess, sys, tempfile, time
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout
from .projects import encode_snapshot, protect_local, unprotect_local
from .ocr import JobCancelled


def worker_command(flag,folder):
    return ([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve().parents[1]/'run.py')])+[flag,str(folder)]


class TaskThread(QThread):
    progress=Signal(int,int,str)
    succeeded=Signal(object)
    failed=Signal(str)
    cancelled=Signal()

    def __init__(self,operation,parent=None):
        super().__init__(parent);self.operation=operation;self.value=None;self.error=None;self.was_cancelled=False

    def report(self,done,total,message):
        self.progress.emit(done,total,message)
        if self.isInterruptionRequested():raise JobCancelled('تم إلغاء العملية.')
        return True

    def run(self):
        try:
            self.value=self.operation(self.report,self.isInterruptionRequested)
            self.succeeded.emit(self.value)
        except JobCancelled:
            self.was_cancelled=True;self.cancelled.emit()
        except Exception as exc:
            self.error=str(exc);self.failed.emit(str(exc))


class TaskDialog(QDialog):
    def __init__(self,label,thread,parent=None):
        super().__init__(parent);self.setWindowTitle(label);self.setMinimumWidth(460);self.thread=thread
        layout=QVBoxLayout(self);self.message=QLabel(label);self.message.setWordWrap(True);layout.addWidget(self.message)
        self.bar=QProgressBar();self.bar.setRange(0,0);layout.addWidget(self.bar)
        self.cancel=QPushButton('إلغاء');self.cancel.clicked.connect(self.request_cancel);layout.addWidget(self.cancel)
        thread.progress.connect(self.update_progress);thread.finished.connect(self.accept)

    def update_progress(self,done,total,message):
        self.message.setText(message);self.bar.setRange(0,max(0,total));self.bar.setValue(done)

    def request_cancel(self):
        self.thread.requestInterruption();self.cancel.setEnabled(False);self.message.setText('جاري الإلغاء بأمان…')

    def reject(self):
        if self.thread.isRunning():self.request_cancel()
        else:super().reject()


def run_task(parent,label,operation):
    if hasattr(parent,'record_operation'):parent.record_operation(label,'جارٍ التنفيذ')
    thread=TaskThread(operation,parent);dialog=TaskDialog(label,thread,parent)
    thread.start();dialog.exec();thread.wait()
    value,error,cancelled=thread.value,thread.error,thread.was_cancelled
    dialog.deleteLater();thread.deleteLater()
    if error:
        if hasattr(parent,'record_operation'):parent.record_operation(label,'فشل')
        raise ValueError(error)
    if cancelled:
        if hasattr(parent,'record_operation'):parent.record_operation(label,'أُلغي')
        raise JobCancelled('تم إلغاء العملية؛ لم تُطبّق نتيجة جزئية.')
    if hasattr(parent,'record_operation'):parent.record_operation(label,'اكتمل')
    return value


def process_job(state,kind,params,report,cancelled):
    """Encrypted user-local IPC. Child owns all PDFium handles and PDF parsing."""
    with tempfile.TemporaryDirectory(prefix='waraq-job-') as directory:
        folder=Path(directory)
        report(0,0,'جاري تجهيز المعالجة…')
        (folder/'state.bin').write_bytes(encode_snapshot(state,local=True,compress=False))
        (folder/'request.bin').write_bytes(protect_local(json.dumps({'kind':kind,'params':params}).encode('utf-8')))
        if cancelled():raise JobCancelled()
        process=subprocess.Popen(worker_command('--job',folder),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        cancellation_time=None;last_progress=None
        try:
            while process.poll() is None:
                if cancelled():
                    (folder/'cancel').touch(exist_ok=True)
                    if cancellation_time is None:cancellation_time=time.monotonic()
                    # Cooperative OCR cancellation terminates its own subprocess;
                    # generic CPU jobs can be killed after a short grace period.
                    if time.monotonic()-cancellation_time>8:
                        process.kill();process.wait();raise JobCancelled()
                try:
                    value=(folder/'progress.json').read_text(encoding='utf-8')
                    if value!=last_progress:
                        p=json.loads(value);last_progress=value
                        if not cancelled():report(p['done'],p['total'],p['message'])
                except (OSError,ValueError):pass
                time.sleep(.08)
            if cancelled():raise JobCancelled()
            if not (folder/'result.bin').is_file():raise ValueError('توقفت عملية المعالجة قبل إرجاع نتيجة. لم يتغير المستند.')
            result=json.loads(unprotect_local((folder/'result.bin').read_bytes()).decode('utf-8'))
            if result.get('cancelled'):raise JobCancelled()
            if result.get('error'):raise ValueError(result['error'])
            if (folder/'output.bin').is_file():result['data']=unprotect_local((folder/'output.bin').read_bytes())
            return result
        finally:
            if process.poll() is None:
                (folder/'cancel').touch(exist_ok=True)
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.kill();process.wait()
