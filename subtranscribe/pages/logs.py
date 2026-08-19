"""Application event log viewer. Qt port of SubGenApp._render_logs +
_copy_logs/_clear_logs (subgen.py:2592-2642)."""
import time

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QApplication, QScrollArea

from ..backend.device import GPU_NAME, DEVICE, COMPUTE_TYPE
from ..backend.transcribe import BACKEND
from ..config import APP_VER, DARK_BG
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH
from ..widgets.cards import make_card
from ..widgets.styles import BTN_SECONDARY_STYLE, BTN_DANGER_STYLE, TEXTEDIT_STYLE


class LogsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {DARK_BG}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {DARK_BG};")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        card, body = make_card("Application Console & Event Logs", icon_name="file-earmark-code-fill")

        bar = QHBoxLayout()
        bar.addStretch(1)
        copy_btn = QPushButton("  Copy Logs")
        copy_btn.setIcon(get_bs_icon("clipboard-fill", color="#FFFFFF", size=14))
        copy_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        copy_btn.clicked.connect(self._copy_logs)
        bar.addWidget(copy_btn)
        clear_btn = QPushButton("  Clear Logs")
        clear_btn.setIcon(get_bs_icon("trash-fill", color="#EF4444", size=14))
        clear_btn.setStyleSheet(BTN_DANGER_STYLE)
        clear_btn.clicked.connect(self._clear_logs)
        bar.addWidget(clear_btn)
        body.addLayout(bar)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(360)
        self.log_box.setStyleSheet(TEXTEDIT_STYLE)
        body.addWidget(self.log_box)

        layout.addWidget(card)
        layout.addStretch(1)

        self._write_startup_info()

    def _ts(self) -> str:
        return time.strftime("%H:%M:%S")

    def _write_startup_info(self):
        lines = [
            f"[{self._ts()}] SubTranscribe v{APP_VER} initialized cleanly.",
            f"[{self._ts()}] Backend detected: {BACKEND}",
            f"[{self._ts()}] Device compute mode: {DEVICE} ({COMPUTE_TYPE})",
            f"[{self._ts()}] GPU Name: {GPU_NAME or 'None detected'}",
            f"[{self._ts()}] FFmpeg Binary: {FFMPEG_PATH or 'Not Found'}",
            f"[{self._ts()}] System Status: All Systems Operational.",
        ]
        self.log_box.setPlainText("\n".join(lines) + "\n")

    def _copy_logs(self):
        txt = self.log_box.toPlainText().strip()
        if txt:
            QApplication.clipboard().setText(txt)
            self.main_window.state.set_status("Logs copied to clipboard!", "")

    def _clear_logs(self):
        self.log_box.setPlainText(f"[{self._ts()}] Event logs cleared.\n")
        self.main_window.state.set_status("Logs cleared.", "")
