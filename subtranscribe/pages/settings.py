"""App Settings: preferences, environment info, desktop shortcut, purge.
Qt port of SubGenApp._render_app_settings + _create_desktop_shortcut +
_purge_all_data (subgen.py:2311-2407).
"""
import os
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QMessageBox, QScrollArea,
)

from ..backend.device import DEVICE_LABEL, DEVICE_COLOR
from ..backend.models import delete_model_files
from ..backend.history import clear_history
from ..config import (
    MODEL_SIZES, OUTPUT_FORMATS, LANGUAGE_MAP, PROJECT_DIR, DATA_DIR,
    DARK_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, SUCCESS, WARNING,
)
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH, ASSETS_DIR
from ..widgets.cards import make_card
from ..widgets.language_select import LanguageSelect
from ..widgets.styles import COMBO_STYLE, BTN_PRIMARY_STYLE, BTN_DANGER_STYLE


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        state = main_window.state

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

        card, body = make_card("Application Preferences & Environment", icon_name="gear-fill")

        fmt_combo = QComboBox()
        fmt_combo.addItems(OUTPUT_FORMATS)
        fmt_combo.setCurrentText(state.fmt)
        fmt_combo.setStyleSheet(COMBO_STYLE)
        fmt_combo.currentTextChanged.connect(lambda v: setattr(state, "fmt", v))
        body.addWidget(self._pref_row(
            "Default Subtitle Output Format", "Default format when selecting a new file", fmt_combo))

        src_combo = LanguageSelect(list(LANGUAGE_MAP.keys()))
        src_combo.setCurrentValue(state.src_lang)
        src_combo.setStyleSheet(COMBO_STYLE)
        src_combo.valueChanged.connect(lambda v: setattr(state, "src_lang", v))
        body.addWidget(self._pref_row(
            "Default Source Language", "Default spoken language detection preset", src_combo))

        ff_str = FFMPEG_PATH or "Not Detected"
        ff_lbl = QLabel("Auto Detected" if FFMPEG_PATH else "Missing")
        ff_lbl.setStyleSheet(f"color: {SUCCESS if FFMPEG_PATH else WARNING}; font-weight: 700; border: none;")
        body.addWidget(self._pref_row("FFmpeg Executable Path", f"Detected binary: {ff_str}", ff_lbl))

        gpu_lbl = QLabel(DEVICE_LABEL)
        gpu_lbl.setStyleSheet(f"color: {DEVICE_COLOR}; font-weight: 700; border: none;")
        body.addWidget(self._pref_row("Primary GPU Compute Backend", f"Active engine: {DEVICE_LABEL}", gpu_lbl))

        shortcut_btn = QPushButton("  Create Desktop Shortcut")
        shortcut_btn.setIcon(get_bs_icon("window-desktop", color="#FFFFFF", size=16))
        shortcut_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        shortcut_btn.clicked.connect(self._create_desktop_shortcut)
        body.addWidget(self._pref_row(
            "Desktop Shortcut", "Create a Windows Desktop Shortcut with SubTranscribe Logo Icon", shortcut_btn))

        purge_btn = QPushButton("  Purge All Models & Cache")
        purge_btn.setIcon(get_bs_icon("trash-fill", color="#EF4444", size=16))
        purge_btn.setStyleSheet(BTN_DANGER_STYLE)
        purge_btn.clicked.connect(self._purge_all_data)
        body.addWidget(self._pref_row(
            "Purge All Local AI Models & Data",
            "Completely remove all downloaded AI models, cache, and history logs leaving zero traces",
            purge_btn))

        layout.addWidget(card)
        layout.addStretch(1)

    def _pref_row(self, title: str, desc: str, widget: QWidget) -> QWidget:
        row = QFrame()
        row.setStyleSheet("border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 8, 0, 8)

        info = QVBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 13px; font-weight: 700; border: none;")
        info.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        info.addWidget(desc_lbl)
        h.addLayout(info, 1)
        h.addWidget(widget)
        return row

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
        self.main_window.invalidate_page("Models")
        self.main_window.invalidate_page("History")
        QMessageBox.information(self, "Cleanup Complete", f"Successfully purged {count} model packages and all cached data.\nZero traces remain.")
        self.main_window.state.set_status("All models and local cache completely purged from disk.", "")
