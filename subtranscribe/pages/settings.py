"""App Settings: preferences, environment info, desktop shortcut, purge.
Qt port of SubGenApp._render_app_settings + _create_desktop_shortcut +
_purge_all_data (subgen.py:2311-2407).
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QMessageBox, QScrollArea,
)

from ..backend.device import DEVICE_LABEL, DEVICE_COLOR
from ..backend.eventlog import log_event
from ..backend.models import delete_model_files
from ..backend.history import clear_history
from ..config import (
    MODEL_SIZES, OUTPUT_FORMATS, LANGUAGE_MAP, PROJECT_DIR, DATA_DIR,
    DARK_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, SUCCESS, WARNING, INPUT_BG,
)
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH, ASSETS_DIR
from ..widgets.cards import make_card
from ..widgets.language_select import LanguageSelect
from ..widgets.styles import COMBO_STYLE, BTN_PRIMARY_STYLE, BTN_DANGER_STYLE, SCROLLBAR_STYLE


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet(f"background-color: {BORDER_COLOR}; border: none; max-height: 1px; min-height: 1px;")
    return line


def _badge(text: str, color: str, icon_name: str | None = None) -> QFrame:
    pill = QFrame()
    pill.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
    row = QHBoxLayout(pill)
    row.setContentsMargins(10, 6, 10, 6)
    row.setSpacing(6)
    if icon_name:
        icon = get_bs_icon(icon_name, color=color, size=14)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(14, 14))
            icon_lbl.setStyleSheet("border: none; background: transparent;")
            row.addWidget(icon_lbl)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
    row.addWidget(lbl)
    return pill


def _pref_row(title: str, desc: str, widget: QWidget) -> QWidget:
    row = QFrame()
    row.setStyleSheet("border: none; background: transparent;")
    h = QHBoxLayout(row)
    h.setContentsMargins(4, 6, 4, 6)
    h.setSpacing(16)

    info = QVBoxLayout()
    info.setSpacing(3)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 13px; font-weight: 700; border: none;")
    info.addWidget(title_lbl)
    desc_lbl = QLabel(desc)
    desc_lbl.setWordWrap(True)
    desc_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
    info.addWidget(desc_lbl)
    h.addLayout(info, 1)

    h.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)
    return row


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        state = main_window.state

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
        layout.setSpacing(16)

        # ── Card 1: Preferences ──────────────────────────────────────────
        pref_card, pref_body = make_card("Application Preferences", icon_name="gear-fill")

        fmt_combo = QComboBox()
        fmt_combo.addItems(OUTPUT_FORMATS)
        fmt_combo.setCurrentText(state.fmt)
        fmt_combo.setStyleSheet(COMBO_STYLE)
        fmt_combo.setFixedWidth(160)
        fmt_combo.currentTextChanged.connect(lambda v: setattr(state, "fmt", v))
        pref_body.addWidget(_pref_row(
            "Default Subtitle Output Format", "Default export format when generating subtitles", fmt_combo))

        pref_body.addWidget(_divider())

        src_combo = LanguageSelect(list(LANGUAGE_MAP.keys()))
        src_combo.setCurrentValue(state.src_lang)
        src_combo.setStyleSheet(COMBO_STYLE)
        src_combo.setFixedWidth(240)
        src_combo.valueChanged.connect(lambda v: setattr(state, "src_lang", v))
        pref_body.addWidget(_pref_row(
            "Default Source Language", "Default spoken language detection preset", src_combo))

        layout.addWidget(pref_card)

        # ── Card 2: Environment & Hardware ───────────────────────────────
        env_card, env_body = make_card("Environment & Hardware Acceleration", icon_name="cpu-fill")

        ff_str = FFMPEG_PATH or "Not Detected"
        ff_badge = _badge("Auto Detected" if FFMPEG_PATH else "Missing", SUCCESS if FFMPEG_PATH else WARNING, "check-circle-fill")
        env_body.addWidget(_pref_row("FFmpeg Executable Path", f"Detected binary: {ff_str}", ff_badge))

        env_body.addWidget(_divider())

        gpu_badge = _badge(DEVICE_LABEL, DEVICE_COLOR, "cpu-fill")
        env_body.addWidget(_pref_row("Primary GPU Compute Backend", f"Active acceleration engine: {DEVICE_LABEL}", gpu_badge))

        layout.addWidget(env_card)

        # ── Card 3: System Shortcuts ─────────────────────────────────────
        sc_card, sc_body = make_card("Desktop & System Integration", icon_name="window-desktop")

        shortcut_btn = QPushButton("  Create Desktop Shortcut")
        shortcut_ic = get_bs_icon("window-desktop", color="#FFFFFF", size=14)
        if shortcut_ic:
            shortcut_btn.setIcon(shortcut_ic)
        shortcut_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        shortcut_btn.clicked.connect(self._create_desktop_shortcut)
        sc_body.addWidget(_pref_row(
            "Desktop Shortcut", "Create a Windows Desktop Shortcut with SubTranscribe Logo Icon", shortcut_btn))

        layout.addWidget(sc_card)

        # ── Card 4: Data & Maintenance ───────────────────────────────────
        maint_card, maint_body = make_card("Storage & Data Maintenance", icon_name="trash-fill")

        purge_btn = QPushButton("  Purge All Models && Cache")

        purge_ic = get_bs_icon("trash-fill", color="#EF4444", size=14)
        if purge_ic:
            purge_btn.setIcon(purge_ic)
        purge_btn.setStyleSheet(BTN_DANGER_STYLE)
        purge_btn.clicked.connect(self._purge_all_data)
        maint_body.addWidget(_pref_row(
            "Purge All Local AI Models & Data",
            "Completely remove all downloaded AI models, cache, and history logs leaving zero traces",
            purge_btn))

        layout.addWidget(maint_card)
        layout.addStretch(1)

    def _create_desktop_shortcut(self):
        """Mechanical port of SubGenApp._create_desktop_shortcut (subgen.py:2361-2388)."""
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            target_exe = sys.executable if getattr(sys, "frozen", False) else str(PROJECT_DIR / "run.bat")
            icon_file = str(ASSETS_DIR / "logo.ico")
            shortcut_path = os.path.join(desktop, "SubTranscribe Studio.lnk")

            vbs_script = f'''
Set WshShell = CreateObject("WScript.Shell")
Set shortcut = WshShell.CreateShortcut("{shortcut_path}")
shortcut.TargetPath = "{target_exe}"
shortcut.WorkingDirectory = "{str(PROJECT_DIR)}"
shortcut.IconLocation = "{icon_file}"
shortcut.Description = "SubTranscribe Studio Enterprise Edition"
shortcut.Save
'''
            vbs_file = DATA_DIR / "create_sc.vbs"
            with open(vbs_file, "w", encoding="utf-8") as f:
                f.write(vbs_script)
            os.system(f'cscript //nologo "{vbs_file}"')
            if vbs_file.exists():
                os.unlink(vbs_file)
            QMessageBox.information(self, "Success", f"Desktop Shortcut created successfully on your Desktop!\n\nLocation:\n{shortcut_path}")
            self.main_window.state.set_status("Desktop Shortcut created with logo icon!", "")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create desktop shortcut: {e}")

    def _purge_all_data(self):
        reply = QMessageBox.question(
            self, "Purge All Models & Traces?",
            "Are you sure you want to COMPLETELY DELETE all downloaded AI model weights, caches, and history logs?\n\n"
            "This will remove all downloaded model files and leave zero traces on your PC.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        count = 0
        for m_size in MODEL_SIZES:
            if delete_model_files(m_size):
                count += 1
        clear_history()
        log_event(f"Purged all local data: {count} model packages and history cleared.")
        self.main_window.invalidate_page("Models")
        self.main_window.invalidate_page("History")
        QMessageBox.information(self, "Cleanup Complete", f"Successfully purged {count} model packages and all cached data.\nZero traces remain.")
        self.main_window.state.set_status("All models and local cache completely purged from disk.", "")
