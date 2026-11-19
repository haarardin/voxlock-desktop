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


def test_loading_can_be_cancelled_without_starting_audio(monkeypatch):
    from voxlock_desktop import ui
    from voxlock_desktop.engine import IsolationWorker
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.input_combo.clear()
    window.input_combo.addItem("Mock microphone", "mock")
    window.auto_mode.setChecked(True)
    monkeypatch.setattr(ui, "is_linux", lambda: True)
    monkeypatch.setattr(IsolationWorker, "start", lambda worker: None)
    window.start_processing()
    assert window.start_button.isEnabled()
    assert "Отменить" in window.start_button.text()
    assert window.worker is not None
    window.stop_processing()
    assert window.worker.cancelled.is_set()
    # A delayed ready signal must not reactivate the already cancelled worker.
    window._processing_ready("Mock virtual microphone")
    assert "Защита включена" not in window.status.text()
    window._worker_finished()
    assert window.worker is None
    assert window.start_button.isEnabled()
    if window.tray:
        window.tray.hide()
    window.deleteLater()
    app.processEvents()
