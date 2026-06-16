"""疲勞警報播放與觸發狀態機。"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from gui.alarm_config import (
    SCENARIO_PRIORITY,
    STATUS_TO_SCENARIO,
    AlarmConfig,
    AlarmScenarioConfig,
)

logger = logging.getLogger(__name__)

_BUILTIN_BEEP_MS = 280
_BUILTIN_BEEP_FREQ: dict[str, int] = {
    "low_vigilance": 620,
    "drowsy": 780,
    "critical": 980,
    "microsleep": 1180,
}


class AlarmPlaybackBackend(Protocol):
    def play_file(self, path: str, *, volume: float) -> bool:
        ...

    def play_builtin(self, scenario: str) -> None:
        ...


@dataclass
class AlarmTriggerState:
    last_status: str | None = None
    status_since: float | None = None
    played_for_entry: bool = False
    last_played_scenario: str | None = None
    last_play_monotonic: dict[str, float] = field(default_factory=dict)


def decide_alarm_trigger(
    *,
    config: AlarmConfig,
    state: AlarmTriggerState,
    status: str,
    calibrated: bool,
    now: float,
) -> str | None:
    """依設定與狀態決定是否播放某情境音效，回傳 scenario key 或 None。"""
    if not config.enabled or not calibrated:
        return None

    status_changed = status != state.last_status
    if status_changed:
        state.last_status = status
        state.status_since = now if status in STATUS_TO_SCENARIO else None
        state.played_for_entry = False

    scenario = STATUS_TO_SCENARIO.get(status)
    if scenario is None:
        if status_changed:
            state.last_played_scenario = None
        return None

    scenario_cfg = config.scenarios.get(scenario)
    if scenario_cfg is None or not scenario_cfg.enabled:
        return None

    if state.status_since is None:
        return None
    if (now - state.status_since) < config.trigger_delay_sec:
        return None

    current_priority = SCENARIO_PRIORITY[scenario]
    last_priority = SCENARIO_PRIORITY.get(state.last_played_scenario or "", 0)
    escalation = current_priority > last_priority

    last_play = state.last_play_monotonic.get(scenario, 0.0)
    cooldown_ok = (now - last_play) >= config.repeat_interval_sec

    if escalation:
        return scenario
    if not state.played_for_entry:
        return scenario
    if scenario in ("critical", "microsleep") and config.repeat_while_critical and cooldown_ok:
        return scenario
    return None


def mark_alarm_played(state: AlarmTriggerState, scenario: str, *, now: float) -> None:
    state.last_play_monotonic[scenario] = now
    state.last_played_scenario = scenario
    state.played_for_entry = True


class QtAlarmPlaybackBackend(QObject):
    """使用 Qt Multimedia 播放音效檔。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)

    def play_file(self, path: str, *, volume: float) -> bool:
        sound = Path(path).expanduser()
        if not sound.is_file():
            return False
        self._audio.setVolume(max(0.0, min(1.0, volume)))
        self._player.setSource(QUrl.fromLocalFile(str(sound.resolve())))
        self._player.play()
        return True

    def play_builtin(self, scenario: str) -> None:
        if sys.platform == "win32":
            try:
                import winsound

                winsound.Beep(
                    _BUILTIN_BEEP_FREQ.get(scenario, 800),
                    _BUILTIN_BEEP_MS,
                )
                return
            except Exception as exc:
                logger.debug("winsound.Beep failed: %s", exc)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.beep()


class FatigueAlarmController:
    """接收 FatigueMetrics，在適當時機觸發警報音效。"""

    def __init__(
        self,
        config: AlarmConfig,
        parent: QObject | None = None,
        *,
        playback: AlarmPlaybackBackend | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._state = AlarmTriggerState()
        self._playback = playback or QtAlarmPlaybackBackend(parent)
        self._monotonic = monotonic or time.monotonic

    @property
    def config(self) -> AlarmConfig:
        return self._config

    def set_config(self, config: AlarmConfig) -> None:
        self._config = config
        self.reset_state()

    def reset_state(self) -> None:
        self._state = AlarmTriggerState()

    def on_metrics(self, metrics: Any) -> None:
        status = str(getattr(metrics, "status", "") or "")
        calibrated = bool(getattr(metrics, "calibrated", False))
        if not self._config.enabled:
            return
        if not calibrated:
            self.reset_state()
            return

        now = self._monotonic()
        scenario = decide_alarm_trigger(
            config=self._config,
            state=self._state,
            status=status,
            calibrated=calibrated,
            now=now,
        )
        if scenario is None:
            return

        scenario_cfg = self._config.scenarios.get(scenario)
        if scenario_cfg is None:
            return

        self._play_scenario(scenario, scenario_cfg)
        mark_alarm_played(self._state, scenario, now=now)

    def preview_scenario(self, scenario: str) -> bool:
        """設定對話框試聽用。"""
        scenario_cfg = self._config.scenarios.get(scenario)
        if scenario_cfg is None:
            return False
        return self._play_scenario(scenario, scenario_cfg)

    def _play_scenario(self, scenario: str, scenario_cfg: AlarmScenarioConfig) -> bool:
        volume = max(0.0, min(1.0, self._config.volume / 100.0))
        path = str(scenario_cfg.sound_path or "").strip()
        if path:
            if self._playback.play_file(path, volume=volume):
                return True
            logger.info("警報音效檔不存在或無法播放：%s", path)

        if self._config.use_builtin_fallback:
            self._playback.play_builtin(scenario)
            return True
        return False
