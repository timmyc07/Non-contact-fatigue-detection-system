"""P6b-3b：rPPG 參數線上協調層的接線測試。

涵蓋三層接線（皆須在 OFF／無候選時逐位元不變）：
1. ``RppgWorker`` / ``CombinedWorker`` 的 ``set_candidate_roi_weights`` pending-flag
   與 ``_maybe_emit_candidate_bpm`` 低頻重算分支（OFF 早退、ON 才發射訊號）。
2. ``gui.main_window.MainWindow._tick_rppg_param_coordinator`` GUI 薄接線
   （協調層為 None 時整段不動作）。
3. ``_on_candidate_bpm_ready`` / ``_adopt_rppg_param_candidate`` /
   ``_dispatch_candidate_roi_weights`` / ``_resolve_current_roi_weights`` 的判斷邏輯。

測試策略：以 ``SimpleNamespace`` 充當 ``MainWindow`` 的 fake self，把未綁定方法
（``MainWindow._method``）直接餵 fake self 呼叫——只測真正的接線程式碼，不建構
完整 QApplication / 真實 GUI（過重且非必要）。
"""

from __future__ import annotations

import queue
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PySide6")

from gui.mediapipe_tuning import load_mediapipe_tuning  # noqa: E402
from rppg.adaptive_calibration import (  # noqa: E402
    CONF_HIGH,
    CONF_LOW,
    COORD_EVALUATING,
    COORD_GATED,
    AdaptiveCalibState,
    RppgParamAbVerdict,
    RppgParamCoordinator,
)
from rppg.rppg_worker import (  # noqa: E402
    ROI_BASE_WEIGHTS,
    RppgEngine,
    RppgWorker,
    resolve_effective_rppg_tuning,
)


