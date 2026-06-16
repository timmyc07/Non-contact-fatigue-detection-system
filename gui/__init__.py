"""PySide6 console UI for rPPG MediaPipe system v2."""

from __future__ import annotations

def __getattr__(name: str):
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    raise AttributeError(name)
