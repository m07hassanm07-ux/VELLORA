from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import os

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication

from pypdf import PdfReader, PdfWriter

from waraq.batch_workflows import (execute_workflow, load_workflows,
                                   save_workflows, validate_workflow)

APP=QApplication.instance() or QApplication([])


def pdf_file(path, pages=1):
    writer=PdfWriter()
    for _ in range(pages):writer.add_blank_page(300,400)
    with open(path,'wb') as stream:writer.write(stream)
    writer.close()


class BatchWorkflowTests(unittest.TestCase):
    def test_workflows_roundtrip_validation_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'workflows.json'
            item={'name':'أرشفة','merge':True,'rotation':90,'watermark':'داخلي','numbering':True}
            save_workflows([item],target);self.assertEqual(load_workflows(target),[validate_workflow(item)])
            with self.assertRaises(ValueError):save_workflows([item,item],target)
            with self.assertRaises(ValueError):validate_workflow({'name':'bad','rotation':45})

    def test_execute_merged_and_individual_workflows(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=root/'a.pdf';second=root/'b.pdf';pdf_file(first,2);pdf_file(second,1)
            out=root/'out';events=[]
            merged=execute_workflow([first,second],out,{'name':'Combined','merge':True,'rotation':90,
                'watermark':'Internal','numbering':True},lambda *args:events.append(args))
            self.assertEqual(len(merged),1);reader=PdfReader(merged[0]);self.assertEqual(len(reader.pages),3)
            self.assertEqual(reader.pages[0].rotation,90);self.assertEqual(len(events),2)
            separate=execute_workflow([first,second],out,{'name':'Copies','merge':False,'rotation':0,
                'watermark':'','numbering':False})
            self.assertEqual(len(separate),2);self.assertTrue(all(path.is_file() for path in separate))


if __name__=='__main__':unittest.main()
