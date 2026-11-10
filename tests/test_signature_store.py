from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QApplication

from waraq.app import SignatureCanvas
from waraq.signature_store import SignatureStore


class VisualSignatureStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_encrypted_signature_lifecycle(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'library.vsig';store=SignatureStore(path)
            image=QImage(180,70,QImage.Format.Format_ARGB32_Premultiplied);image.fill(QColor('#172a32'))
            identifier=store.save('توقيع المدير',image)
            self.assertEqual(store.list()[0]['id'],identifier);self.assertFalse(store.image(identifier).isNull())
            raw=path.read_bytes();self.assertNotIn('توقيع المدير'.encode('utf-8'),raw);self.assertNotIn(b'PNG',raw)
            store.rename(identifier,'توقيع معتمد');self.assertEqual(store.list()[0]['name'],'توقيع معتمد')
            store.delete(identifier);self.assertEqual(store.list(),[])

    def test_drawing_canvas_creates_transparent_ink_image(self):
        canvas=SignatureCanvas();canvas.resize(620,240)
        canvas.draw_to(QPointF(40,80));canvas.draw_to(QPointF(300,130));canvas.last=None
        self.assertTrue(canvas.has_ink());self.assertGreater(canvas.image.pixelColor(80,160).alpha(),0)
        canvas.clear();self.assertFalse(canvas.has_ink());canvas.close()


if __name__=='__main__':unittest.main()
