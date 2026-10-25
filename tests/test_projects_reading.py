from io import BytesIO
from pathlib import Path
import json, os, tempfile, unittest
from pypdf import PdfReader, PdfWriter
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication
from test_editing import text_fixture
from waraq.core import Document, Overlay
from waraq.projects import snapshot,restore,encode_snapshot,decode_snapshot,RecoveryStore,LOCAL
from waraq.textlayout import character_map, select_region, find_matches
from waraq.app import MainWindow
from waraq.rendering import ensure_font_support
from qt_helpers import wait_for


class ProjectsReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);ensure_font_support()

    def model(self):
        model=Document();model.import_bytes('sample.pdf',text_fixture());model.mark_saved()
        model.duplicate([0]);model.add_overlay([1],Overlay('test'));model.rotate([0],90)
        return model

    def test_project_embeds_sources_history_and_metadata(self):
        model=self.model();state=snapshot(model);data=encode_snapshot(state)
        loaded=restore(decode_snapshot(data))
        self.assertEqual(loaded.fingerprint(),model.fingerprint());self.assertTrue(loaded.dirty)
        loaded.undo();model.undo();self.assertEqual(loaded.fingerprint(),model.fingerprint())
        loaded.redo();model.redo();self.assertEqual(loaded.fingerprint(),model.fingerprint())

    def test_protected_sources_require_encrypted_project_and_reject_wrong_password(self):
        writer=PdfWriter();writer.append(PdfReader(BytesIO(text_fixture())));writer.encrypt('source-secret',algorithm='AES-256')
        stream=BytesIO();writer.write(stream);model=Document();model.import_bytes('secret.pdf',stream.getvalue(),'source-secret')
        with self.assertRaises(ValueError):encode_snapshot(snapshot(model))
        encrypted=encode_snapshot(snapshot(model),password='project-secret')
        self.assertNotIn(b'source-secret',encrypted);self.assertNotIn(b'project-secret',encrypted)
        with self.assertRaises(ValueError):decode_snapshot(encrypted,'wrong')
        loaded=restore(decode_snapshot(encrypted,'project-secret'))
        self.assertIn('OLD TEXT',PdfReader(BytesIO(loaded.build_bytes())).pages[0].extract_text())

    @unittest.skipUnless(os.name=='nt','DPAPI is Windows-specific')
    def test_recovery_is_user_encrypted_and_preserves_other_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            a=RecoveryStore(folder);b=RecoveryStore(folder);model=self.model()
            a.write(snapshot(model));payload=a.path.read_bytes()
            self.assertTrue(payload.startswith(LOCAL));self.assertNotIn(b'OLD TEXT',payload)
            self.assertEqual(restore(decode_snapshot(payload)).fingerprint(),model.fingerprint())
            self.assertEqual(b.candidates(),[])  # live process is not a crashed session
            a.path.with_suffix('.json').write_text(json.dumps({'pid':0}))
            self.assertEqual(b.candidates(),[a.path])
            sentinel=Path(folder)/'user-note.txt';sentinel.write_text('keep')
            b.clear();self.assertTrue(a.path.exists());a.clear();self.assertTrue(sentinel.exists())

    def test_region_selection_and_rotated_geometry(self):
        data=text_fixture();glyphs=character_map(data)[2]
        text,rects,ids=select_region(glyphs,(30,60,180,45))
        self.assertEqual(text,'OLD TEXT');self.assertTrue(rects);self.assertTrue(ids)
        rotated=text_fixture(rotation=90)
        match=find_matches(rotated,'OLD')[0]
        # Rotated page is 800 x 500, so original top text appears at the right.
        self.assertGreater(match['rects'][0][0],650)
        self.assertLess(match['rects'][0][1],100)

    def test_main_window_search_selection_and_clipboard(self):
        window=MainWindow();window.document.import_bytes('sample.pdf',text_fixture());window.refresh()
        window.render_current();wait_for(lambda:bool(window.current_glyphs));window.select_page_text(QRectF(30,60,180,45))
        self.assertEqual(window.selected_text,'OLD TEXT')
        window.copy_selected_text();self.assertEqual(self.app.clipboard().text(),'OLD TEXT')
        window.search_document('keep');self.assertEqual(len(window.search_matches),1)
        self.assertEqual(window.pending_match[0],0)
        window.document.mark_saved();window.close()