def _pulse_channels(t: np.ndarray, f0: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = 0.5 * np.sin(2 * np.pi * f0 * t)
    g = 2.0 * np.sin(2 * np.pi * f0 * t + 0.4)
    b = 0.2 * np.sin(2 * np.pi * f0 * t + 0.8)
    return r, g, b


class _ExplodingEngine:
    """OFF 早退驗證用：任何存取都應視為違反 bit-identical 不變量。"""

    def get_roi_window(self, *args, **kwargs):  # pragma: no cover - 預期不會被呼叫
        raise AssertionError("OFF（無候選）時不應存取 engine.get_roi_window")


# ── weighted_mix 連動（審查 B 修正）────────────────────────────────────────

def test_weighted_mix_linkage_off_when_no_override():
    """worker 用 `roi_override_active = rppg_tuning is not self._tuning` 推導
    weighted_mix。無覆寫（無 explicit、無 loader）時 resolve 回傳原物件 → False →
    等權平均逐位元不變。這是 OFF bit-identical 的關鍵連動，釘住不讓回歸。"""
    tuning = load_mediapipe_tuning()
    rppg_tuning = resolve_effective_rppg_tuning(tuning, None, None)
    roi_override_active = rppg_tuning is not tuning
    assert roi_override_active is False


def test_weighted_mix_linkage_on_when_calibration_loader_provides_override():
    """production 覆寫路徑（走 calibration_loader → rppg_params，而非
    set_roi_base_weights_override）也要讓 weighted_mix 為 True——這正是審查 B
    指出、本次修正的核心：舊寫法 `self._roi_weights_override is not None` 在此路徑
    恆 False，導致 adopt 的權重重載後無加權槓桿。"""
    tuning = load_mediapipe_tuning()
    override = {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}
    version = SimpleNamespace(params=SimpleNamespace(rppg_params={"roi_weights": override}))
    rppg_tuning = resolve_effective_rppg_tuning(tuning, None, lambda: version)
    roi_override_active = rppg_tuning is not tuning
    assert roi_override_active is True


@pytest.mark.parametrize("worker_run", ["rppg_worker", "combined_worker"])
def test_both_workers_pass_roi_override_active_into_collect(worker_run):
    """回歸守衛（審查 finding 3 盲點）：兩條 worker 的 collect 呼叫端都必須用
    `weighted_mix=roi_override_active`，不得回退到會在 production 覆寫路徑恆 False
    的舊寫法 `self._roi_weights_override is not None`。run() 迴圈需真相機/
    FaceLandmarker 太重無法整合驅動，故以原始碼守衛釘住兩處 callsite 一致，
    防止 combined_worker 那類「修正未移植到另一 callsite」的回歸。"""
    import inspect

    if worker_run == "rppg_worker":
        from rppg.rppg_worker import RppgWorker as _W
        src = inspect.getsource(_W.run)
    else:
        from gui.combined_worker import CombinedWorker as _W
        src = inspect.getsource(_W.run)

    assert "collect_rppg_roi_sample_with_means(" in src
    assert "weighted_mix=roi_override_active" in src
    assert "weighted_mix=self._roi_weights_override is not None" not in src


# ── RppgWorker._maybe_emit_candidate_bpm（OFF 早退 / ON 發射）───────────────

def test_rppg_worker_candidate_none_by_default():
    worker = RppgWorker(queue.Queue())
    assert worker._candidate_roi_weights is None


def test_rppg_worker_set_candidate_roi_weights_hotswap_flag():
    worker = RppgWorker(queue.Queue())
    weights = {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}
    worker.set_candidate_roi_weights(weights)
    assert worker._candidate_roi_weights is weights
    worker.set_candidate_roi_weights(None)
    assert worker._candidate_roi_weights is None


def test_rppg_worker_maybe_emit_candidate_bpm_off_is_noop_and_touches_nothing():
    """OFF（預設無候選）：不呼叫 engine.get_roi_window、不發射訊號——逐位元不變。"""
    worker = RppgWorker(queue.Queue())
    received = []
    worker.candidate_bpm_ready.connect(lambda *a: received.append(a))
    tuning = load_mediapipe_tuning()

    # 用會在被呼叫時 raise 的假 engine，證明 OFF 路徑完全不存取它。
    worker._maybe_emit_candidate_bpm(_ExplodingEngine(), tuning, 1.0)

    assert received == []


def test_rppg_worker_maybe_emit_candidate_bpm_on_emits_signal():
    worker = RppgWorker(queue.Queue())
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    fs, n, f0 = 30.0, 300, 1.2
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, f0)
    for i in range(n):
        engine.push_roi_means(float(t[i]), {"forehead": (float(r[i]), float(g[i]), float(b[i]))})

    worker.set_candidate_roi_weights({"forehead": 1.0, "L_cheek": 0.0, "R_cheek": 0.0, "glabella": 0.0})
    tuning = load_mediapipe_tuning()
    received = []
    worker.candidate_bpm_ready.connect(lambda t_now, cur, cand: received.append((t_now, cur, cand)))

    worker._maybe_emit_candidate_bpm(engine, tuning, float(t[-1]))

    assert len(received) == 1
    t_now, cur_bpm, cand_bpm = received[0]
    assert t_now == pytest.approx(float(t[-1]))
    # current 用 tuning 的 base_weights（forehead 佔 0.34 而非唯一 ROI，但此處只有
    # forehead 有資料，其餘 ROI 因緩衝為空被略過），candidate 只用 forehead=1.0；
    # 兩者實際參與的 ROI 集合相同（僅 forehead），BPM 應相等。
    assert cur_bpm == pytest.approx(cand_bpm, abs=1e-6)
    assert not np.isnan(cur_bpm)


def test_rppg_worker_maybe_emit_candidate_bpm_rate_limited():
    """低頻節奏：同一秒內第二次呼叫不應重算（_last_candidate_recompute_t 節流）。"""
    worker = RppgWorker(queue.Queue())
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    fs, n, f0 = 30.0, 300, 1.2
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, f0)
    for i in range(n):
        engine.push_roi_means(float(t[i]), {"forehead": (float(r[i]), float(g[i]), float(b[i]))})
    worker.set_candidate_roi_weights({"forehead": 1.0, "L_cheek": 0.0, "R_cheek": 0.0, "glabella": 0.0})
    tuning = load_mediapipe_tuning()
    received = []
    worker.candidate_bpm_ready.connect(lambda *a: received.append(a))

    worker._maybe_emit_candidate_bpm(engine, tuning, float(t[-1]))
    worker._maybe_emit_candidate_bpm(_ExplodingEngine(), tuning, float(t[-1]) + 0.01)  # 同一節奏內：不應存取 engine

    assert len(received) == 1


