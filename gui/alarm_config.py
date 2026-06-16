"""疲勞警報器設定資料結構與預設音效路徑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALARM_SCENARIO_KEYS: tuple[str, ...] = (
    "low_vigilance",
    "drowsy",
    "critical",
    "microsleep",
)

STATUS_TO_SCENARIO: dict[str, str] = {
    "LOW_VIGILANCE": "low_vigilance",
    "DROWSY": "drowsy",
    "CRITICAL": "critical",
    "MICROSLEEP": "microsleep",
}

SCENARIO_PRIORITY: dict[str, int] = {
    "low_vigilance": 1,
    "drowsy": 2,
    "critical": 3,
    "microsleep": 4,
}

SCENARIO_LABELS: dict[str, str] = {
    "low_vigilance": "低警覺",
    "drowsy": "嗜睡",
    "critical": "危急",
    "microsleep": "微睡眠",
}

DEFAULT_SOUND_FILES: dict[str, str] = {
    "low_vigilance": "low_vigilance.wav",
    "drowsy": "drowsy.wav",
    "critical": "critical.wav",
    "microsleep": "microsleep.wav",
}

SUPPORTED_SOUND_SUFFIXES: tuple[str, ...] = (".wav", ".mp3", ".ogg", ".flac")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_alerts_dir() -> Path:
    return project_root() / "assets" / "alerts"


def default_sound_path(scenario: str) -> str:
    filename = DEFAULT_SOUND_FILES.get(scenario, f"{scenario}.wav")
    return str(default_alerts_dir() / filename)


@dataclass
class AlarmScenarioConfig:
    enabled: bool = True
    sound_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "sound_path": str(self.sound_path or ""),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, scenario: str) -> AlarmScenarioConfig:
        if not isinstance(data, dict):
            return default_scenario_config(scenario)
        enabled = data.get("enabled")
        sound_path = data.get("sound_path")
        base = default_scenario_config(scenario)
        if isinstance(enabled, bool):
            base.enabled = enabled
        if isinstance(sound_path, str):
            base.sound_path = sound_path
        return base


def default_scenario_config(scenario: str) -> AlarmScenarioConfig:
    return AlarmScenarioConfig(
        enabled=scenario != "low_vigilance",
        sound_path=default_sound_path(scenario),
    )


@dataclass
class AlarmConfig:
    enabled: bool = False
    volume: int = 70
    trigger_delay_sec: float = 2.0
    repeat_interval_sec: float = 30.0
    repeat_while_critical: bool = True
    use_builtin_fallback: bool = True
    scenarios: dict[str, AlarmScenarioConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scenarios:
            self.scenarios = {
                key: default_scenario_config(key)
                for key in ALARM_SCENARIO_KEYS
            }

    @classmethod
    def defaults(cls) -> AlarmConfig:
        return cls(
            scenarios={
                key: default_scenario_config(key)
                for key in ALARM_SCENARIO_KEYS
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "volume": int(self.volume),
            "trigger_delay_sec": float(self.trigger_delay_sec),
            "repeat_interval_sec": float(self.repeat_interval_sec),
            "repeat_while_critical": bool(self.repeat_while_critical),
            "use_builtin_fallback": bool(self.use_builtin_fallback),
            "scenarios": {
                key: self.scenarios[key].to_dict()
                for key in ALARM_SCENARIO_KEYS
                if key in self.scenarios
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AlarmConfig:
        base = cls.defaults()
        if not isinstance(data, dict):
            return base

        if isinstance(data.get("enabled"), bool):
            base.enabled = data["enabled"]

        volume = data.get("volume")
        if isinstance(volume, int) and 0 <= volume <= 100:
            base.volume = volume

        trigger_delay = data.get("trigger_delay_sec")
        if isinstance(trigger_delay, (int, float)) and trigger_delay >= 0:
            base.trigger_delay_sec = float(trigger_delay)

        repeat_interval = data.get("repeat_interval_sec")
        if isinstance(repeat_interval, (int, float)) and repeat_interval > 0:
            base.repeat_interval_sec = float(repeat_interval)

        if isinstance(data.get("repeat_while_critical"), bool):
            base.repeat_while_critical = data["repeat_while_critical"]

        if isinstance(data.get("use_builtin_fallback"), bool):
            base.use_builtin_fallback = data["use_builtin_fallback"]

        raw_scenarios = data.get("scenarios")
        if isinstance(raw_scenarios, dict):
            for key in ALARM_SCENARIO_KEYS:
                base.scenarios[key] = AlarmScenarioConfig.from_dict(
                    raw_scenarios.get(key),
                    scenario=key,
                )
        return base

    def scenario_for_status(self, status: str) -> str | None:
        return STATUS_TO_SCENARIO.get(status)
