from __future__ import annotations

import time

from gui.alarm_config import AlarmConfig
from gui.alarm_player import (
    AlarmTriggerState,
    decide_alarm_trigger,
)


class _FakePlayback:
    def __init__(self) -> None:
        self.files: list[tuple[str, float]] = []
        self.builtins: list[str] = []
        self.close_calls = 0

    def play_file(self, path: str, *, volume: float) -> bool:
        self.files.append((path, volume))
        return path.endswith(".wav")

    def play_builtin(self, scenario: str) -> None:
        self.builtins.append(scenario)

    def close(self) -> None:
        self.close_calls += 1


def _cfg(**kwargs) -> AlarmConfig:
    cfg = AlarmConfig.defaults()
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return cfg


def test_decide_alarm_trigger_respects_delay() -> None:
    cfg = _cfg(enabled=True, trigger_delay_sec=2.0)
    state = AlarmTriggerState(last_status="DROWSY", status_since=100.0)
    assert decide_alarm_trigger(
        config=cfg,
        state=state,
        status="DROWSY",
        calibrated=True,
        now=101.0,
    ) is None


def test_decide_alarm_trigger_after_delay() -> None:
    cfg = _cfg(enabled=True, trigger_delay_sec=2.0)
    state = AlarmTriggerState(last_status="DROWSY", status_since=100.0)
    assert decide_alarm_trigger(
        config=cfg,
        state=state,
        status="DROWSY",
        calibrated=True,
        now=102.5,
    ) == "drowsy"


def test_low_vigilance_disabled_by_default() -> None:
    cfg = AlarmConfig.defaults()
    cfg.enabled = True
    cfg.trigger_delay_sec = 0.0
    state = AlarmTriggerState()
    assert cfg.scenarios["low_vigilance"].enabled is False
    assert decide_alarm_trigger(
        config=cfg,
        state=state,
        status="LOW_VIGILANCE",
        calibrated=True,
        now=10.0,
    ) is None


def test_escalation_plays_higher_priority() -> None:
    cfg = _cfg(enabled=True, trigger_delay_sec=0.0, repeat_interval_sec=60.0)
    state = AlarmTriggerState(
        last_status="DROWSY",
        status_since=100.0,
        played_for_entry=True,
        last_played_scenario="drowsy",
        last_play_monotonic={"drowsy": 101.0},
    )
    assert decide_alarm_trigger(
        config=cfg,
        state=state,
        status="CRITICAL",
        calibrated=True,
        now=102.0,
    ) == "critical"


def test_critical_repeats_when_enabled() -> None:
    cfg = _cfg(
        enabled=True,
        trigger_delay_sec=0.0,
        repeat_interval_sec=10.0,
        repeat_while_critical=True,
    )
    state = AlarmTriggerState(
        last_status="CRITICAL",
        status_since=100.0,
        played_for_entry=True,
        last_played_scenario="critical",
        last_play_monotonic={"critical": 100.0},
    )
    assert decide_alarm_trigger(
        config=cfg,
        state=state,
        status="CRITICAL",
        calibrated=True,
        now=111.0,
    ) == "critical"


def test_danger_group_flip_keeps_trigger_timer() -> None:
    # DROWSY↔CRITICAL 邊界抖動不得重置觸發計時（2026-07-03 審核 P1-3）
    cfg = _cfg(enabled=True, trigger_delay_sec=2.0)
    state = AlarmTriggerState(last_status="DROWSY", status_since=100.0)
    # 100.0 進入 DROWSY，101.0 抖動成 CRITICAL：計時應沿用 100.0 起算
    assert decide_alarm_trigger(
        config=cfg, state=state, status="CRITICAL", calibrated=True, now=101.0,
    ) is None
    assert state.status_since == 100.0
    assert decide_alarm_trigger(
        config=cfg, state=state, status="CRITICAL", calibrated=True, now=102.5,
    ) == "critical"


def test_microsleep_triggers_fast() -> None:
    # 微睡為最高優先，觸發延遲上限 0.5 秒，不受通用 2 秒延遲拖累（2026-07-03 審核 P0-2）
    cfg = _cfg(enabled=True, trigger_delay_sec=2.0)
    state = AlarmTriggerState(last_status="OK", status_since=None)
    assert decide_alarm_trigger(
        config=cfg, state=state, status="MICROSLEEP", calibrated=True, now=100.0,
    ) is None
    assert decide_alarm_trigger(
        config=cfg, state=state, status="MICROSLEEP", calibrated=True, now=100.6,
    ) == "microsleep"


def test_microsleep_blip_during_critical_escalates() -> None:
    # 單幀 MICROSLEEP 出現在 CRITICAL 中：沿用危險群組計時＋升級優先，立即觸發微睡警報
    cfg = _cfg(enabled=True, trigger_delay_sec=2.0, repeat_interval_sec=60.0)
    state = AlarmTriggerState(
        last_status="CRITICAL",
        status_since=100.0,
        played_for_entry=True,
        last_played_scenario="critical",
        last_play_monotonic={"critical": 102.0},
    )
    assert decide_alarm_trigger(
        config=cfg, state=state, status="MICROSLEEP", calibrated=True, now=103.0,
    ) == "microsleep"


def test_alarm_config_roundtrip() -> None:
    cfg = AlarmConfig.defaults()
    cfg.enabled = True
    cfg.scenarios["microsleep"].sound_path = "C:/sounds/wake.wav"
    restored = AlarmConfig.from_dict(cfg.to_dict())
    assert restored.enabled is True
    assert restored.scenarios["microsleep"].sound_path == "C:/sounds/wake.wav"
    assert restored.scenarios["low_vigilance"].enabled is False


def test_controller_uses_builtin_when_file_missing() -> None:
    cfg = AlarmConfig.defaults()
    cfg.enabled = True
    cfg.trigger_delay_sec = 0.0
    cfg.use_builtin_fallback = True
    playback = _FakePlayback()

    from gui.alarm_player import FatigueAlarmController

    controller = FatigueAlarmController(
        cfg,
        playback=playback,
        monotonic=time.monotonic,
    )
    controller.on_metrics(type("M", (), {"status": "DROWSY", "calibrated": True})())
    assert playback.builtins == ["drowsy"]


def test_controller_close_stops_playback_and_ignores_queued_metrics() -> None:
    cfg = AlarmConfig.defaults()
    cfg.enabled = True
    cfg.trigger_delay_sec = 0.0
    playback = _FakePlayback()

    from gui.alarm_player import FatigueAlarmController

    controller = FatigueAlarmController(cfg, playback=playback)
    controller.close()
    controller.close()
    controller.on_metrics(type("M", (), {"status": "DROWSY", "calibrated": True})())

    assert controller.preview_scenario("critical") is None
    assert playback.close_calls == 1
    assert playback.builtins == []
