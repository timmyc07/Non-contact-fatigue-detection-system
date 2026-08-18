"""Qt-free data models shared by the desktop engine and Flutter control API."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HotkeyConfig:
    toggle_metrics: str = "Ctrl+Alt+O"
    toggle_preview: str = "Ctrl+Alt+P"
    start_stop: str = "Ctrl+Alt+S"
    lock_overlay: str = "Ctrl+Alt+F8"
    toggle_all: str = "Ctrl+Alt+A"
    toggle_recording: str = "Ctrl+Alt+F9"


@dataclass
class UserProfile:
    age: int = 28
    height_cm: int = 170
    weight_kg: float = 65.0
