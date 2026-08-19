"""Transcription task history. Qt port of SubGenApp._render_history
(subgen.py:2454-2542), backed by backend.history (already extracted
verbatim from _get_history/_add_history_entry/_delete_history_entry)."""
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QFontMetrics, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QSizePolicy, QMessageBox,
)

from ..backend.history import get_history, delete_history_entry
from ..config import DARK_BG, INPUT_BG, PANEL_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT, ACCENT_HOVER, ACCENT_CYAN, SUCCESS, ERROR_C
from ..icons import get_bs_icon
from ..widgets.cards import make_card
from ..widgets.styles import BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE, BTN_DANGER_STYLE, SCROLLBAR_STYLE



class ElidedLabel(QLabel):
    """Label that elides text in the middle when space is constrained."""

    def __init__(self, text="", color=TEXT_MAIN, bold=True, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._color = QColor(color)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(60)
        font = self.font()
        font.setBold(bold)
        self.setFont(font)
        self.setStyleSheet("border: none; background: transparent;")

    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.ElideMiddle, self.width())
        painter.setPen(self._color)
        painter.setFont(self.font())
        painter.drawText(self.rect(), self.alignment() | Qt.AlignVCenter, elided)


class HistoryPage(QWidget):
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
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(20, 20, 20, 20)
        self.layout_.setSpacing(10)

        self.card, self.body = make_card("Transcription Task History")

        bar = QHBoxLayout()
        desc = QLabel("View and access all previously generated subtitle files and export history.")
        desc.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        bar.addWidget(desc)
        bar.addStretch(1)
        clear_btn = QPushButton("  Clear History")
        clear_icon = get_bs_icon("trash-fill", color="#EF4444", size=13)
        if clear_icon:
            clear_btn.setIcon(clear_icon)
        clear_btn.setStyleSheet(BTN_DANGER_STYLE)
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
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(8)

        def lbl(text, color=TEXT_MAIN, bold=True, width=None):
            l = QLabel(text)
            weight = "700" if bold else "400"
            l.setStyleSheet(f"color: {color}; font-weight: {weight}; border: none;")
            if width:
                l.setFixedWidth(width)
            return l

        h.addWidget(lbl(str(idx), TEXT_SUB, False, 24))
        h.addWidget(ElidedLabel(media_file, TEXT_MAIN, True), 1)
        h.addWidget(lbl(model_name, ACCENT_CYAN, True, 85))
        h.addWidget(lbl(fmt_name, TEXT_MAIN, True, 45))
        h.addWidget(lbl(timestamp, TEXT_SUB, False, 125))
        h.addWidget(lbl("Completed", SUCCESS, True, 75))

        btn_style_primary = f"""
            QPushButton {{
                background-color: {ACCENT}; color: white; border: none;
                border-radius: 5px; padding: 6px 12px; font-weight: 700; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}
        """
        btn_style_sec = f"""
            QPushButton {{
                background-color: transparent; color: {TEXT_SUB};
                border: 1px solid {BORDER_COLOR}; border-radius: 5px; padding: 6px 10px; font-size: 11px;
            }}
            QPushButton:hover {{ color: {TEXT_MAIN}; border-color: {ACCENT}; }}
        """
        btn_style_danger = f"""
            QPushButton {{
                background-color: transparent; color: #EF4444;
                border: 1px solid {BORDER_COLOR}; border-radius: 5px; padding: 6px 10px; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {INPUT_BG}; }}
        """

        if sub_path and os.path.exists(sub_path):
            open_btn = QPushButton("  Open File")
            open_ic = get_bs_icon("file-earmark-code-fill", color="#FFFFFF", size=13)
            if open_ic:
                open_btn.setIcon(open_ic)
            open_btn.setStyleSheet(btn_style_primary)
            open_btn.clicked.connect(lambda checked=False, p=sub_path: self._open_file(p))
            h.addWidget(open_btn)

        out_dir = str(Path(sub_path).parent) if sub_path else ""
        if out_dir and os.path.isdir(out_dir):
            folder_btn = QPushButton("  Open Folder")
            folder_ic = get_bs_icon("folder2-open", color=TEXT_SUB, size=13)
            if folder_ic:
                folder_btn.setIcon(folder_ic)
            folder_btn.setStyleSheet(btn_style_sec)
            folder_btn.clicked.connect(lambda checked=False, p=sub_path: self._open_folder(p))
            h.addWidget(folder_btn)

        remove_btn = QPushButton("  Delete")
        trash_ic = get_bs_icon("trash-fill", color="#EF4444", size=13)
        if trash_ic:
            remove_btn.setIcon(trash_ic)
        remove_btn.setStyleSheet(btn_style_danger)
        remove_btn.clicked.connect(lambda checked=False, eid=entry_id, it=item: self._remove_entry(eid, it))
        h.addWidget(remove_btn)


        return row

    def _open_file(self, path: str):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "File Not Found", f"The subtitle file no longer exists on disk:\n\n{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            if sys.platform == "win32":
                try:
                    subprocess.Popen(["notepad.exe", path])
                except Exception as e:
                    QMessageBox.warning(self, "Open Error", f"Could not open file:\n{e}")
            else:
                QMessageBox.warning(self, "Open Error", f"Could not open file:\n{path}")

    def _open_folder(self, path: str):
        if not path:
            return
        folder = path if os.path.isdir(path) else str(Path(path).parent)
        if not os.path.exists(folder):
            QMessageBox.warning(self, "Folder Not Found", f"The folder no longer exists on disk:\n\n{folder}")
            return
        try:
            if sys.platform == "win32":
                if os.path.isfile(path):
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
                else:
                    os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "Open Folder Error", f"Could not open folder:\n{e}")

    def _remove_entry(self, entry_id: str, item: dict):
        delete_history_entry(entry_id, match_item=item)
        self._refresh_rows()

    def _clear_history(self):
        from ..backend.history import clear_history
        clear_history()
        self._refresh_rows()


