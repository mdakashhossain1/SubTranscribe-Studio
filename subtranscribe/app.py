"""QApplication bootstrap."""
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SubTranscribe Studio")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
