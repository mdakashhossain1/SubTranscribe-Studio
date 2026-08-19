"""Batch processing queue. Qt port of SubGenApp._render_batch +
_batch_add_files/_batch_clear/_batch_remove_item/_update_batch_display/_batch_start
(subgen.py:2086-2207). Matches the original's actual behavior: "Start Batch"
seeds the first queued file into the shared input and runs one normal
transcription via the Transcribe page — it does not silently loop through
the whole queue unattended, same as the app being ported.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QMessageBox, QScrollArea, QFrame,
)

from ..config import (
    DARK_BG, INPUT_BG, PANEL_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB,
    ACCENT, ACCENT_HOVER, ACCENT_CYAN, SUCCESS, ERROR_C,
)
from ..widgets.cards import make_card
from ..widgets.styles import BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE, BTN_DANGER_STYLE

_MEDIA_FILTER = "Media Files (*.mp4 *.mkv *.avi *.mov *.webm *.mp3 *.wav *.m4a *.flac *.ogg *.aac);;All Files (*)"


class BatchPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.batch_files: list[str] = []

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
        layout.setSpacing(12)

        card, body = make_card("Batch Subtitle Processing Queue")

        bar = QHBoxLayout()
        add_btn = QPushButton("Add Media Files")
        add_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        add_btn.clicked.connect(self._add_files)
        bar.addWidget(add_btn)
        clear_btn = QPushButton("Clear Queue")
        clear_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        clear_btn.clicked.connect(self._clear_queue)
        bar.addWidget(clear_btn)
        bar.addStretch(1)
        body.addLayout(bar)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        body.addLayout(self.rows_layout)

        start_btn = QPushButton("Start Batch Processing")
        start_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        start_btn.setMinimumHeight(44)
        start_btn.clicked.connect(self._start_batch)
        body.addWidget(start_btn)

        layout.addWidget(card)
        layout.addStretch(1)

        self._refresh_rows()

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add Media Files", "", _MEDIA_FILTER)
        if files:
            self.batch_files.extend(files)
            self._refresh_rows()

    def _clear_queue(self):
        self.batch_files = []
        self._refresh_rows()

    def _remove_item(self, idx: int):
        if 0 <= idx < len(self.batch_files):
            self.batch_files.pop(idx)
            self._refresh_rows()

    def _refresh_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.batch_files:
            empty_lbl = QLabel("No files in batch queue.\nClick 'Add Media Files' above to queue video & audio files for automatic subtitle generation.")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 13px; padding: 30px; border: none;")
            self.rows_layout.addWidget(empty_lbl)
            return

        for i, f in enumerate(self.batch_files, 1):
            self.rows_layout.addWidget(self._build_row(i, f))

    def _build_row(self, idx: int, path: str) -> QFrame:
        row = QFrame()
        row.setStyleSheet(f"background-color: {PANEL_BG if idx % 2 == 0 else INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 10, 6)

        idx_lbl = QLabel(str(idx))
        idx_lbl.setFixedWidth(30)
        idx_lbl.setStyleSheet(f"color: {TEXT_SUB}; border: none;")
        h.addWidget(idx_lbl)

        name_lbl = QLabel(Path(path).name)
        name_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-weight: 600; border: none;")
        h.addWidget(name_lbl, 1)

        status_txt = "Next Up" if idx == 1 else "Pending"
        status_col = SUCCESS if idx == 1 else TEXT_SUB
        status_lbl = QLabel(status_txt)
        status_lbl.setStyleSheet(f"color: {status_col}; font-weight: 700; border: none;")
        h.addWidget(status_lbl)

        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(BTN_DANGER_STYLE)
        remove_btn.clicked.connect(lambda: self._remove_item(idx - 1))
        h.addWidget(remove_btn)

        return row

    def _start_batch(self):
        if not self.batch_files:
            QMessageBox.information(self, "Batch Processing", "Please add files to the queue first.")
            return
        first = self.batch_files[0]
        self.main_window.state.input_file = first
        self.main_window.switch_page("Transcribe")
        transcribe_page = self.main_window._page_cache.get("Transcribe")
        if transcribe_page is not None:
            transcribe_page.input_edit.setText(first)
            transcribe_page._on_generate_clicked()
