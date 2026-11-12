from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from pathlib import Path
from drawing_editor.window import DrawingWindow


def main():
    # Deterministic onefile smoke gate: initialize the packaged Qt / image/CAD
    # dependencies without starting the GUI event loop or contacting a server.
    if '--self-test' in sys.argv:
        import fitz, ezdxf
        from PIL import Image
        app = QApplication([sys.argv[0]])
        assert (Path(__file__).parent / 'assets' / 'app.ico').is_file()
        window = DrawingWindow()
        window.close()
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName('Sunrise Drawing Editor')
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / 'app.ico')))
    window = DrawingWindow(sys.argv[1:])
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
