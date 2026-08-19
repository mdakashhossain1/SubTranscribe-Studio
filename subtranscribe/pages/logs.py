"""Application event log viewer. Qt port of SubGenApp._render_logs +
_copy_logs/_clear_logs (subgen.py:2592-2642), now backed by the live,
persistent backend.eventlog event stream instead of a static one-shot
snapshot of startup diagnostics."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QApplication, QScrollArea

from ..backend.eventlog import event_log, log_event
from ..config import DARK_BG
from ..icons import get_bs_icon
from ..widgets.cards import make_card
from ..widgets.styles import BTN_SECONDARY_STYLE, BTN_DANGER_STYLE, TEXTEDIT_STYLE, SCROLLBAR_STYLE


class LogsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {DARK_BG}; }} {SCROLLBAR_STYLE}")
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

        # Render everything logged so far (startup diagnostics + any model
        # download/transcription activity that happened before this page was
        # ever opened), then keep appending live as new events arrive.
        self.log_box.setPlainText("\n".join(event_log.lines) + ("\n" if event_log.lines else ""))
        self._scroll_to_end()
        event_log.lineAdded.connect(self._on_line_added)

    def _scroll_to_end(self):
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_line_added(self, line: str):
        self.log_box.appendPlainText(line)
        self._scroll_to_end()

    def _copy_logs(self):
        txt = self.log_box.toPlainText().strip()
        if txt:
            QApplication.clipboard().setText(txt)
            self.main_window.state.set_status("Logs copied to clipboard!", "")

    def _clear_logs(self):
        event_log.clear()
        self.log_box.clear()
        log_event("Event logs cleared.")
        self.main_window.state.set_status("Logs cleared.", "")
