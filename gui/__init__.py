"""Headless PySide6 runtime adapters for the desktop engine."""

from __future__ import annotations

def __getattr__(name: str):
    if name in {"EngineApplication", "MainWindow"}:
        from .main_window import EngineApplication, MainWindow

        return {
            "EngineApplication": EngineApplication,
            "MainWindow": MainWindow,
        }[name]
    raise AttributeError(name)
