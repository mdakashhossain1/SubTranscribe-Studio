"""Update-available dialog. Qt port of SubGenApp._show_update_popup
(subgen.py:3287-3395), wired to UpdateDownloadWorker instead of a raw
threading.Thread + root.after(0, ...).
"""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QProgressBar, QFrame, QApplication,
)

from .backend.update import clean_release_notes
from .config import APP_VER, DARK_BG, PANEL_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT_CYAN, SUCCESS
from .icons import get_bs_icon
from .widgets.styles import BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE, PROGRESSBAR_STYLE, TEXTEDIT_STYLE
from .workers import UpdateDownloadWorker


class UpdateDialog(QDialog):
    def __init__(self, latest: str, url: str, notes: str, assets: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setFixedSize(560, 540)
        self.setStyleSheet(f"background-color: {DARK_BG};")

        self.latest = latest
        self.url = url
        self.assets = assets
        self.worker: UpdateDownloadWorker | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet(f"background-color: {PANEL_BG};")
        hv_outer = QHBoxLayout(hdr)
        hv_outer.setContentsMargins(24, 18, 24, 18)
        icon = get_bs_icon("arrow-up-circle-fill", color=SUCCESS, size=28)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(28, 28))
            icon_lbl.setStyleSheet("border: none;")
            hv_outer.addWidget(icon_lbl)
        hv = QVBoxLayout()
        title_lbl = QLabel("Update Available")
        title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 18px; font-weight: 700; border: none;")
        hv.addWidget(title_lbl)
        ver_lbl = QLabel(f"v{APP_VER}  →  v{latest}")
        ver_lbl.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 12px; border: none;")
        hv.addWidget(ver_lbl)
        hv_outer.addLayout(hv)
        hv_outer.addStretch(1)
        v.addWidget(hdr)

        notes_card = QFrame()
        notes_card.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 10px;")
        nv = QVBoxLayout(notes_card)
        nv.setContentsMargins(14, 10, 14, 10)
        whats_new_lbl = QLabel("What's new")
        whats_new_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; font-weight: 700; border: none;")
        nv.addWidget(whats_new_lbl)
        notes_box = QPlainTextEdit()
        notes_box.setReadOnly(True)
        notes_box.setStyleSheet(TEXTEDIT_STYLE)
        notes_box.setPlainText(clean_release_notes(notes))
        nv.addWidget(notes_box, 1)
        v.addWidget(notes_card, 1)

        self.prog_lbl = QLabel("")
        self.prog_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px;")
        self.prog_lbl.setVisible(False)
        v.addWidget(self.prog_lbl)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setStyleSheet(PROGRESSBAR_STYLE)
        self.prog_bar.setVisible(False)
        v.addWidget(self.prog_bar)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(20, 14, 20, 14)
        btn_row.addStretch(1)

        self.install_btn = QPushButton("  Install Update")
        self.install_btn.setIcon(get_bs_icon("download", color="#FFFFFF", size=16))
        self.install_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        self.view_btn = QPushButton("View on GitHub")
        self.view_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.view_btn.clicked.connect(lambda: webbrowser.open(url))
        btn_row.addWidget(self.view_btn)

        self.later_btn = QPushButton("Later")
        self.later_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.later_btn.clicked.connect(self.close)
        btn_row.addWidget(self.later_btn)

        v.addLayout(btn_row)

    def _start_install(self):
        self.install_btn.setEnabled(False)
        self.install_btn.setText("Downloading…")
        self.later_btn.setEnabled(False)
        self.view_btn.setEnabled(False)
        self.prog_lbl.setVisible(True)
        self.prog_bar.setVisible(True)

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
        self.install_btn.setText("Install Update")
        self.later_btn.setEnabled(True)
        self.view_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self.prog_lbl.setText(msg)
        self._reset_buttons()

    def _on_no_installer(self, release_url: str):
        self.prog_lbl.setText("No installer found in release. Opening GitHub…")
        webbrowser.open(release_url)
        self._reset_buttons()
