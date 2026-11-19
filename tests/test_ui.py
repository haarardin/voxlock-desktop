"""Offscreen UI smoke test: verify all pages and controls can be constructed."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from voxlock_desktop.ui import MainWindow


def test_window_construction_and_navigation():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.pages.count() == 4
    assert window.start_button.text()
    assert window.record_button.text()
    window.navigate(1)
    assert window.pages.currentIndex() == 1
    window.navigate(0)
    assert window.pages.currentIndex() == 0
    window.tray.hide() if window.tray else None
    window.deleteLater()
    app.processEvents()
