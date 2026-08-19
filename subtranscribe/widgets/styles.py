"""Shared Qt stylesheet fragments so every page looks consistent without
copy-pasting the same QSS string into each file."""
import sys
from ..config import TEXT_MAIN, TEXT_SUB, INPUT_BG, PANEL_BG, BORDER_COLOR, ACCENT, ACCENT_HOVER, CARD_BG, ASSETS_DIR



def enable_dark_titlebar(widget):
    """Enable Windows DWM immersive dark mode and caption color on native window titlebar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        hwnd = int(widget.winId())
        val = c_int(1)
        # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 11 / Windows 10 20H1+)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, byref(val), sizeof(val))
        # DWMWA_USE_IMMERSIVE_DARK_MODE_OLD (Windows 10 1903/1909)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, byref(val), sizeof(val))
        # DWMWA_CAPTION_COLOR (Windows 11): 0x00BBGGRR for #0B0F17 -> 0x00170F0B
        caption_color = c_int(0x00170F0B)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, byref(caption_color), sizeof(caption_color))
        # DWMWA_TEXT_COLOR (Windows 11): White 0x00FFFFFF
        text_color = c_int(0x00FFFFFF)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, byref(text_color), sizeof(text_color))
    except Exception:
        pass



COMBO_STYLE = f"""
    QComboBox {{
        background-color: {INPUT_BG}; color: {TEXT_MAIN};
        border: 1px solid {BORDER_COLOR}; border-radius: 6px;
        padding: 6px 10px; min-height: 26px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {INPUT_BG}; color: {TEXT_MAIN};
        selection-background-color: {ACCENT};
    }}
"""
LINEEDIT_STYLE = f"""
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {INPUT_BG}; color: {TEXT_MAIN};
        border: 1px solid {BORDER_COLOR}; border-radius: 6px;
        padding: 6px 10px;
    }}
"""
BTN_PRIMARY_STYLE = f"""
    QPushButton {{
        background-color: {ACCENT}; color: white; border: none;
        border-radius: 6px; padding: 8px 16px; font-weight: 700;
    }}
    QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}
    QPushButton:disabled {{ background-color: {BORDER_COLOR}; color: {TEXT_SUB}; }}
"""
BTN_SECONDARY_STYLE = f"""
    QPushButton {{
        background-color: transparent; color: {TEXT_SUB};
        border: 1px solid {BORDER_COLOR}; border-radius: 6px; padding: 8px 14px;
    }}
    QPushButton:hover {{ color: {TEXT_MAIN}; border-color: {ACCENT}; }}
"""
BTN_DANGER_STYLE = f"""
    QPushButton {{
        background-color: transparent; color: #EF4444;
        border: 1px solid {BORDER_COLOR}; border-radius: 6px; padding: 8px 14px;
    }}
    QPushButton:hover {{ background-color: {INPUT_BG}; }}
"""
PROGRESSBAR_STYLE = f"""
    QProgressBar {{
        background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR};
        border-radius: 6px; text-align: center; color: {TEXT_MAIN};
        height: 20px;
    }}
    QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 6px; }}
"""
TEXTEDIT_STYLE = f"""
    QPlainTextEdit, QTextEdit {{
        background-color: {INPUT_BG}; color: {TEXT_MAIN};
        border: 1px solid {BORDER_COLOR}; border-radius: 6px;
        font-family: Consolas, monospace; font-size: 12px;
    }}
"""
FIELD_LABEL_STYLE = f"color: {TEXT_SUB}; font-size: 12px; font-weight: 600; border: none; background: transparent; padding-bottom: 2px;"

_CHECK_SVG = (ASSETS_DIR / "check-white.svg").as_posix()

CHECKBOX_STYLE = f"""
    QCheckBox {{
        color: {TEXT_MAIN};
        font-size: 13px;
        font-weight: 500;
        spacing: 8px;
        background: transparent;
        border: none;
    }}
    QCheckBox:hover {{
        color: #FFFFFF;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid {BORDER_COLOR};
        background-color: {INPUT_BG};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
        background-color: {PANEL_BG};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
        image: url("{_CHECK_SVG}");
    }}
    QCheckBox::indicator:checked:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}
"""



SCROLLBAR_STYLE = f"""
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_COLOR};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT_SUB};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 0px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        border: none;
        background: none;
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
"""

DIALOG_STYLE = f"""
    QMessageBox, QDialog {{
        background-color: {CARD_BG};
        color: {TEXT_MAIN};
    }}
    QMessageBox QLabel, QDialog QLabel {{
        color: {TEXT_MAIN};
        font-size: 13px;
        font-weight: 500;
        background-color: transparent;
    }}
    QMessageBox QDialogButtonBox, QDialog QDialogButtonBox {{
        background-color: transparent;
    }}
    QMessageBox QPushButton, QDialog QPushButton, QDialogButtonBox QPushButton {{
        background-color: {ACCENT};
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        padding: 8px 22px;
        font-size: 12px;
        font-weight: 700;
        min-width: 80px;
        min-height: 22px;
    }}
    QMessageBox QPushButton:hover, QDialog QPushButton:hover, QDialogButtonBox QPushButton:hover {{
        background-color: {ACCENT_HOVER};
    }}
    QMessageBox QPushButton:pressed, QDialog QPushButton:pressed, QDialogButtonBox QPushButton:pressed {{
        background-color: #3730A3;
    }}
    {SCROLLBAR_STYLE}
"""


