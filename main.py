"""Launch the rPPG v2 PySide6 control console."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Align with demo: reduce log noise when Qt / MediaPipe coexist later
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")

from PySide6.QtCore import QLibraryInfo
from PySide6.QtWidgets import QApplication


def _prefer_pyside6_qt_plugins() -> None:
    """避免 OpenCV wheel 的 Qt plugin 路徑蓋掉 PySide6 的 platform plugins."""
    if not sys.platform.startswith("linux"):
        return

    plugins_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    platforms_dir = plugins_dir / "platforms"
    if platforms_dir.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)


_prefer_pyside6_qt_plugins()

from gui.main_window import MainWindow, application_stylesheet


def main() -> int:
    _prefer_pyside6_qt_plugins()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(application_stylesheet())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
