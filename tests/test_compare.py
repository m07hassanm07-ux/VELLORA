import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from io import BytesIO
import unittest
from pypdf import PdfWriter
from waraq.compare import compare_pdfs
from waraq.core import Overlay
from waraq.rendering import text_overlay


class CompareTests(unittest.TestCase):
    def test_identical_changed_and_added_pages(self):
        plain=text_overlay(300,400,Overlay('Version one','center',22))
        changed=text_overlay(300,400,Overlay('Version two','center',22))
        same=compare_pdfs(plain,plain,dpi=72)
        self.assertEqual(same[0].status,'same')
        different=compare_pdfs(plain,changed,dpi=72)
        self.assertEqual(different[0].status,'changed');self.assertLess(different[0].text_similarity,1)
        writer=PdfWriter();writer.append(BytesIO(plain));writer.add_blank_page(300,400);stream=BytesIO();writer.write(stream)
        added=compare_pdfs(plain,stream.getvalue(),dpi=72)
        self.assertEqual(added[1].status,'added')


if __name__=='__main__':unittest.main()
