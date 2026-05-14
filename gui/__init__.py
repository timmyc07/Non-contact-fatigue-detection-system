"""PySide6 console UI for rPPG MediaPipe system v2."""

from __future__ import annotations

__all__ = ["MainWindow"]


def __getattr__(name: str):
    if name == "MainWindow":
        from gui.main_window import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
