"""Main application window: sidebar navigation + lazily-built, cached pages.

Mirrors SubGenApp's `cached_pages`/`_switch_page` semantics (subgen.py:1931-1994):
each page is built exactly once on first visit and reused after that, via
QStackedWidget instead of pack/pack_forget.
"""
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QObject, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QButtonGroup, QSizePolicy, QFrame,
    QApplication, QComboBox, QAbstractSpinBox, QSlider, QScrollArea,
)

from .backend.device import DEVICE_LABEL, DEVICE_COLOR, DEVICE, COMPUTE_TYPE, GPU_NAME
from .backend.eventlog import log_event
from .backend.transcribe import BACKEND
from .config import APP_NAME, APP_VER, LOGO_PATH, ICON_PATH, DARK_BG, PANEL_BG, BORDER_COLOR, ACCENT, TEXT_MAIN, TEXT_SUB, MODEL_SIZES, WARNING, SUCCESS, INPUT_BG, ACCENT_CYAN
from .icons import get_bs_icon
from .paths import FFMPEG_PATH
from .state import AppState
from .widgets.styles import DIALOG_STYLE
from .workers import TelemetryWorker, UpdateCheckWorker


class ScrollWheelFilter(QObject):
    """Event filter that prevents mouse wheel from inadvertently changing values
    on QComboBox, QAbstractSpinBox, and QSlider widgets while scrolling through pages."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            if isinstance(obj, (QComboBox, QAbstractSpinBox, QSlider)):
                parent = obj.parentWidget()
                while parent:
                    if isinstance(parent, QScrollArea):
                        QApplication.sendEvent(parent.viewport(), event)
                        return True
                    parent = parent.parentWidget()
                event.ignore()
                return True
        return super().eventFilter(obj, event)

# (label, page_name, bootstrap-icon-name) — icon choices match subgen.py's
# nav_items (subgen.py:1828-1837, 1873-1874).
NAV_ITEMS = [
    ("Dashboard", "Dashboard", "speedometer2"),
    ("Transcribe", "Transcribe", "mic-fill"),
    ("Batch Processing", "Batch Processing", "collection-play-fill"),
    ("Models", "Models", "cpu-fill"),
    ("History", "History", "clock-history"),
    ("Telemetry", "Telemetry", "bar-chart-line-fill"),
    ("Logs", "Logs", "file-earmark-code-fill"),
    ("App Settings", "App Settings", "gear-fill"),
]
FOOTER_NAV_ITEMS = [
    ("Help & Support", "Help & Support", "question-circle-fill"),
    ("About", "About", "info-circle-fill"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} Studio  v{APP_VER}")
        self.resize(1280, 800)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        from .widgets.dialogs import patch_qmessagebox
        from .widgets.styles import enable_dark_titlebar
        patch_qmessagebox()
        enable_dark_titlebar(self)

        app = QApplication.instance()
        if app is not None:

            self._wheel_filter = ScrollWheelFilter(self)
            app.installEventFilter(self._wheel_filter)
            app.setStyleSheet(DIALOG_STYLE)


        self._page_cache: dict[str, QWidget] = {}
        self._page_builders: dict[str, callable] = {}
        self.nav_buttons: dict[str, QPushButton] = {}

        # Shared across every page (mirrors subgen.py's shared src_lang_var/
        # tgt_lang_var/model_var StringVars used by both Quick and Settings tabs).
        self.state = AppState(model_default=MODEL_SIZES[0])

        # Read by TelemetryWorker to pick its simulated GPU-load/temperature
        # range, mirroring the original's `getattr(self, "running", False)`
        # (subgen.py:3547). Set via set_busy() below by TranscribePage/BatchPage
        # around a run, which also drives the footer's Elapsed label.
        self.is_busy = False
        self._job_start_time = None

        # One long-lived poller for the app's lifetime, matching
        # _start_live_telemetry's rationale (subgen.py:3510-3517): avoid
        # spawning a new thread every second.
        self.telemetry_worker = TelemetryWorker(is_busy=lambda: self.is_busy)
        self.telemetry_worker.start()

        log_event(f"SubTranscribe v{APP_VER} initialized cleanly.")
        log_event(f"Backend detected: {BACKEND}")
        log_event(f"Device compute mode: {DEVICE} ({COMPUTE_TYPE})")
        log_event(f"GPU Name: {GPU_NAME or 'None detected'}")
        log_event(f"FFmpeg Binary: {FFMPEG_PATH or 'Not Found'}")
        log_event("System Status: All Systems Operational.")

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        # sidebar | (header, stack, footer) — header/footer are global chrome
        # visible on every page, matching image/dashboard.png etc.
        main_col = QVBoxLayout()
        main_col.setContentsMargins(0, 0, 0, 0)
        main_col.setSpacing(0)
        root_layout.addLayout(main_col, 1)

        main_col.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {DARK_BG};")
        main_col.addWidget(self.stack, 1)

        main_col.addWidget(self._build_footer())

        from .pages.dashboard import DashboardPage
        from .pages.transcribe import TranscribePage
        from .pages.batch import BatchPage
        from .pages.models import ModelsPage
        from .pages.history import HistoryPage
        from .pages.telemetry import TelemetryPage
        from .pages.logs import LogsPage
        from .pages.settings import SettingsPage
        from .pages.help import HelpPage
        from .pages.about import AboutPage

        self.register_page("Dashboard", lambda w, n: DashboardPage(w))
        self.register_page("Transcribe", lambda w, n: TranscribePage(w))
        self.register_page("Batch Processing", lambda w, n: BatchPage(w))
        self.register_page("Models", lambda w, n: ModelsPage(w))
        self.register_page("History", lambda w, n: HistoryPage(w))
        self.register_page("Telemetry", lambda w, n: TelemetryPage(w))
        self.register_page("Logs", lambda w, n: LogsPage(w))
        self.register_page("App Settings", lambda w, n: SettingsPage(w))
        self.register_page("Help & Support", lambda w, n: HelpPage(w))
        self.register_page("About", lambda w, n: AboutPage(w))

        self.switch_page("Dashboard")

        # Silent startup update check, mirroring _check_for_update_bg
        # (subgen.py:3260-3267) — only touches the UI if a newer release
        # actually exists.
        self._update_found = None
        self._update_dialog = None
        self._update_popup_shown = False
        self._update_check_worker = UpdateCheckWorker()
        self._update_check_worker.result.connect(self._on_startup_update_result)
        self._update_check_worker.start()

    def _on_startup_update_result(self, found):
        if not found:
            return
        latest, url, notes, assets = found
        self._update_found = found
        self.ver_badge_btn.setText(f"Update v{latest} available")
        self.ver_badge_btn.setVisible(True)
        if not self._update_popup_shown:
            self._update_popup_shown = True
            QTimer.singleShot(1500, lambda: self.show_update_dialog(*found))

    def show_update_dialog(self, latest, url, notes, assets):
        """Mechanical port of SubGenApp._show_update_popup's single-instance
        guard (subgen.py:3291-3293) — reuse via .raise_() if already open."""
        from .update_dialog import UpdateDialog
        if self._update_dialog is not None:
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return
        dlg = UpdateDialog(latest, url, notes, assets, parent=self)
        dlg.finished.connect(lambda _: setattr(self, "_update_dialog", None))
        self._update_dialog = dlg
        dlg.show()

    def set_busy(self, busy: bool):
        """Pages call this instead of setting main_window.is_busy directly —
        drives both TelemetryWorker's simulated load range and the footer's
        Elapsed label (mirrors _tick_elapsed's per-job timing, subgen.py:4131-4146,
        rather than app-uptime)."""
        self.is_busy = busy
        self._job_start_time = time.time() if busy else self._job_start_time

    def closeEvent(self, event):
        self.telemetry_worker.stop()
        self.telemetry_worker.wait(2000)
        for page in self._page_cache.values():
            player = getattr(page, "audio_player", None)
            if player is not None:
                player.stop()
        # Best-effort background startup check (network call, up to 8s
        # timeout) — don't hang shutdown waiting on it; force-stop if it
        # hasn't finished quickly, since a QThread must not outlive its
        # Python wrapper object.
        if self._update_check_worker.isRunning():
            if not self._update_check_worker.wait(300):
                self._update_check_worker.terminate()
                self._update_check_worker.wait()
        super().closeEvent(event)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet(f"background-color: {PANEL_BG}; border-right: 1px solid {BORDER_COLOR};")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(4)

        header = QHBoxLayout()
        if LOGO_PATH.exists():
            from PySide6.QtGui import QPixmap
            logo_lbl = QLabel()
            logo_lbl.setPixmap(QPixmap(str(LOGO_PATH)).scaledToHeight(28, Qt.SmoothTransformation))
            header.addWidget(logo_lbl)
        title_lbl = QLabel(APP_NAME)
        title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 16px; font-weight: 700;")
        header.addWidget(title_lbl)
        header.addStretch(1)
        layout.addLayout(header)

        # Hidden until _on_startup_update_result finds a newer release —
        # Qt port of SubGenApp's ver_badge/ver_badge_lbl (subgen.py:3269-3280).
        self.ver_badge_btn = QPushButton("")
        self.ver_badge_btn.setVisible(False)
        self.ver_badge_btn.setCursor(Qt.PointingHandCursor)
        self.ver_badge_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {WARNING}; color: #0A0E17; border: none;
                border-radius: 6px; padding: 6px 10px; font-size: 11px; font-weight: 700;
            }}
        """)
        self.ver_badge_btn.clicked.connect(
            lambda: self.show_update_dialog(*self._update_found) if self._update_found else None)
        layout.addWidget(self.ver_badge_btn)
        layout.addSpacing(12)

        self._nav_group = QButtonGroup(sidebar)
        self._nav_group.setExclusive(True)
        for label, page_name, icon_name in NAV_ITEMS:
            btn = self._make_nav_button(label, page_name, icon_name)
            layout.addWidget(btn)

        layout.addStretch(1)

        for label, page_name, icon_name in FOOTER_NAV_ITEMS:
            btn = self._make_nav_button(label, page_name, icon_name)
            layout.addWidget(btn)

        status_card = QWidget()
        status_card.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 8px;")
        status_row = QHBoxLayout(status_card)
        status_row.setContentsMargins(10, 6, 10, 6)
        status_icon = get_bs_icon("check-circle-fill", color=SUCCESS, size=14)
        if status_icon:
            status_icon_lbl = QLabel()
            status_icon_lbl.setPixmap(status_icon.pixmap(14, 14))
            status_icon_lbl.setStyleSheet("border: none; background: transparent;")
            status_row.addWidget(status_icon_lbl)
        status_lbl = QLabel("All Systems Operational")
        status_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        status_row.addWidget(status_lbl)
        status_row.addStretch(1)
        layout.addSpacing(8)
        layout.addWidget(status_card)

        return sidebar

    def _build_header(self) -> QWidget:
        """Backend/FFmpeg chip (left) + GPU status chip (right) — matches
        the header bar visible in every image/*.png reference screenshot."""
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(f"background-color: {DARK_BG}; border-bottom: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)

        ffmpeg_name = Path(FFMPEG_PATH).name if FFMPEG_PATH else "Missing"
        backend_chip = self._make_chip(f"Backend: {BACKEND or 'None'}   •   FFmpeg: {ffmpeg_name}", TEXT_SUB)
        layout.addWidget(backend_chip)
        layout.addStretch(1)

        gpu_icon = get_bs_icon("cpu-fill", color=DEVICE_COLOR, size=16)
        gpu_chip = self._make_chip(DEVICE_LABEL, DEVICE_COLOR, icon=gpu_icon, bold=True)
        layout.addWidget(gpu_chip)

        return header

    def _make_chip(self, text: str, color: str, icon=None, bold: bool = False) -> QFrame:
        chip = QFrame()
        chip.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 8px;")
        row = QHBoxLayout(chip)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(16, 16))
            icon_lbl.setStyleSheet("border: none; background: transparent;")
            row.addWidget(icon_lbl)
        lbl = QLabel(text)
        weight = "700" if bold else "600"
        lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: {weight}; border: none; background: transparent;")
        row.addWidget(lbl)
        return chip

    def _build_footer(self) -> QWidget:
        """System status + live GPU/RAM/CPU/Disk/Temp/Elapsed — matches the
        bottom bar visible in every image/*.png reference screenshot."""
        footer = QWidget()
        footer.setFixedHeight(40)
        footer.setStyleSheet(f"background-color: {PANEL_BG}; border-top: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 6, 24, 6)
        layout.setSpacing(20)

        status_icon = get_bs_icon("check-circle-fill", color=SUCCESS, size=13)
        if status_icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(status_icon.pixmap(13, 13))
            icon_lbl.setStyleSheet("border: none;")
            layout.addWidget(icon_lbl)
        status_lbl = QLabel("System Status:  All Systems Operational")
        status_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 11px; font-weight: 700;")
        layout.addWidget(status_lbl)
        layout.addStretch(1)

        self.footer_gpu_lbl = self._make_footer_metric(layout, "GPU")
        self.footer_ram_lbl = self._make_footer_metric(layout, "RAM")
        self.footer_cpu_lbl = self._make_footer_metric(layout, "CPU")
        self.footer_disk_lbl = self._make_footer_metric(layout, "Disk")
        self.footer_temp_lbl = self._make_footer_metric(layout, "Temp")
        self.footer_elapsed_lbl = self._make_footer_metric(layout, "Elapsed", "00:00:00")

        self.telemetry_worker.stats.connect(self._on_footer_stats)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_footer_elapsed)
        self._elapsed_timer.start(1000)

        return footer

    def _make_footer_metric(self, layout: QHBoxLayout, label: str, initial: str = "—") -> QLabel:
        lbl_container = QLabel(f"{label}: ")
        lbl_container.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px;")
        layout.addWidget(lbl_container)
        val_lbl = QLabel(initial)
        val_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 11px; font-weight: 700;")
        layout.addWidget(val_lbl)
        return val_lbl

    def _on_footer_stats(self, s: dict):
        self.footer_gpu_lbl.setText(s.get("gpu_str", "—"))
        self.footer_ram_lbl.setText(s.get("ram_str", "—"))
        self.footer_cpu_lbl.setText(s.get("cpu_str", "—"))
        self.footer_disk_lbl.setText(s.get("disk_str", "—"))
        self.footer_temp_lbl.setText(s.get("temp_str", "—"))

    def _tick_footer_elapsed(self):
        if not self.is_busy or self._job_start_time is None:
            return
        elapsed = int(time.time() - self._job_start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        self.footer_elapsed_lbl.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _make_nav_button(self, label: str, page_name: str, icon_name: str | None = None) -> QPushButton:
        btn = QPushButton(f"  {label}" if icon_name else label)
        if icon_name:
            icon = get_bs_icon(icon_name, color=TEXT_SUB, size=18)
            if icon:
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setFixedHeight(38)
        btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left; padding-left: 12px; border-radius: 6px;
                color: {TEXT_SUB}; background: transparent; border: none;
                font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {BORDER_COLOR}; color: {TEXT_MAIN}; }}
            QPushButton:checked {{ background-color: {ACCENT}; color: white; }}
        """)
        btn.clicked.connect(lambda: self.switch_page(page_name))
        self.nav_buttons[page_name] = btn
        return btn

    def register_page(self, page_name: str, builder):
        """builder(main_window, page_name) -> QWidget, called lazily on first visit only."""
        self._page_builders[page_name] = builder

    def switch_page(self, page_name: str):
        if page_name not in self._page_cache:
            builder = self._page_builders.get(page_name, self._placeholder_page)
            page = builder(self, page_name)
            self._page_cache[page_name] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self._page_cache[page_name])
        for name, btn in self.nav_buttons.items():
            btn.setChecked(name == page_name)

    def invalidate_page(self, page_name: str):
        """Drop a cached page so it gets rebuilt from scratch on next visit —
        the Qt analog of `self.cached_pages.pop(name, None)` in subgen.py
        (e.g. after Models/History data changes underneath it)."""
        page = self._page_cache.pop(page_name, None)
        if page is not None:
            self.stack.removeWidget(page)
            page.deleteLater()

    def showEvent(self, event):
        super().showEvent(event)
        from .widgets.styles import enable_dark_titlebar
        enable_dark_titlebar(self)

    def _placeholder_page(self, main_window, page_name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        lbl = QLabel(f"{page_name}\n\n(coming in a later phase)")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 16px;")
        layout.addWidget(lbl)
        return page

