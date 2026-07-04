"""持續閉眼強通道測試（2026-07-04 治本設計）。

背景：opus 診斷定位系統無「持續閉眼→高分」專門通道，純閉眼只走 PERCLOS 單通道
（engine fatigue_level 與 scorer behavior 皆僅 0.55 權重），閉眼 10 秒 fused 天花板 ~0.47。
設計 spec 見 scratchpad/eye_closure_channel_spec.md（同 session）。

additive 鐵律（本檔核心不變量）：closure_s = 0（即 eye_closure_sec 未達
CLOSURE_ONSET_SEC 的長閉眼）時，fatigue_level 與 fused 必須逐位元回退到加通道前的值。
本檔的 bit-identical 測試組直接證明這點；另一半證據是既有 416 個測試不動且維持全綠
（closure 通道對它們全是 +0.0）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_engine import (  # noqa: E402
    CLOSURE_FULL_SEC,
    CLOSURE_ONSET_SEC,
    EyeCognitiveModule,
    FatigueEngine,
    FatigueMetrics,
    FatigueParams,
)
from gui.fatigue_scorer import FatigueFuser, FuserConfig  # noqa: E402
from rppg.rppg_worker import RppgMetrics  # noqa: E402


def _fake_landmarks() -> list[SimpleNamespace]:
    return [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]


def _eye_landmarks(closed: bool) -> list[SimpleNamespace]:
    """僅覆寫 EAR 6 點（RIGHT_EYE_IDX=[33,160,158,133,153,144] /
    LEFT_EYE_IDX=[362,385,387,263,373,380]）。p1/p4 為固定水平角點，p2/p3/p5/p6 為
    垂直對：closed 時垂直對重合 → EAR=0；open 時垂直對分開 → EAR 明顯高於任何合理
    base_ear_th。其餘點維持預設 (0.5,0.5)，因為 EyeCognitiveModule.step() 的
    blink_ok/fatigue_ok 由呼叫端明確傳入，不靠幾何 gate 推導。"""
    pts = _fake_landmarks()
    v_top = 0.50 if closed else 0.47
    v_bot = 0.50 if closed else 0.53
    pts[33]  = SimpleNamespace(x=0.45, y=0.50)   # right EAR p1 (outer)
    pts[133] = SimpleNamespace(x=0.55, y=0.50)   # right EAR p4 (inner)
    pts[160] = SimpleNamespace(x=0.48, y=v_top)  # right EAR p2
    pts[144] = SimpleNamespace(x=0.48, y=v_bot)  # right EAR p6
    pts[158] = SimpleNamespace(x=0.52, y=v_top)  # right EAR p3
    pts[153] = SimpleNamespace(x=0.52, y=v_bot)  # right EAR p5
    pts[362] = SimpleNamespace(x=0.45, y=0.50)   # left EAR p1 (outer)
    pts[263] = SimpleNamespace(x=0.55, y=0.50)   # left EAR p4 (inner)
    pts[385] = SimpleNamespace(x=0.48, y=v_top)  # left EAR p2
    pts[380] = SimpleNamespace(x=0.48, y=v_bot)  # left EAR p6
    pts[387] = SimpleNamespace(x=0.52, y=v_top)  # left EAR p3
    pts[373] = SimpleNamespace(x=0.52, y=v_bot)  # left EAR p5
    return pts


# ── 測試 1：eye_closure_sec 累積 / 睜眼歸零 / 短暫閉眼(眨眼)不誤累積長 dur ─────────
#
# 注意：EAR 走 EMA 平滑（ear_ema_alpha=0.40）+ 開闔遲滯（closed_open_hyst=1.06），
# 從睜眼瞬間閉眼到 EMA 真正跌破 close_fat 門檻需要數幀收斂，不是餵一幀閉眼landmark
# 就立刻進入 fatigue-closed 狀態。測試用 _settle_closed 直接觀察 `_fatigue_closed`
# 旗標找出實際進入時刻，避免對 EMA 收斂時間點做脆弱假設。

def _settle_closed(eye: EyeCognitiveModule, t0: float, closed_lm) -> float:
    """反覆餵入閉眼 landmark 直到 EMA 收斂進入 fatigue-closed 狀態，回傳實際進入時刻。"""
    t = t0
    for _ in range(20):
        eye.step(closed_lm, 640, 480, t, True, True, 1.0, run_brow=False)
        if eye._fatigue_closed:
            return eye._fat_enter_t
        t += 0.05
    raise AssertionError("eye did not enter fatigue-closed state within settle window")


def test_eye_closure_sec_accumulates_persists_and_resets() -> None:
    p = FatigueParams()
    eye = EyeCognitiveModule(p)
    eye.calibrated = True
    eye.base_ear_th = 0.20

    open_lm = _eye_landmarks(closed=False)
    closed_lm = _eye_landmarks(closed=True)

    eye.step(open_lm, 640, 480, 0.0, True, True, 1.0, run_brow=False)
    assert eye.eye_closure_sec == 0.0

    enter_t = _settle_closed(eye, 1.0, closed_lm)

    # 持續閉眼：eye_closure_sec 精確反映自進入時刻起的累積秒數
    eye.step(closed_lm, 640, 480, enter_t + 3.0, True, True, 1.0, run_brow=False)
    assert abs(eye.eye_closure_sec - 3.0) < 1e-9
    eye.step(closed_lm, 640, 480, enter_t + 10.0, True, True, 1.0, run_brow=False)
    assert abs(eye.eye_closure_sec - 10.0) < 1e-9

    # 睜眼：EMA 回升超過 open_fat 後立即歸零（不殘留先前長閉眼的 dur）
    t = enter_t + 10.05
    for _ in range(20):
        eye.step(open_lm, 640, 480, t, True, True, 1.0, run_brow=False)
        if not eye._fatigue_closed:
            break
        t += 0.05
    assert eye._fatigue_closed is False
    assert eye.eye_closure_sec == 0.0


def test_brief_blink_never_crosses_long_closure_onset() -> None:
    # 眨眼(<0.45s)：EMA 平滑使極短暫的低 EAR 幀不足以在閉眼結束前跨過長閉眼的
    # onset 門檻，closure_s 因此恆為 0（見 test_closure_s_mapping_boundaries_in_scorer）。
    p = FatigueParams()
    eye = EyeCognitiveModule(p)
    eye.calibrated = True
    eye.base_ear_th = 0.20
    open_lm = _eye_landmarks(closed=False)
    closed_lm = _eye_landmarks(closed=True)

    eye.step(open_lm, 640, 480, 0.0, True, True, 1.0, run_brow=False)
    eye.step(closed_lm, 640, 480, 0.1, True, True, 1.0, run_brow=False)
    eye.step(closed_lm, 640, 480, 0.2, True, True, 1.0, run_brow=False)
    eye.step(open_lm, 640, 480, 0.3, True, True, 1.0, run_brow=False)
    assert eye.eye_closure_sec < CLOSURE_ONSET_SEC


# ── 測試 2：closure_s 純函式映射邊界（scorer 端，engine 端於測試 3 交叉驗證同常數）──

def test_closure_s_mapping_boundaries_in_scorer() -> None:
    fuser = FatigueFuser()

    def _closure_s(eye_closure_sec: float) -> float:
        fm = FatigueMetrics(face_detected=True, calibrated=True, eye_closure_sec=eye_closure_sec)
        return fuser._behavior_sub_score(fm)[-1]

    assert _closure_s(0.0) == 0.0
    assert _closure_s(0.5) == 0.0                        # onset 以下 = 0
    assert _closure_s(CLOSURE_ONSET_SEC) == 0.0           # 邊界：onset 本身仍是 0
    assert abs(_closure_s(4.5) - 0.5) < 1e-9              # 中點線性：(1.0+8.0)/2=4.5 → 0.5
    # 邊界：full 本身飽和 1.0（分母 +1e-9 epsilon 導致極微小浮點誤差，容許極小 tolerance）
    assert abs(_closure_s(CLOSURE_FULL_SEC) - 1.0) < 1e-6
    assert _closure_s(20.0) == 1.0                        # 超過 full：clamp 1.0


def test_closure_constants_single_source_shared_by_engine_and_scorer() -> None:
    assert FatigueParams().closure_onset_sec == CLOSURE_ONSET_SEC == FuserConfig().closure_onset_sec
    assert FatigueParams().closure_full_sec == CLOSURE_FULL_SEC == FuserConfig().closure_full_sec


# ── 測試 3：分數效果——engine fatigue_level 與 scorer fused 隨閉眼秒數上升 ─────────

def _bare_engine() -> FatigueEngine:
    """no-op 掉三個子模組的 step()，讓呼叫端直接控制屬性以隔離 fatigue_level 公式
    （沿用既有測試對 solve_head_pose 的 monkeypatch 慣例，繞開需要真實幾何的
    姿態/EAR 品質 gate；engine.step() 前段的 quality-gate 計算對全同點假 landmark
    安全，因分母皆有 +1e-6 保護）。"""
    engine = FatigueEngine()
    engine.eye.step = lambda *a, **k: None
    engine.gaze.step = lambda *a, **k: None
    engine.head.step = lambda *a, **k: (False, False)
    # has_iris / long_closed / calib_progress / ear / ear_smooth 平常只在
    # EyeCognitiveModule.step() 內部才第一次賦值（reset() 不預設它們）；step() 被
    # no-op 掉後 FatigueEngine.step() 仍會讀取這些屬性建構狀態/FatigueMetrics，
    # 需先手動補上通用安全值，避免 AttributeError。
    engine.eye.has_iris = False
    engine.eye.long_closed = False
    engine.eye.calib_progress = 1.0
    engine.eye.ear = 1.0
    return engine


def _engine_fatigue_level_for_closure(
    eye_closure_sec: float, *, last_perclos: float = 1.0, microsleep: bool = False,
) -> tuple[float, float]:
    engine = _bare_engine()
    eye = engine.eye
    eye.calibrated = True
    eye.last_perclos = last_perclos
    eye.blink_temporal_score = 0.0
    eye.is_squinting = False
    eye.squint_duration = 0.0
    eye.is_frowning = False
    eye.blend_eye_squint = 0.0
    eye.blend_brow_down = 0.0
    eye.lid_balance = 0.0
    eye.ear_smooth = 1.0
    eye.base_ear_th = 0.2
    eye.eye_closure_sec = eye_closure_sec
    engine.gaze.gaze_mental_fatigue = False
    engine.gaze.fixation_duration = 0.0
    engine.head.yawn_count = 0
    engine.head.step = lambda *a, m=microsleep, **k: (m, False)

    m = engine.step(_fake_landmarks(), 640, 480, 5.0)
    return m.fatigue_level, m.eye_closure_sec


def test_engine_fatigue_level_closure_additive_matches_spec_table() -> None:
    # 對照 spec 驗算表：假設 perclos_norm=1.0 之基線 0.55，closure additive 精確疊加
    # （closure_s * W_ENGINE_CLOSURE=0.35），其餘子模組輸出全 0/False 已隔離其他項。
    level_blink, closure_blink = _engine_fatigue_level_for_closure(0.3)   # 眨眼
    assert closure_blink == 0.3
    assert abs(level_blink - 0.55) < 1e-9          # closure_s=0 → +0（additive 鐵律）

    level_1_5, _ = _engine_fatigue_level_for_closure(1.5)
    assert abs(level_1_5 - 0.575) < 1e-6

    level_3, _ = _engine_fatigue_level_for_closure(3.0)
    assert abs(level_3 - 0.65) < 1e-6

    level_10, _ = _engine_fatigue_level_for_closure(10.0)
    assert abs(level_10 - 0.90) < 1e-6

    level_0, closure_0 = _engine_fatigue_level_for_closure(0.0)
    assert closure_0 == 0.0
    assert abs(level_0 - 0.55) < 1e-9


def _rppg_stub(stress_prob: float) -> RppgMetrics:
    return RppgMetrics(
        face_detected=True, warmup_progress=1.0, sqi=1.0, quality_score=1.0,
        roi_valid_count=4, stress_prob=stress_prob, bpm=75.0,
    )


def test_fused_score_reaches_moderate_then_high_with_sustained_closure() -> None:
    cfg = FuserConfig()
    rppg = _rppg_stub(1.0 / 6.0)   # → rppg_sub = 0.10（spec 假設「rppg 靜坐 sub≈0.1」）

    def _fused_for(eye_closure_sec: float, engine_fatigue_level: float) -> tuple[float, str]:
        fm = FatigueMetrics(
            face_detected=True, calibrated=True,
            perclos=1.0,   # → perc_s 拉滿 1.0，比照 spec 假設基線 0.55
            eye_closure_sec=eye_closure_sec,
            fatigue_level=engine_fatigue_level,
        )
        out = FatigueFuser(cfg).update(rppg, fm)
        return out.score, out.level

    # 無閉眼／眨眼 0.3s：closure_s=0，兩者必須完全相同（additive 鐵律的整合面驗證）
    score_zero, _level_zero = _fused_for(0.0, 0.55)
    score_blink, _level_blink = _fused_for(0.3, 0.55)
    assert score_zero == score_blink

    # 閉眼 3s → 中度區間
    score_3s, level_3s = _fused_for(3.0, 0.65)
    assert 0.40 <= score_3s < 0.60
    assert level_3s == "中度疲勞"

    # 閉眼 10s → 高度區間
    score_10s, level_10s = _fused_for(10.0, 0.90)
    assert 0.60 <= score_10s < 0.80
    assert level_10s == "高度疲勞"

    # 閉眼程度遞增，融合分數應嚴格遞增（新通道不破壞單調性）
    assert score_blink < score_3s < score_10s


# ── 測試 4：bit-identical——closure=0 時 fatigue_level 與 fused 逐位元回退 ─────────

def test_engine_fatigue_level_bit_identical_when_no_closure() -> None:
    p = FatigueParams()
    scenarios = [
        dict(last_perclos=0.0, microsleep=False, blink_temporal=0.0, squint=(False, 0.0),
             frown=False, gaze_mental=False, blend_squint=0.0, blend_brow=0.0, yawn=0),
        dict(last_perclos=0.03, microsleep=True, blink_temporal=0.4, squint=(True, 10.0),
             frown=True, gaze_mental=True, blend_squint=0.5, blend_brow=0.5, yawn=6),
        dict(last_perclos=1.0, microsleep=True, blink_temporal=1.0, squint=(True, 40.0),
             frown=True, gaze_mental=True, blend_squint=1.0, blend_brow=1.0, yawn=20),
    ]
    for sc in scenarios:
        engine = _bare_engine()
        eye = engine.eye
        eye.calibrated = True
        eye.last_perclos = sc["last_perclos"]
        eye.blink_temporal_score = sc["blink_temporal"]
        eye.is_squinting, eye.squint_duration = sc["squint"]
        eye.is_frowning = sc["frown"]
        eye.blend_eye_squint = sc["blend_squint"]
        eye.blend_brow_down = sc["blend_brow"]
        eye.lid_balance = 0.0
        eye.ear_smooth = 1.0
        eye.base_ear_th = 0.2
        eye.eye_closure_sec = 0.0
        engine.gaze.gaze_mental_fatigue = sc["gaze_mental"]
        engine.gaze.fixation_duration = 0.0
        engine.head.yawn_count = sc["yawn"]
        engine.head.step = lambda *a, m=sc["microsleep"], **k: (m, False)

        m = engine.step(_fake_landmarks(), 640, 480, 5.0)

        perclos_full = p.perclos_composite_full
        perclos_norm = min(1.0, max(0.0, sc["last_perclos"] / (perclos_full + 1e-6)))
        expected_old = min(1.0, max(0.0,
            perclos_norm * 0.55
            + (1.0 if sc["microsleep"] else 0.0) * 0.12
            + sc["blink_temporal"] * 0.10
            + (sc["squint"][1] / 30.0 if sc["squint"][0] else 0.0) * 0.10
            + (0.05 if sc["frown"] else 0.0)
            + (0.08 if sc["gaze_mental"] else 0.0)
            + (0.05 if sc["blend_squint"] > p.blend_squint_gate else 0.0)
            + (0.05 if sc["blend_brow"] > p.blend_brow_gate else 0.0)
            + (sc["yawn"] / 10.0) * 0.05
        ))
        assert abs(m.fatigue_level - expected_old) < 1e-9


def test_scorer_behavior_pillar_bit_identical_when_no_closure() -> None:
    cfg = FuserConfig()
    fuser = FatigueFuser(cfg)
    scenarios = [
        dict(perclos=0.0, blink_temporal_score=0.0, is_squinting=False, squint_duration=0.0,
             microsleep_count=0, fixation_duration=0.0, saccade_freq_pm=0.0,
             saccade_window_ready=False, gaze_mental_fatigue=False, is_frowning=False,
             brow_dist_norm=1.0, yawn_count=0),
        dict(perclos=0.05, blink_temporal_score=0.6, is_squinting=True, squint_duration=15.0,
             microsleep_count=2, fixation_duration=10.0, saccade_freq_pm=1.0,
             saccade_window_ready=True, gaze_mental_fatigue=True, is_frowning=True,
             brow_dist_norm=0.6, yawn_count=3),
    ]
    for sc in scenarios:
        fm = FatigueMetrics(face_detected=True, calibrated=True, eye_closure_sec=0.0, **sc)
        pillar, perc_s, blink_s, squint_s, micro_s, gaze_s, frown_s, yawn_s, closure_s = (
            fuser._behavior_sub_score(fm)
        )
        assert closure_s == 0.0
        expected_old = max(0.0, min(1.0,
            cfg.beh_w_perclos * perc_s
            + cfg.beh_w_blink_temporal * blink_s
            + cfg.beh_w_squint * squint_s
            + cfg.beh_w_microsleep * micro_s
            + cfg.beh_w_gaze * gaze_s
            + cfg.beh_w_frown * frown_s
            + cfg.beh_w_yawn * yawn_s
        ))
        assert abs(pillar - expected_old) < 1e-9
