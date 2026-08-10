"""Qt-free desktop settings command validation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from gui.alarm_config import (
    ALARM_SCENARIO_KEYS,
    SUPPORTED_SOUND_SUFFIXES,
    AlarmConfig,
    AlarmScenarioConfig,
)


RESET_SECTIONS = frozenset(
    {
        "hotkeys",
        "user_profile",
        "alarm",
        "camera",
        "toggles",
        "overlay",
        "web",
        "replay",
    }
)


def parse_user_profile(args: dict[str, Any]) -> tuple[int, int, float]:
    if set(args) != {"user_profile"} or not isinstance(args.get("user_profile"), dict):
        raise ValueError("user_profile must be the only argument and must be an object")
    raw = args["user_profile"]
    if set(raw) != {"age", "height_cm", "weight_kg"}:
        raise ValueError("user_profile must contain age, height_cm, and weight_kg")

    age = raw["age"]
    height_cm = raw["height_cm"]
    weight_kg = raw["weight_kg"]
    if isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 110:
        raise ValueError("user_profile.age must be an integer between 0 and 110")
    if (
        isinstance(height_cm, bool)
        or not isinstance(height_cm, int)
        or not 100 <= height_cm <= 220
    ):
        raise ValueError("user_profile.height_cm must be an integer between 100 and 220")
    if (
        isinstance(weight_kg, bool)
        or not isinstance(weight_kg, (int, float))
        or not math.isfinite(float(weight_kg))
        or not 30.0 <= float(weight_kg) <= 200.0
    ):
        raise ValueError("user_profile.weight_kg must be between 30.0 and 200.0")
    return age, height_cm, float(weight_kg)


def parse_alarm_config(args: dict[str, Any]) -> AlarmConfig:
    if set(args) != {"alarm"} or not isinstance(args.get("alarm"), dict):
        raise ValueError("alarm must be the only argument and must be an object")
    raw = args["alarm"]
    expected = {
        "enabled",
        "volume",
        "trigger_delay_sec",
        "repeat_interval_sec",
        "repeat_while_critical",
        "use_builtin_fallback",
        "scenarios",
    }
    if set(raw) != expected:
        raise ValueError("alarm must contain the complete alarm configuration")

    for key in ("enabled", "repeat_while_critical", "use_builtin_fallback"):
        if not isinstance(raw[key], bool):
            raise ValueError(f"alarm.{key} must be a boolean")

    volume = raw["volume"]
    if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
        raise ValueError("alarm.volume must be an integer between 0 and 100")

    def finite_number(key: str, lower: float, upper: float) -> float:
        value = raw[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not lower <= float(value) <= upper
        ):
            raise ValueError(f"alarm.{key} must be between {lower} and {upper}")
        return float(value)

    trigger_delay = finite_number("trigger_delay_sec", 0.0, 10.0)
    repeat_interval = finite_number("repeat_interval_sec", 5.0, 120.0)
    raw_scenarios = raw["scenarios"]
    if not isinstance(raw_scenarios, dict) or set(raw_scenarios) != set(ALARM_SCENARIO_KEYS):
        raise ValueError("alarm.scenarios must contain all four supported scenarios")

    scenarios: dict[str, AlarmScenarioConfig] = {}
    for key in ALARM_SCENARIO_KEYS:
        scenario = raw_scenarios[key]
        if not isinstance(scenario, dict) or set(scenario) != {"enabled", "sound_path"}:
            raise ValueError(f"alarm.scenarios.{key} must contain enabled and sound_path")
        enabled = scenario["enabled"]
        sound_path = scenario["sound_path"]
        if not isinstance(enabled, bool):
            raise ValueError(f"alarm.scenarios.{key}.enabled must be a boolean")
        if not isinstance(sound_path, str):
            raise ValueError(f"alarm.scenarios.{key}.sound_path must be a string")
        sound_path = sound_path.strip()
        if enabled and sound_path:
            path = Path(sound_path).expanduser()
            if not path.is_file() and not raw["use_builtin_fallback"]:
                raise ValueError(f"alarm.scenarios.{key}.sound_path does not exist")
            if path.is_file() and path.suffix.lower() not in SUPPORTED_SOUND_SUFFIXES:
                raise ValueError(f"alarm.scenarios.{key}.sound_path has an unsupported format")
        scenarios[key] = AlarmScenarioConfig(enabled=enabled, sound_path=sound_path)

    return AlarmConfig(
        enabled=raw["enabled"],
        volume=volume,
        trigger_delay_sec=trigger_delay,
        repeat_interval_sec=repeat_interval,
        repeat_while_critical=raw["repeat_while_critical"],
        use_builtin_fallback=raw["use_builtin_fallback"],
        scenarios=scenarios,
    )


def parse_settings_reset_sections(args: dict[str, Any]) -> list[str]:
    if set(args) != {"sections"} or not isinstance(args.get("sections"), list):
        raise ValueError("sections must be the only argument and must be an array")
    sections = args["sections"]
    if (
        not sections
        or any(not isinstance(section, str) or section not in RESET_SECTIONS for section in sections)
        or len(set(sections)) != len(sections)
    ):
        raise ValueError("sections must contain unique supported settings sections")
    return list(sections)
