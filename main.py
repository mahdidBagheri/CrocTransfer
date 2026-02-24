import sys
from PyQt5.QtWidgets import QApplication
from utils import setup_logging
from gui import CrocApp


def main():
    # 1. Initialize Application Environment
    setup_logging()

    # 2. Launch GUI
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = CrocApp()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()