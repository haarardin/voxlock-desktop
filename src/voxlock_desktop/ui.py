"""PySide6 desktop UI, styled after the VoxLock concept screen."""
from __future__ import annotations

from collections import deque
from pathlib import Path
import platform

from PySide6.QtCore import Qt, QSettings, QUrl, QRectF
from PySide6.QtGui import QAction, QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .devices import is_linux, list_inputs, list_outputs
from .engine import EnrollmentWorker, IsolationWorker, data_directory, profile_file
from .style import QSS

GREEN = "#38db9f"
BG = "#10151e"


def label(text: str, kind: str = "") -> QLabel:
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    widget.setWordWrap(True)
    return widget


def card(title: str | None = None, hero: bool = False) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("hero" if hero else "panel")
    inner = QVBoxLayout(frame)
    inner.setContentsMargins(20, 18, 20, 18)
    inner.setSpacing(12)
    if title:
        inner.addWidget(label(title, "section"))
    return frame, inner


def button(text: str, kind: str = "") -> QPushButton:
    result = QPushButton(text)
    if kind:
        result.setObjectName(kind)
    result.setCursor(Qt.PointingHandCursor)
    return result


def add_row(layout: QVBoxLayout, title: str, control: QWidget, note: str = ""):
    layout.addWidget(label(title, "muted"))
    layout.addWidget(control)
    if note:
        layout.addWidget(label(note, "small"))