# ── CombinedWorker（同一組行為，OFF 早退）───────────────────────────────────

def test_combined_worker_candidate_none_by_default_and_off_is_noop():
    cw_mod = pytest.importorskip("gui.combined_worker")
    worker = cw_mod.CombinedWorker(queue.Queue())
    assert worker._candidate_roi_weights is None

    received = []
    worker.candidate_bpm_ready.connect(lambda *a: received.append(a))
    tuning = load_mediapipe_tuning()

    # rppg_engine=None（enable_rppg=False 情境）：早退，不呼叫 _ExplodingEngine。
    worker._maybe_emit_candidate_bpm(None, tuning, 1.0)
    assert received == []

    # rppg_engine 非 None 但候選為 None：仍早退，不存取 engine.get_roi_window。
    worker._maybe_emit_candidate_bpm(_ExplodingEngine(), tuning, 1.0)
    assert received == []


def test_combined_worker_set_candidate_roi_weights_hotswap_flag():
    cw_mod = pytest.importorskip("gui.combined_worker")
    worker = cw_mod.CombinedWorker(queue.Queue())
    weights = {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}
    worker.set_candidate_roi_weights(weights)
    assert worker._candidate_roi_weights is weights
    worker.set_candidate_roi_weights(None)
    assert worker._candidate_roi_weights is None


# ── gui.main_window 薄接線（fake self，避免建構完整 QApplication/GUI）───────

class _FakeCal:
    """duck-typed 版 OnlineBpmCalibrator：只提供 `_tick_rppg_param_coordinator`
    實際使用的 `.state()` 介面，讓測試能直接指定任意 confidence（offset 是否穩定）
    以驗證觸發 gate（使用者裁決 1：gate 只看 confidence != CONF_LOW）。
    """

    def __init__(self, state: AdaptiveCalibState) -> None:
        self._st = state

    def state(self) -> AdaptiveCalibState:
        return self._st


def _fake_main_window(**overrides) -> SimpleNamespace:
    base = dict(
        _rppg_param_coordinator=None,
        _rppg_param_current_weights=dict(ROI_BASE_WEIGHTS),
        _combined_worker=None,
        _rppg_worker=None,
        _belt_calibrator=None,
        _engine_controller=SimpleNamespace(belt_status=lambda: None),
        _rppg_calibration_store=None,
        _clear_candidate_roi_weights=lambda: None,
        _adopt_rppg_param_candidate=lambda: None,
        _dispatch_candidate_roi_weights=lambda w: None,
    )
    base.update(overrides)
    logs: list[str] = []
    base["_append_log"] = lambda msg: logs.append(msg)
    ns = SimpleNamespace(**base)
    ns._logs = logs
    return ns


def test_tick_rppg_param_coordinator_off_when_coordinator_none():
    from gui.main_window import MainWindow

    dispatched = []
    fake = _fake_main_window(_dispatch_candidate_roi_weights=lambda w: dispatched.append(w))
    cal = _FakeCal(AdaptiveCalibState(confidence=CONF_HIGH))

    MainWindow._tick_rppg_param_coordinator(fake, cal)

    assert dispatched == []
    assert fake._logs == []


def test_tick_rppg_param_coordinator_off_when_cal_none():
    from gui.main_window import MainWindow

    dispatched = []
    fake = _fake_main_window(
        _rppg_param_coordinator=RppgParamCoordinator(),
        _dispatch_candidate_roi_weights=lambda w: dispatched.append(w),
    )

    MainWindow._tick_rppg_param_coordinator(fake, None)

    assert dispatched == []


def test_tick_rppg_param_coordinator_gated_does_not_dispatch():
    from gui.main_window import MainWindow

    coord = RppgParamCoordinator()
    dispatched = []
    fake = _fake_main_window(
        _rppg_param_coordinator=coord,
        _dispatch_candidate_roi_weights=lambda w: dispatched.append(w),
    )
    cal = _FakeCal(AdaptiveCalibState(confidence=CONF_LOW))

    MainWindow._tick_rppg_param_coordinator(fake, cal)

    assert dispatched == []
    assert coord.phase == COORD_GATED


