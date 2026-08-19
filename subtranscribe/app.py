"""QApplication bootstrap."""
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .widgets.dialogs import patch_qmessagebox
from .widgets.styles import DIALOG_STYLE


def main():
    patch_qmessagebox()
    app = QApplication(sys.argv)
    app.setApplicationName("SubTranscribe Studio")
    app.setStyleSheet(DIALOG_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())



if __name__ == "__main__":
    main()