class LevelGraph(QWidget):
    """RMS history, not an invented or simulated waveform."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.history = deque([0.0] * 66, maxlen=66)
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def push(self, level: float):
        self.history.append(max(0.02, min(1.0, (level + 70.0) / 60.0)))
        self.update()

    def reset(self):
        self.history = deque([0.0] * 66, maxlen=66)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid = h / 2
        painter.setPen(QPen(QColor("#344253"), 1))
        painter.drawLine(0, int(mid), w, int(mid))
        bars = list(self.history)
        bar_step = w / max(1, len(bars))
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        for i, value in enumerate(bars):
            height = max(2, value * (h - 15) * 0.85)
            painter.drawRoundedRect(
                QRectF(i * bar_step + 1, mid - height / 2,
                       max(2.5, bar_step - 3), height), 2, 2
            )
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("VoxLock", "VoxLockDesktop")
        self.worker: IsolationWorker | None = None
        self.recorder: EnrollmentWorker | None = None
        self.preview_paths: tuple[str, str] | None = None
        self._quit_requested = False
        self.setWindowTitle("VoxLock Desktop")
        self.resize(1320, 900)
        self.setMinimumSize(950, 690)
        self.setStyleSheet(QSS)
        self._build()
        self._configure_tray()
        self.refresh_devices()
        self.refresh_profile()

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 15, 24, 15)
        hl.addWidget(label("◉  VoxLock Desktop", "brand"))
        hl.addSpacing(20)
        self.status = label("●  Обработка выключена", "muted")
        hl.addWidget(self.status)
        hl.addStretch()
        hl.addWidget(label("⌁  Локально · " + platform.system(), "muted"))
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, stretch=1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 20, 12, 18)
        sl.setSpacing(7)
        self.nav_buttons: list[QPushButton] = []
        for text, index in [
            ("◉   Микрофон", 0),
            ("♙   Мой голос", 1),
            ("⚙   Настройки", 2),
            ("ⓘ   О приложении", 3),
        ]:
            nav = button(text, "nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            self.nav_buttons.append(nav)
            sl.addWidget(nav)
        sl.addStretch()
        sl.addWidget(label("VoxLock · ONNX · 16 kHz", "small"))
        sl.addWidget(label("Никаких облачных записей", "small"))
        body.addWidget(sidebar)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, stretch=1)
        self.pages.addWidget(self._dashboard())
        self.pages.addWidget(self._profile_page())
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._about_page())
        self.navigate(0)

    def _dashboard(self) -> QWidget:
        wrapper = self._scroll_page()
        layout = wrapper.layout()

        hero, h = card(hero=True)
        titlebar = QHBoxLayout()
        head = QVBoxLayout()
        head.addWidget(label("Изоляция голоса", "heading"))
        head.addWidget(label(
            "Только ваш голос — посторонние разговоры подавляются нейросетью VoxLock.",
            "muted"
        ))
        titlebar.addLayout(head, stretch=1)
        self.start_button = button("▶  Начать обработку", "primary")
        self.start_button.clicked.connect(self.toggle_processing)
        titlebar.addWidget(self.start_button)
        h.addLayout(titlebar)
        layout.addWidget(hero)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        layout.addLayout(columns)
        center = QVBoxLayout()
        center.setSpacing(14)
        columns.addLayout(center, stretch=7)
        side = QVBoxLayout()
        side.setSpacing(14)
        columns.addLayout(side, stretch=3)

        devices, dv = card("Устройства")
        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        add_row(dv, "Входной микрофон", self.input_combo,
                "Физический микрофон: USB, Bluetooth или встроенный")
        add_row(dv, "Выход / виртуальный микрофон", self.output_combo,
                "Linux: создаётся автоматически · Windows: выберите CABLE Input")
        self.refresh_button = button("↻  Обновить список устройств")
        self.refresh_button.clicked.connect(self.refresh_devices)
        dv.addWidget(self.refresh_button)
        center.addWidget(devices)

        profile, pv = card("Голосовой профиль")
        self.profile_status = label("", "muted")
        pv.addWidget(self.profile_status)
        self.auto_mode = QCheckBox("Автоматически определить первого говорящего")
        self.auto_mode.setChecked(False)
        self.auto_mode.toggled.connect(self._refresh_profile_hint)
        pv.addWidget(self.auto_mode)
        self.profile_hint = label("", "small")
        pv.addWidget(self.profile_hint)
        pr = QHBoxLayout()
        self.record_button = button("●  Записать образец (8 секунд)")
        self.record_button.clicked.connect(self.toggle_enrollment)
        pr.addWidget(self.record_button)
        pv.addLayout(pr)
        self.record_progress = QProgressBar()
        self.record_progress.setValue(0)
        self.record_progress.hide()
        pv.addWidget(self.record_progress)
        center.addWidget(profile)

        before, bv = card("Исходный звук")
        bv.addWidget(label("Микрофон: голос, фон и другие собеседники", "small"))
        self.input_graph = LevelGraph("#b78bd4")
        bv.addWidget(self.input_graph)
        self.input_level = label("−∞ dBFS", "muted")
        bv.addWidget(self.input_level)
        center.addWidget(before)

        after, av = card("После изоляции")
        av.addWidget(label("Из виртуального микрофона передаётся обработанный звук", "small"))
        self.output_graph = LevelGraph(GREEN)
        av.addWidget(self.output_graph)
        self.output_level = label("−∞ dBFS", "muted")
        av.addWidget(self.output_level)
        center.addWidget(after)

        preview, pv = card("Проверка качества")
        self.preview_button = button("◉  Записать сравнение (5 секунд)")
        self.preview_button.clicked.connect(self.request_preview)
        pv.addWidget(self.preview_button)
        self.before_button = button("▶  Открыть исходную запись")
        self.after_button = button("▶  Открыть обработанную запись")
        self.before_button.clicked.connect(lambda: self.open_preview(0))
        self.after_button.clicked.connect(lambda: self.open_preview(1))
        self.before_button.setEnabled(False)
        self.after_button.setEnabled(False)
        pv.addWidget(self.before_button)
        pv.addWidget(self.after_button)
        self.performance = label("Модель: 24 мс алгоритмической задержки; полная задержка не измерена", "small")
        pv.addWidget(self.performance)
        center.addWidget(preview)

        how, hw = card("Как это работает")
        for number, name, explanation in [
            ("01", "Микрофон", "Захват речи и окружающих звуков"),
            ("↓", "VoxLock AI", "Выделение голоса по эталону"),
            ("03", "Виртуальный микрофон", "Обработанный звук для любых звонков"),
        ]:
            step, st = card()
            st.addWidget(label(f"{number}   {name}", "section"))
            st.addWidget(label(explanation, "small"))
            hw.addWidget(step)
        hw.addWidget(label(
            "Обработка выполняется на вашем CPU. Звуковые записи сохраняются "
            "только при явном запросе.", "muted"
        ))
        side.addWidget(how)

        help_card, hp = card("Подключение")
        self.connection_help = label(
            "Linux: выберите VoxLock_Microphone в Discord, Telegram или браузере."
            if is_linux() else
            "Windows: установите VB-CABLE, в приложении выберите CABLE Input "
            "(воспроизведение), а в Discord — CABLE Output (запись).",
            "muted"
        )
        hp.addWidget(self.connection_help)
        side.addWidget(help_card)

        state, sp = card("Состояние")
        self.message = label("Ожидание. Выберите микрофон и запишите образец голоса.", "muted")
        sp.addWidget(self.message)
        side.addWidget(state)
        side.addStretch()
        return wrapper

    def _scroll_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 18, 20, 22)
        layout.setSpacing(15)
        scroll.setWidget(content)
        return scroll

    def _information_page(self, title: str, subtitle: str) -> tuple[QScrollArea, QVBoxLayout]:
        page = self._scroll_page()
        layout = page.widget().layout()
        layout.addWidget(label(title, "heading"))
        layout.addWidget(label(subtitle, "muted"))
        return page, layout

    def _profile_page(self):
        page, layout = self._information_page(
            "Мой голос", "Образец голоса позволяет VoxLock выделять именно вас."
        )
        p, pv = card("Как записать профиль")
        pv.addWidget(label(
            "1. Выберите микрофон на вкладке «Микрофон».\n"
            "2. В тихой комнате произнесите несколько предложений в течение 8 секунд.\n"
            "3. Вернитесь на главную вкладку и нажмите «Начать обработку».",
            "muted"
        ))
        btn = button("Перейти к записи голоса", "primary")
        btn.clicked.connect(lambda: self.navigate(0))
        pv.addWidget(btn)
        layout.addWidget(p)
        location, lv = card("Расположение записи")
        self.profile_location = label(str(profile_file()), "muted")
        self.profile_location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lv.addWidget(self.profile_location)
        open_btn = button("Открыть папку с профилем")
        open_btn.clicked.connect(lambda: self.open_directory(profile_file().parent))
        lv.addWidget(open_btn)
        layout.addWidget(location)
        layout.addStretch()
        return page

    def _settings_page(self):
        page, layout = self._information_page(
            "Настройки", "Управление подключением и локальными файлами."
        )
        details, dl = card("Платформенный аудиовыход")
        dl.addWidget(label(
            "Linux: требуется PipeWire с pipewire-pulse (либо PulseAudio), "
            "pactl, parec и pacat. Виртуальный источник появляется только "
            "когда запущена обработка.\n\n"
            "Windows: требуется VB-CABLE или другое виртуальное аудиоустройство. "
            "VoxLock выводит звук в выбранный playback endpoint; драйвер не "
            "устанавливается приложением.", "muted"
        ))
        layout.addWidget(details)
        privacy, pl = card("Конфиденциальность")
        pl.addWidget(label(
            "Модель работает локально. При первом запуске VoxLock может скачать "
            "модель ONNX из Hugging Face (~74 MB); микрофон в облако не отправляется. "
            "Профиль и записи проверки хранятся локально.", "muted"
        ))
        open_btn = button("Открыть локальные данные")
        open_btn.clicked.connect(lambda: self.open_directory(data_directory()))
        pl.addWidget(open_btn)
        layout.addWidget(privacy)
        layout.addStretch()
        return page

    def _about_page(self):
        page, layout = self._information_page(
            "О VoxLock Desktop", "Открытый GUI-клиент для нейросетевой изоляции голоса."
        )
        info, il = card("Компоненты")
        il.addWidget(label(
            "Интерфейс: Python + PySide6\n"
            "Выделение голоса: VoxLock (Apache 2.0)\n"
            "Инференс: ONNX Runtime, INT8\n"
            "Linux: PulseAudio / PipeWire\n"
            "Windows: PortAudio и сторонний виртуальный кабель", "muted"
        ))
        link = button("Исходники VoxLock ↗")
        link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/arbazsiddiqui/voxlock"))
        )
        il.addWidget(link)
        layout.addWidget(info)
        layout.addStretch()
        return page

    def navigate(self, index: int):
        self.pages.setCurrentIndex(index)
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)

    def _configure_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        from PySide6.QtWidgets import QStyle
        icon = self.style().standardIcon(QStyle.SP_MediaVolume)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        open_action = QAction("Показать VoxLock", self)
        open_action.triggered.connect(self._show_from_tray)
        menu.addAction(open_action)
        stop_action = QAction("Остановить обработку", self)
        stop_action.triggered.connect(self.stop_processing)
        menu.addAction(stop_action)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.quit_app)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_from_tray()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.setToolTip("VoxLock Desktop")
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh_devices(self):
        self.input_combo.clear()
        self.output_combo.clear()
        try:
            inputs, outputs = list_inputs(), list_outputs()
            for item in inputs:
                self.input_combo.addItem(item.label, item.key)
            for item in outputs:
                self.output_combo.addItem(item.label, item.key)
            desired_input = self.settings.value("input", "")
            desired_output = self.settings.value("output", "")
            for combo, saved in ((self.input_combo, desired_input),
                                 (self.output_combo, desired_output)):
                pos = combo.findData(saved)
                if pos >= 0:
                    combo.setCurrentIndex(pos)
            if not is_linux() and self.output_combo.count():
                if self.output_combo.findData(desired_output) < 0:
                    for i in range(self.output_combo.count()):
                        if "CABLE Input" in self.output_combo.itemText(i):
                            self.output_combo.setCurrentIndex(i)
                            break
            self.message.setText(
                f"Обнаружено микрофонов: {len(inputs)}. "
                "Проверьте выбранное устройство перед запуском."
            )
        except Exception as exc:
            self.message.setText(f"Ошибка поиска устройств: {exc}")

    def refresh_profile(self):
        path = profile_file()
        if path.exists():
            self.profile_status.setText("✓  Основной профиль · образец записан")
        else:
            self.profile_status.setText("○  Профиль не записан")
        self._refresh_profile_hint()

    def _refresh_profile_hint(self):
        if self.auto_mode.isChecked():
            self.profile_hint.setText(
                "Внимание: первые секунды передаются без фильтра; "
                "первым говорящим может оказаться другой человек."
            )
        else:
            self.profile_hint.setText(
                "Рекомендуется для подавления чужих голосов. "
                "VoxLock сравнивает речь с вашим образцом."
            )

    def toggle_enrollment(self):
        if self.recorder and self.recorder.isRunning():
            self.recorder.cancel()
            self.record_button.setEnabled(False)
            return
        if self.worker and self.worker.isRunning():
            self.notify("Сначала остановите обработку.")
            return
        microphone = self.input_combo.currentData()
        if microphone is None:
            self.notify("Выберите входной микрофон.")
            return
        self.recorder = EnrollmentWorker(microphone, parent=self)
        self.recorder.progress.connect(self.record_progress.setValue)
        self.recorder.success.connect(self._enrollment_ready)
        self.recorder.failure.connect(lambda msg: self.notify("Запись не удалась: " + msg))
        self.recorder.finished.connect(self._enrollment_done)
        self.record_progress.setValue(0)
        self.record_progress.show()
        self.record_button.setText("■  Отменить запись")
        self.recorder.start()
        self.notify("Говорите обычным голосом на протяжении 8 секунд.")

    def _enrollment_ready(self, path: str):
        self.refresh_profile()
        self.notify("Голосовой профиль сохранён локально: " + path)

    def _enrollment_done(self):
        self.record_button.setEnabled(True)
        self.record_button.setText("●  Перезаписать образец (8 секунд)")
        self.record_progress.hide()
        self.recorder = None

    def toggle_processing(self):
        if self.worker and self.worker.isRunning():
            self.stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        if self.worker and self.worker.isRunning():
            return
        if self.recorder and self.recorder.isRunning():
            self.notify("Завершите запись голосового профиля.")
            return
        microphone = self.input_combo.currentData()
        if microphone is None:
            self.notify("Входной микрофон не выбран.")
            return
        if is_linux():
            output = None
        else:
            output = self.output_combo.currentData()
            if output is None:
                self.notify("Выберите виртуальный выход, например CABLE Input (VB-CABLE).")
                return
            if output == microphone:
                self.notify("Входной и выходной аудиоустройства должны различаться.")
                return
        sample = None if self.auto_mode.isChecked() else str(profile_file())
        if sample and not Path(sample).exists():
            self.notify("Сначала запишите образец голоса или выберите автоматический режим.")
            return
        self.settings.setValue("input", microphone)
        self.settings.setValue("output", output or "")
        self.worker = IsolationWorker(microphone, output, sample, parent=self)
        self.worker.ready.connect(self._processing_ready)
        self.worker.levels.connect(self._levels)
        self.worker.performance.connect(self.performance.setText)
        self.worker.preview_saved.connect(self._preview_saved)
        self.worker.error.connect(lambda msg: self.notify("Ошибка обработки: " + msg, error=True))
        self.worker.stopped.connect(self._processing_stopped)
        self.worker.finished.connect(self._worker_finished)
        self.start_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.input_combo.setEnabled(False)
        self.output_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.auto_mode.setEnabled(False)
        self.status.setText("◌  Загрузка модели / подключение...")
        self.notify("При первом запуске модель может скачиваться из интернета.")
        self.worker.start()

    def _processing_ready(self, source: str):
        self.status.setText("●  Защита включена")
        self.status.setObjectName("ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.start_button.setText("■  Остановить обработку")
        self.start_button.setObjectName("danger")
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.start_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.notify("Активно. В приложениях выберите: " + source)

    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.start_button.setEnabled(False)
            self.status.setText("◌  Остановка...")
            self.worker.stop()

    def _processing_stopped(self):
        self.status.setText("●  Обработка выключена")
        self.status.setObjectName("muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.start_button.setText("▶  Начать обработку")
        self.start_button.setObjectName("primary")
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.start_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.auto_mode.setEnabled(True)
        self.preview_button.setEnabled(False)

    def _worker_finished(self):
        self.worker = None
        if self._quit_requested:
            QApplication.instance().quit()

    def _levels(self, before: float, after: float):
        self.input_graph.push(before)
        self.output_graph.push(after)
        self.input_level.setText(f"{before:.0f} dBFS")
        self.output_level.setText(f"{after:.0f} dBFS")

    def request_preview(self):
        if not self.worker or not self.worker.isRunning():
            self.notify("Сначала запустите обработку.")
            return
        self.worker.request_preview()
        self.preview_button.setEnabled(False)
        self.notify("Сохраняется 5-секундная запись до и после обработки.")

    def _preview_saved(self, before: str, after: str):
        self.preview_paths = before, after
        self.before_button.setEnabled(True)
        self.after_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.notify("Записи сохранены. Откройте их кнопками для прослушивания.")

    def open_preview(self, index: int):
        if self.preview_paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.preview_paths[index]))

    def open_directory(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def notify(self, message: str, error: bool = False):
        self.message.setText(message)
        self.message.setObjectName("warning" if error else "muted")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def quit_app(self):
        self._quit_requested = True
        if self.recorder and self.recorder.isRunning():
            self.recorder.cancel()
            self.recorder.wait(3000)
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.hide()
            return  # finish callback exits after worker closes
        QApplication.instance().quit()

    def closeEvent(self, event):
        if not self._quit_requested and self.tray and self.tray.isVisible():
            self.hide()
            self.tray.showMessage(
                "VoxLock Desktop", "Приложение продолжает работать в трее.",
                QSystemTrayIcon.Information, 1500
            )
            event.ignore()
        else:
            self.quit_app()
            if self.worker and self.worker.isRunning():
                event.ignore()
            else:
                event.accept()
