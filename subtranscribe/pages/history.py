"""Transcription task history. Qt port of SubGenApp._render_history
(subgen.py:2454-2542), backed by backend.history (already extracted
verbatim from _get_history/_add_history_entry/_delete_history_entry)."""
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
)

from ..backend.history import get_history, delete_history_entry
from ..config import DARK_BG, INPUT_BG, PANEL_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT_CYAN, SUCCESS, ERROR_C
from ..widgets.cards import make_card
from ..widgets.styles import BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE, BTN_DANGER_STYLE


def _open_path(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class HistoryPage(QWidget):
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
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(20, 20, 20, 20)
        self.layout_.setSpacing(10)

        self.card, self.body = make_card("Transcription Task History")

        bar = QHBoxLayout()
        desc = QLabel("View and access all previously generated subtitle files and export history.")
        desc.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        bar.addWidget(desc)
        bar.addStretch(1)
        clear_btn = QPushButton("Clear History")
        clear_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        clear_btn.clicked.connect(self._clear_history)
        bar.addWidget(clear_btn)
        self.body.addLayout(bar)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        self.body.addLayout(self.rows_layout)

        self.layout_.addWidget(self.card)
        self.layout_.addStretch(1)

        self._refresh_rows()

    def _refresh_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        history_items = get_history()
        if not history_items:
            empty_lbl = QLabel("No transcription history recorded yet.\nGenerated subtitles will be saved here automatically.")
            empty_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 13px; padding: 24px; border: none;")
            self.rows_layout.addWidget(empty_lbl)
            return

        for idx, item in enumerate(history_items, 1):
            self.rows_layout.addWidget(self._build_row(idx, item))

    def _build_row(self, idx: int, item: dict) -> QFrame:
        sub_path = item.get("subtitle_path", "")
        media_file = item.get("media_file", "Unknown")
        model_name = item.get("model", "large-v3")
        fmt_name = item.get("format", "SRT")
        timestamp = item.get("timestamp", "--")
        entry_id = item.get("id", str(idx))

        row = QFrame()
        row.setStyleSheet(f"background-color: {INPUT_BG if idx % 2 == 0 else PANEL_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 10, 6)

        def lbl(text, color=TEXT_MAIN, bold=True, width=None):
            l = QLabel(text)
            weight = "700" if bold else "400"
            l.setStyleSheet(f"color: {color}; font-weight: {weight}; border: none;")
            if width:
                l.setFixedWidth(width)
            return l

        h.addWidget(lbl(str(idx), TEXT_SUB, False, 30))
        h.addWidget(lbl(media_file, TEXT_MAIN, True), 1)
        h.addWidget(lbl(model_name, ACCENT_CYAN, True, 110))
        h.addWidget(lbl(fmt_name, TEXT_MAIN, True, 60))
        h.addWidget(lbl(timestamp, TEXT_SUB, False, 150))
        h.addWidget(lbl("Completed", SUCCESS, True, 90))

        if sub_path and os.path.exists(sub_path):
            open_btn = QPushButton("Open File")
            open_btn.setStyleSheet(BTN_PRIMARY_STYLE)
            open_btn.clicked.connect(lambda p=sub_path: _open_path(p))
            h.addWidget(open_btn)

        out_dir = str(Path(sub_path).parent) if sub_path else ""
        if out_dir and os.path.isdir(out_dir):
            folder_btn = QPushButton("Open Folder")
            folder_btn.setStyleSheet(BTN_SECONDARY_STYLE)
            folder_btn.clicked.connect(lambda d=out_dir: _open_path(d))
            h.addWidget(folder_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(BTN_DANGER_STYLE)
        remove_btn.clicked.connect(lambda eid=entry_id: self._remove_entry(eid))
        h.addWidget(remove_btn)

        return row

    def _remove_entry(self, entry_id: str):
        delete_history_entry(entry_id)
        self._refresh_rows()

    def _clear_history(self):
        from ..backend.history import clear_history
        clear_history()
        self._refresh_rows()