def test_tick_rppg_param_coordinator_on_dispatches_when_triggered():
    from gui.main_window import MainWindow

    coord = RppgParamCoordinator()
    dispatched = []
    fake = _fake_main_window(
        _rppg_param_coordinator=coord,
        _dispatch_candidate_roi_weights=lambda w: dispatched.append(w),
    )
    cal = _FakeCal(AdaptiveCalibState(confidence=CONF_HIGH))

    MainWindow._tick_rppg_param_coordinator(fake, cal)

    assert len(dispatched) == 1
    assert coord.phase == COORD_EVALUATING
    assert len(fake._logs) == 1


def test_dispatch_candidate_roi_weights_forwards_to_both_workers():
    from gui.main_window import MainWindow

    calls = {"combined": [], "rppg": []}
    fake = _fake_main_window(
        _combined_worker=SimpleNamespace(set_candidate_roi_weights=lambda w: calls["combined"].append(w)),
        _rppg_worker=SimpleNamespace(set_candidate_roi_weights=lambda w: calls["rppg"].append(w)),
    )
    weights = {"forehead": 0.4}

    MainWindow._dispatch_candidate_roi_weights(fake, weights)

    assert calls["combined"] == [weights]
    assert calls["rppg"] == [weights]


def test_dispatch_candidate_roi_weights_tolerates_no_active_worker():
    from gui.main_window import MainWindow

    fake = _fake_main_window()  # _combined_worker / _rppg_worker 皆 None
    MainWindow._dispatch_candidate_roi_weights(fake, {"forehead": 0.4})  # 不應丟例外


def test_on_candidate_bpm_ready_noop_when_coordinator_none():
    from gui.main_window import MainWindow

    fake = _fake_main_window(_rppg_param_coordinator=None)
    MainWindow._on_candidate_bpm_ready(fake, 1.0, 70.0, 71.0)  # 不應丟例外，靜默返回


def test_on_candidate_bpm_ready_skips_nan_samples():
    from gui.main_window import MainWindow

    coord = RppgParamCoordinator()
    coord.tick(0.0, AdaptiveCalibState(confidence=CONF_HIGH), dict(ROI_BASE_WEIGHTS))
    assert coord.phase == COORD_EVALUATING
    belt_status = SimpleNamespace(state="connected", bpm=70)
    fake = _fake_main_window(
        _rppg_param_coordinator=coord,
        _engine_controller=SimpleNamespace(belt_status=lambda: belt_status),
    )

    MainWindow._on_candidate_bpm_ready(fake, 1.0, float("nan"), 71.0)

    # NaN 樣本應被跳過，evaluator 內不應累積任何配對。
    assert coord.evaluator.evaluate().pairs_used == 0


def test_on_candidate_bpm_ready_adopt_calls_adopt_helper(monkeypatch):
    from gui.main_window import MainWindow

    coord = RppgParamCoordinator()
    coord.tick(0.0, AdaptiveCalibState(confidence=CONF_HIGH), dict(ROI_BASE_WEIGHTS))
    assert coord.phase == COORD_EVALUATING

    belt_status = SimpleNamespace(state="connected", bpm=70)
    adopt_calls = []
    fake = _fake_main_window(
        _rppg_param_coordinator=coord,
        _engine_controller=SimpleNamespace(belt_status=lambda: belt_status),
        _adopt_rppg_param_candidate=lambda: adopt_calls.append(True),
    )

    for i in range(8):
        MainWindow._on_candidate_bpm_ready(fake, float(i), 70.0, 80.0)  # cur=70 (殘差0) 候選=80 (殘差10)：候選較差
    # 上面刻意construct current 更好、candidate 更差 → 先驗證 rollback 分支不誤觸發 adopt
    assert adopt_calls == []

    # 重新驅動一個候選較佳的情境，驗證 adopt 分支會呼叫 _adopt_rppg_param_candidate。
    coord2 = RppgParamCoordinator()
    coord2.tick(0.0, AdaptiveCalibState(confidence=CONF_HIGH), dict(ROI_BASE_WEIGHTS))
    adopt_calls2 = []
    fake2 = _fake_main_window(
        _rppg_param_coordinator=coord2,
        _engine_controller=SimpleNamespace(belt_status=lambda: belt_status),
        _adopt_rppg_param_candidate=lambda: adopt_calls2.append(True),
    )
    for i in range(8):
        MainWindow._on_candidate_bpm_ready(fake2, float(i), 80.0, 71.0)  # belt=70：現行殘差10、候選殘差1
    assert adopt_calls2 == [True]


