"""Custom styled dialogs and automatic QMessageBox theming."""
import sys
from PySide6.QtWidgets import QMessageBox, QWidget
from PySide6.QtGui import QIcon

from ..config import ICON_PATH
from .styles import DIALOG_STYLE, enable_dark_titlebar


def _create_styled_box(icon, parent, title, text, buttons, defaultButton=QMessageBox.NoButton) -> QMessageBox:
    box = QMessageBox(parent)
    box.setStyleSheet(DIALOG_STYLE)
    if ICON_PATH.exists():
        box.setWindowIcon(QIcon(str(ICON_PATH)))
    enable_dark_titlebar(box)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if defaultButton != QMessageBox.NoButton:
        box.setDefaultButton(defaultButton)
    return box



class StyledMessageBox(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DIALOG_STYLE)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

    @staticmethod
    def information(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        box = _create_styled_box(QMessageBox.Information, parent, title, text, buttons, defaultButton)
        return box.exec()

    @staticmethod
    def warning(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        box = _create_styled_box(QMessageBox.Warning, parent, title, text, buttons, defaultButton)
        return box.exec()

    @staticmethod
    def critical(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        box = _create_styled_box(QMessageBox.Critical, parent, title, text, buttons, defaultButton)
        return box.exec()

    @staticmethod
    def question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.NoButton):
        box = _create_styled_box(QMessageBox.Question, parent, title, text, buttons, defaultButton)
        return box.exec()


def patch_qmessagebox():
    """Globally patch standard static methods of QMessageBox to always be beautifully styled."""
    QMessageBox.information = StyledMessageBox.information
    QMessageBox.warning = StyledMessageBox.warning
    QMessageBox.critical = StyledMessageBox.critical
    QMessageBox.question = StyledMessageBox.question
