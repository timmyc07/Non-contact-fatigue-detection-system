"""Launch the rPPG v2 PySide6 control console (UI shell; pipeline wiring TBD)."""

from __future__ import annotations

import os
import sys

# Align with demo: reduce log noise when Qt / MediaPipe coexist later
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow, application_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(application_stylesheet())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