def test_resolve_current_roi_weights_falls_back_on_exception():
    from gui.main_window import MainWindow

    class _RaisingStore:
        def get_active_version(self):
            raise RuntimeError("no active version")

    fake = _fake_main_window(_rppg_calibration_store=_RaisingStore())
    weights = MainWindow._resolve_current_roi_weights(fake)
    assert weights == dict(ROI_BASE_WEIGHTS)


def test_resolve_current_roi_weights_uses_override_when_present():
    from gui.main_window import MainWindow

    override = {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}
    version = SimpleNamespace(params=SimpleNamespace(rppg_params={"roi_weights": override}))

    class _Store:
        def get_active_version(self):
            return version

    fake = _fake_main_window(_rppg_calibration_store=_Store())
    weights = MainWindow._resolve_current_roi_weights(fake)
    assert weights == pytest.approx(override)


# ── 使用者裁決 2：_persist_belt_calibration carry-forward rppg_params ─────────

class _CapturingStore:
    """capture save_new_version 的 kwargs，並可指定 active 版本的 rppg_params。"""

    def __init__(self, active_rppg_params) -> None:
        self._active = SimpleNamespace(
            id="active_v", model="bias",
            params=SimpleNamespace(bpm_offset=0.0, rppg_params=active_rppg_params),
        )
        self.saved_kwargs = None

    def get_active_version(self):
        return self._active

    def save_new_version(self, **kwargs):
        self.saved_kwargs = kwargs
        return SimpleNamespace(id="new_v")


def _persist_fake(store) -> SimpleNamespace:
    """_persist_belt_calibration 需要的最小 fake self：一個信心足夠的假校正器 +
    capture 用 store。"""
    cal_state = AdaptiveCalibState(
        confidence=CONF_HIGH, accepted_observations=20, pairs_used=20,
        offset_bpm=5.0, raw_residual_bpm=5.0, corrected_residual_bpm=0.5,
    )
    logs: list[str] = []
    ns = SimpleNamespace(
        _belt_calibrator=SimpleNamespace(state=lambda: cal_state),
        _rppg_calibration_store=store,
        _append_log=lambda m: logs.append(m),
    )
    ns._logs = logs
    return ns


def test_persist_carries_forward_rppg_params_from_active_version():
    """裁決 2：active 版本帶 rppg_params 時，offset-only 停止存檔仍保留該 rppg_params，
    避免同 session 先 adopt ROI 權重後停止校準被覆蓋遺失。"""
    from gui.main_window import MainWindow

    adopted = {"roi_weights": {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}}
    store = _CapturingStore(active_rppg_params=adopted)
    fake = _persist_fake(store)

    MainWindow._persist_belt_calibration(fake)

    assert store.saved_kwargs is not None
    assert store.saved_kwargs["rppg_params"] == adopted
    assert store.saved_kwargs["offset_bpm"] == pytest.approx(5.0)


def test_persist_offset_only_when_active_has_no_rppg_params():
    """裁決 2 邊界：active 版本無 rppg_params（OFF 路徑常態）時，行為與現況一致——
    仍傳 rppg_params=None，只存 offset。"""
    from gui.main_window import MainWindow

    store = _CapturingStore(active_rppg_params=None)
    fake = _persist_fake(store)

    MainWindow._persist_belt_calibration(fake)

    assert store.saved_kwargs is not None
    assert store.saved_kwargs["rppg_params"] is None


def test_persist_offset_only_when_active_lookup_raises():
    """裁決 2 容錯：讀 active 版本失敗時不阻斷存檔，退回只存 offset（rppg_params=None）。"""
    from gui.main_window import MainWindow

    class _RaisingActiveStore(_CapturingStore):
        def get_active_version(self):
            raise RuntimeError("boom")

    store = _RaisingActiveStore(active_rppg_params=None)
    fake = _persist_fake(store)

    MainWindow._persist_belt_calibration(fake)

    assert store.saved_kwargs is not None
    assert store.saved_kwargs["rppg_params"] is None
