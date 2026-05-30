import sys

from PyQt6.QtWidgets import QApplication

from app.config import AppConfig
from app.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Mimaki ME-500 GUI")
    app.setOrganizationName("mimaki-gui")

    config = AppConfig.load()
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
