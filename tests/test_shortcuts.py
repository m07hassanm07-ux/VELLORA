import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtGui import QKeySequence
from waraq.shortcuts import portable_shortcut,validate_shortcut_map


class ShortcutTests(unittest.TestCase):
    def test_portable_normalization_and_empty_disabled_shortcut(self):
        self.assertEqual(portable_shortcut(QKeySequence('Ctrl+Shift+O')),'Ctrl+Shift+O')
        self.assertEqual(validate_shortcut_map({'open':'Ctrl+O','disabled':''})['disabled'],'')

    def test_duplicate_shortcuts_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'مستخدم لأمرين'):
            validate_shortcut_map({'open':'Ctrl+O','other':'Ctrl+O'})


if __name__=='__main__':unittest.main()
