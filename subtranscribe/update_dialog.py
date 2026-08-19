"""Update-available dialog. Qt port of SubGenApp._show_update_popup
(subgen.py:3287-3395), wired to UpdateDownloadWorker instead of a raw
threading.Thread + root.after(0, ...).
"""
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QProgressBar, QFrame, QApplication, QWidget,
)

from .backend.update import clean_release_notes
from .config import (
    APP_VER, DARK_BG, PANEL_BG, CARD_BG, INPUT_BG, BORDER_COLOR,
    TEXT_MAIN, TEXT_SUB, ACCENT_CYAN, SUCCESS, ACCENT,
)
from .icons import get_bs_icon
from .widgets.cards import make_card
from .widgets.styles import (
    BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE, PROGRESSBAR_STYLE,
    TEXTEDIT_STYLE, SCROLLBAR_STYLE, enable_dark_titlebar,
)
from .workers import UpdateDownloadWorker


class UpdateDialog(QDialog):
    def __init__(self, latest: str, url: str, notes: str, assets: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SubTranscribe Studio — Update Available")
        self.setFixedSize(580, 560)
        self.setStyleSheet(f"background-color: {DARK_BG};")
        enable_dark_titlebar(self)

        self.latest = latest
        self.url = url
        self.assets = assets
        self.worker: UpdateDownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # ── Header Bar ───────────────────────────────────────────────
        hdr_frame = QFrame()
        hdr_frame.setObjectName("hdrFrame")
        hdr_frame.setStyleSheet(f"""
            #hdrFrame {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        hdr_layout = QHBoxLayout(hdr_frame)
        hdr_layout.setContentsMargins(16, 14, 16, 14)
        hdr_layout.setSpacing(14)

        icon = get_bs_icon("arrow-up-circle-fill", color=SUCCESS, size=32)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(32, 32))
            hdr_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title_lbl = QLabel("New Version Available!")
        title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 16px; font-weight: 700;")
        title_col.addWidget(title_lbl)

        sub_lbl = QLabel(f"SubTranscribe Studio v{latest} is ready for installation")
        sub_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px;")
        title_col.addWidget(sub_lbl)
        hdr_layout.addLayout(title_col, 1)

        ver_pill = QFrame()
        ver_pill.setStyleSheet(f"""
            background-color: {INPUT_BG};
            border: 1px solid {ACCENT_CYAN};
            border-radius: 6px;
        """)
        ver_pill_layout = QHBoxLayout(ver_pill)
        ver_pill_layout.setContentsMargins(10, 5, 10, 5)
        ver_text = QLabel(f"v{APP_VER} → v{latest}")
        ver_text.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 12px; font-weight: 700; border: none; background: transparent;")
        ver_pill_layout.addWidget(ver_text)
        hdr_layout.addWidget(ver_pill)

        layout.addWidget(hdr_frame)

        # ── Release Notes Card ───────────────────────────────────────
        notes_card, notes_body = make_card("What's New in this Release", icon_name="file-earmark-code-fill")

        notes_box = QPlainTextEdit()
        notes_box.setReadOnly(True)
        notes_box.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {INPUT_BG};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                font-family: Consolas, 'Segoe UI', monospace;
                font-size: 12px;
                padding: 10px;
                line-height: 1.4;
            }}
            {SCROLLBAR_STYLE}
        """)
        notes_box.setPlainText(clean_release_notes(notes))
        notes_body.addWidget(notes_box, 1)
        layout.addWidget(notes_card, 1)

        # ── Download Progress Section ────────────────────────────────
        self.progress_container = QWidget()
        self.progress_container.setVisible(False)
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(4, 0, 4, 0)
        prog_layout.setSpacing(6)

        self.prog_lbl = QLabel("")
        self.prog_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 12px; font-weight: 600; border: none;")
        prog_layout.addWidget(self.prog_lbl)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setStyleSheet(PROGRESSBAR_STYLE)
        self.prog_bar.setFixedHeight(22)
        prog_layout.addWidget(self.prog_bar)

        layout.addWidget(self.progress_container)

        # ── Bottom Action Buttons ────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        self.later_btn = QPushButton("  Later")
        self.later_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.later_btn.setFixedHeight(40)
        self.later_btn.setMinimumWidth(90)
        self.later_btn.clicked.connect(self.close)
        btn_row.addWidget(self.later_btn)

        self.view_btn = QPushButton("  View on GitHub")
        view_ic = get_bs_icon("window-desktop", color=TEXT_SUB, size=14)
        if view_ic:
            self.view_btn.setIcon(view_ic)
        self.view_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.view_btn.setFixedHeight(40)
        self.view_btn.setMinimumWidth(140)
        self.view_btn.clicked.connect(lambda: webbrowser.open(url))
        btn_row.addWidget(self.view_btn)

        self.install_btn = QPushButton("  Install Update")
        install_ic = get_bs_icon("download", color="#FFFFFF", size=15)
        if install_ic:
            self.install_btn.setIcon(install_ic)
        self.install_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        self.install_btn.setFixedHeight(40)
        self.install_btn.setMinimumWidth(140)
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        layout.addLayout(btn_row)

    def _start_install(self):
        self.install_btn.setEnabled(False)
        self.install_btn.setText("  Downloading…")
        self.later_btn.setEnabled(False)
        self.view_btn.setEnabled(False)
        self.progress_container.setVisible(True)

        self.worker = UpdateDownloadWorker(assets=self.assets, version=self.latest, release_url=self.url)
        self.worker.progress.connect(self._on_progress)
        self.worker.installerLaunched.connect(self._on_installer_launched)
        self.worker.error.connect(self._on_error)
        self.worker.noInstallerFound.connect(self._on_no_installer)
        self.worker.start()

    def _on_progress(self, pct: float, label: str):
        self.prog_bar.setValue(int(pct * 100))
        self.prog_lbl.setText(label)

    def _on_installer_launched(self):
        QApplication.instance().quit()

    def _reset_buttons(self):
        self.install_btn.setEnabled(True)
        self.install_btn.setText("  Install Update")
        self.later_btn.setEnabled(True)
        self.view_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self.prog_lbl.setText(msg)
        self.prog_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600; border: none;")
        self._reset_buttons()

    def _on_no_installer(self, release_url: str):
        self.prog_lbl.setText("No installer found in release. Opening GitHub…")
        webbrowser.open(release_url)
        self._reset_buttons()
