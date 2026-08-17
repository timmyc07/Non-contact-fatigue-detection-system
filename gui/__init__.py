"""Headless PySide6 runtime adapters for the desktop engine."""

from __future__ import annotations

def __getattr__(name: str):
    if name == "EngineApplication":
        from .main_window import EngineApplication

        return EngineApplication
    raise AttributeError(name)
