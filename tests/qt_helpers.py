import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


def wait_for(predicate,timeout=20000):
    deadline=time.monotonic()+timeout/1000
    while time.monotonic()<deadline:
        QApplication.processEvents()
        if predicate():return
        QTest.qWait(20)
    raise AssertionError('Timed out waiting for asynchronous UI result')
