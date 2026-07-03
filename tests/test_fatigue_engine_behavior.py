"""fatigue_engine 安全關鍵行為測試（2026-07-03 審核 P0-1 / P0-2 / B2 回歸鎖定）。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_engine import (  # noqa: E402
    FatigueEngine,
    FatigueParams,
    GazeTrackingModule,
    HeadMouthModule,
)


def _fake_landmarks() -> list[SimpleNamespace]:
    return [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]


def _face_landmarks() -> list[SimpleNamespace]:
    """幾何合理的假臉（通過 face_area/roll/yaw 品質 gate），沿用既有測試慣例。"""
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[1] = SimpleNamespace(x=0.50, y=0.45)
    pts[10] = SimpleNamespace(x=0.50, y=0.20)
    pts[152] = SimpleNamespace(x=0.50, y=0.82)
    pts[234] = SimpleNamespace(x=0.34, y=0.52)
    pts[454] = SimpleNamespace(x=0.66, y=0.52)
    pts[33] = SimpleNamespace(x=0.38, y=0.36)
    pts[263] = SimpleNamespace(x=0.62, y=0.38)
    for idx in (338, 297, 332, 284, 251, 389, 356, 323, 361, 288, 397, 365,
                379, 378, 400, 377, 148, 176, 149, 150, 136, 172, 58, 132,
                93, 127, 162, 21, 54, 103, 67, 109):
        pts[idx] = SimpleNamespace(x=0.50, y=0.35)
    return pts


# ── P0-1：無臉寬限期 ──────────────────────────────────────────────────────────

def test_no_face_within_grace_keeps_calibration() -> None:
    engine = FatigueEngine()
    engine.eye.calibrated = True
    engine.eye.base_ear_th = 0.21

    m = engine.on_no_face(10.0)          # 第一個無臉幀
    assert m.status == "NO_FACE"
    assert m.calibrated is True           # 寬限期內不清校準
    m = engine.on_no_face(10.5)          # 0.5s < no_face_reset_sec(1.0)
    assert engine.eye.calibrated is True
    assert engine.eye.base_ear_th == 0.21


def test_no_face_beyond_grace_resets_calibration() -> None:
    engine = FatigueEngine()
    engine.eye.calibrated = True

    engine.on_no_face(10.0)
    m = engine.on_no_face(10.0 + engine.p.no_face_reset_sec + 0.1)
    assert engine.eye.calibrated is False
    assert m.calibrated is False


# ── P0-2 / B2：微睡 latch 與姿態閘門 ─────────────────────────────────────────

def _head_ready(head: HeadMouthModule, *, pitch: float, t: float) -> None:
    head.head_pitch = pitch
    head._pitch_offset = 0.0
    head._pitch_calibrated = True
    head._last_pose_ok_t = t


def test_microsleep_latch_persists_while_head_down() -> None:
    p = FatigueParams()
    head = HeadMouthModule(p)
    lm = _fake_landmarks()

    _head_ready(head, pitch=-25.0, t=0.0)
    alert, _ = head.step(lm, 640, 480, 0.0, run_pose=False)
    assert alert is False  # 計時起點

    _head_ready(head, pitch=-25.0, t=p.head_microsleep_sec + 0.1)
    alert, _ = head.step(lm, 640, 480, p.head_microsleep_sec + 0.1, run_pose=False)
    assert alert is True
    assert head.microsleep_count == 1

    # 頭仍低垂：latch 必須持續為 True（單幀狀態會讓警報永不觸發），count 不重複累加
    _head_ready(head, pitch=-25.0, t=p.head_microsleep_sec + 1.0)
    alert, _ = head.step(lm, 640, 480, p.head_microsleep_sec + 1.0, run_pose=False)
    assert alert is True
    assert head.microsleep_count == 1

    # 頭抬起：解除
    _head_ready(head, pitch=0.0, t=p.head_microsleep_sec + 2.0)
    alert, _ = head.step(lm, 640, 480, p.head_microsleep_sec + 2.0, run_pose=False)
    assert alert is False


def test_microsleep_blocked_before_pitch_calibrated() -> None:
    p = FatigueParams()
    head = HeadMouthModule(p)
    lm = _fake_landmarks()

    head.head_pitch = -25.0
    head._pitch_calibrated = False       # offset 未定：不得判微睡
    head._last_pose_ok_t = 0.0
    head.step(lm, 640, 480, 0.0, run_pose=False)
    alert, _ = head.step(lm, 640, 480, p.head_microsleep_sec + 1.0, run_pose=False)
    assert alert is False
    assert head.microsleep_count == 0


def test_microsleep_blocked_when_pose_stale() -> None:
    p = FatigueParams()
    head = HeadMouthModule(p)
    lm = _fake_landmarks()

    _head_ready(head, pitch=-25.0, t=0.0)
    head.step(lm, 640, 480, 0.0, run_pose=False)
    # solvePnP 久未成功：姿態過期期間凍結，不觸發也不累加
    t_late = p.pose_stale_max_sec + p.head_microsleep_sec + 1.0
    alert, _ = head.step(lm, 640, 480, t_late, run_pose=False)
    assert alert is False
    assert head.microsleep_count == 0


def test_microsleep_timer_survives_brief_pose_gap() -> None:
    # 點頭伴隨運動模糊使 solvePnP 短暫失敗：計時凍結而非清空，
    # 姿態恢復且頭仍低垂時自原起點續算（三重審查軸B F3）
    p = FatigueParams()
    head = HeadMouthModule(p)
    lm = _fake_landmarks()

    _head_ready(head, pitch=-25.0, t=0.0)
    head.step(lm, 640, 480, 0.0, run_pose=False)          # 計時起點 t=0
    head.step(lm, 640, 480, 1.0, run_pose=False)           # t=1.0 姿態已過期（>0.75s 未更新）→ 凍結
    _head_ready(head, pitch=-25.0, t=2.0)                  # 姿態恢復，頭仍低垂
    alert, _ = head.step(lm, 640, 480, 2.0, run_pose=False)
    assert alert is True                                    # 2.0s >= head_microsleep_sec(1.5)，計時未被清空
    assert head.microsleep_count == 1


def _calibrate_pitch_with(head: HeadMouthModule, pitch: float) -> None:
    import gui.fatigue_engine as fe

    head._pitch_calib = [pitch] * 59
    head.head_pitch = pitch
    original = fe.solve_head_pose
    fe.solve_head_pose = lambda lm, w, h: (pitch, 0.0, 0.0)
    try:
        head.step(_fake_landmarks(), 640, 480, 0.0, run_pose=True)
    finally:
        fe.solve_head_pose = original


# ── G-M3：眨眼期間凍結凝視 ────────────────────────────────────────────────────

def test_blink_does_not_register_fake_saccade() -> None:
    from gui.fatigue_engine import LEFT_IRIS_CTR, RIGHT_IRIS_CTR

    p = FatigueParams()
    gaze = GazeTrackingModule(p)
    lm = _face_landmarks()

    gaze.step(lm, 0.0, True)                       # 建立 _prev_gaze
    gaze.step(lm, 0.1, True, eyes_closed=True)     # 眨眼幀：凍結
    assert gaze.is_saccade is False
    # 重新睜眼且 iris 位置大幅不同（眨眼期間眼高塌陷的典型假位移）：不得記為掃視
    lm2 = _face_landmarks()
    lm2[LEFT_IRIS_CTR] = SimpleNamespace(x=0.45, y=0.30)
    lm2[RIGHT_IRIS_CTR] = SimpleNamespace(x=0.68, y=0.30)
    gaze.step(lm2, 0.2, True)
    assert gaze.is_saccade is False
    assert len(gaze._saccade_times) == 0


# ── P2-1：掃視觀測窗暖機 ─────────────────────────────────────────────────────

def test_engine_seeds_baselines_from_profile() -> None:
    # P3：帶眉距/blink-temporal 基線的 profile → engine 建構即預置進 eye（免暖機）。
    from gui.personal_profile import PersonalProfile
    prof = PersonalProfile(
        valid=True, brow_dist_norm_awake=0.42,
        blink_dur_mean=0.12, blink_dur_std=0.02,
        blink_amp_mean=0.3, blink_amp_std=0.05,
        blink_openvel_mean=0.8, blink_openvel_std=0.1,
    )
    engine = FatigueEngine(personal_profile=prof)
    assert engine.eye._brow_baseline == 0.42
    assert engine.eye._blink_feature_baseline is not None
    assert engine.eye._blink_feature_baseline["duration"] == (0.12, 0.02)


def test_engine_without_profile_has_no_seeded_baselines() -> None:
    # 無 profile → 不預置任何基線（維持當 session 暖機建立，bit-identical）。
    engine = FatigueEngine()
    assert engine.eye._brow_baseline is None
    assert engine.eye._blink_feature_baseline is None


def test_seed_does_not_clobber_existing_baseline() -> None:
    # seed 只在尚未建立時生效：已建立的 session 基線不被 profile 覆寫。
    from gui.personal_profile import PersonalProfile
    engine = FatigueEngine()
    engine.eye._brow_baseline = 0.9
    engine.set_personal_profile(PersonalProfile(valid=True, brow_dist_norm_awake=0.42))
    assert engine.eye._brow_baseline == 0.9


def _gaze_landmarks(iris_dx: float) -> list[SimpleNamespace]:
    """眼角固定（眼寬 0.2）、虹膜相對眼心偏移 iris_dx 的假臉；用來製造可控 gaze 位置。"""
    import gui.fatigue_engine as fe
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[fe.LEFT_EYE_INNER] = SimpleNamespace(x=0.60, y=0.50)
    pts[fe.LEFT_EYE_OUTER] = SimpleNamespace(x=0.40, y=0.50)
    pts[fe.LEFT_EYE_TOP]   = SimpleNamespace(x=0.50, y=0.45)
    pts[fe.LEFT_EYE_BOT]   = SimpleNamespace(x=0.50, y=0.55)
    pts[fe.RIGHT_EYE_INNER] = SimpleNamespace(x=0.60, y=0.50)
    pts[fe.RIGHT_EYE_OUTER] = SimpleNamespace(x=0.40, y=0.50)
    pts[fe.RIGHT_EYE_TOP]   = SimpleNamespace(x=0.50, y=0.45)
    pts[fe.RIGHT_EYE_BOT]   = SimpleNamespace(x=0.50, y=0.55)
    pts[fe.LEFT_IRIS_CTR]  = SimpleNamespace(x=0.50 + iris_dx, y=0.50)
    pts[fe.RIGHT_IRIS_CTR] = SimpleNamespace(x=0.50 + iris_dx, y=0.50)
    return pts


def _stability_after_jitter(eff_std_th) -> float:
    from gui.fatigue_engine import FatigueParams, GazeTrackingModule
    gaze = GazeTrackingModule(FatigueParams())
    gaze._eff_gaze_fixed_std_th = eff_std_th
    # 12 幀、虹膜 x 在 ±0.01 抖動 → 產生非零 gaze std
    for i in range(12):
        dx = 0.01 if i % 2 else -0.01
        gaze.step(_gaze_landmarks(dx), i * 0.1, has_iris=True)
    return gaze.gaze_stability_index


def test_gaze_effective_threshold_takes_effect() -> None:
    # P2：同一抖動輸入，個人化較大的 gaze_fixed_std_th 應給較高的穩定度指數；
    # eff=None 必須與明確帶 p 常數（0.015）逐位元一致（bit-identical）。
    s_default = _stability_after_jitter(None)
    s_constant = _stability_after_jitter(0.015)
    s_loose = _stability_after_jitter(0.045)
    assert s_default == s_constant           # None 退回 p 常數
    assert s_loose > s_default               # 較大門檻 → 較高穩定度
    assert 0.0 <= s_default <= 1.0


def test_saccade_window_ready_requires_warmup() -> None:
    p = FatigueParams()
    gaze = GazeTrackingModule(p)
    lm = _face_landmarks()

    gaze.step(lm, 0.0, True)
    assert gaze.saccade_window_ready is False       # 剛開始觀測：不可信
    gaze.step(lm, p.gaze_warmup_sec + 0.1, True)
    assert gaze.saccade_window_ready is True


# ── G-M1：低頭對稱 pitch gate ────────────────────────────────────────────────

def _engine_with_pitch(pitch: float) -> FatigueEngine:
    engine = FatigueEngine()
    engine.eye.calibrated = True
    engine.eye.base_ear_th = 0.20
    engine.head._pitch_calibrated = True
    engine.head._pitch_offset = 0.0
    engine.head.head_pitch = pitch
    engine.head._last_pose_ok_t = 0.0

    import gui.fatigue_engine as fe

    original = fe.solve_head_pose
    fe.solve_head_pose = lambda lm, w, h: (pitch, 0.0, 0.0)
    try:
        engine.step(_face_landmarks(), 640, 480, 0.05)
    finally:
        fe.solve_head_pose = original
    return engine


def test_pitch_down_gate_suspends_ear_path() -> None:
    # 低頭超過 pitch_eye_gate_deg：EAR 路徑（可量測時間）必須停用
    gated = _engine_with_pitch(-20.0)
    assert gated.eye._eligible_start is None

    control = _engine_with_pitch(0.0)
    assert control.eye._eligible_start is not None


def test_pitch_offset_rejected_when_boot_posture_abnormal() -> None:
    # 開機頭已垂到胸前（|median| > pitch_offset_sane_deg=20）：offset 不採用，維持 0
    head = HeadMouthModule(FatigueParams())
    _calibrate_pitch_with(head, -25.0)
    assert head._pitch_calibrated is True
    assert head._pitch_offset == 0.0


def test_pitch_offset_accepts_normal_camera_tilt() -> None:
    # 常見相機俯仰角（如 -12°）必須被吸收進 offset，否則整片觸發低頭 gate（golden 實測教訓）
    head = HeadMouthModule(FatigueParams())
    _calibrate_pitch_with(head, -12.2)
    assert head._pitch_calibrated is True
    assert head._pitch_offset == -12.2
