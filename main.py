"""SmartGuard-Vision entry point: python main.py"""
import logging
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.styles import QSS


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.showMaximized()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
