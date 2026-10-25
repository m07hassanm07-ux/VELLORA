from pathlib import Path
import tempfile,unittest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
from io import BytesIO
from test_editing import text_fixture
from qt_helpers import wait_for
from waraq.core import Document
from waraq.projects import snapshot
from waraq.tasks import run_task,process_job
from waraq.ocr import JobCancelled
from waraq.rendering import ensure_font_support


class BackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);ensure_font_support()

    def test_real_worker_keeps_event_loop_active_and_returns_pdf(self):
        model=Document();model.import_bytes('sample.pdf',text_fixture());state=snapshot(model)
        ticks=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        try:
            result=run_task(None,'Worker test',lambda report,cancelled:process_job(state,'assemble',{},report,cancelled))
        finally:timer.stop()
        self.assertGreater(len(ticks),5)
        self.assertIn('OLD TEXT',PdfReader(BytesIO(result['data'])).pages[0].extract_text())

    def test_cancel_before_job_leaves_document_unchanged(self):
        model=Document();model.import_bytes('sample.pdf',text_fixture());fingerprint=model.fingerprint()
        with self.assertRaises(JobCancelled):
            process_job(snapshot(model),'assemble',{},lambda *args:True,lambda:True)
        self.assertEqual(model.fingerprint(),fingerprint)
