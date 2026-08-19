"""Shared Qt stylesheet fragments so every page looks consistent without
copy-pasting the same QSS string into each file."""
from ..config import TEXT_MAIN, TEXT_SUB, INPUT_BG, BORDER_COLOR, ACCENT, ACCENT_HOVER, CARD_BG

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
FIELD_LABEL_STYLE = f"color: {TEXT_SUB}; font-size: 12px; font-weight: 600;"
