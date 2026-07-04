"""下視偵測器（down-gaze detector）測試（2026-07-04）。

背景：眼睛睜開但視線往下看/頭微低帶動眼皮下垂時，EAR 會跌破閉眼門檻，被持續閉眼
強通道誤判為疲勞（實機發現）。偵測器成立時以 pitch gate 相同語意暫停 EAR 衍生累積
（blink_ok/fatigue_ok=False）。

紅線鐵律（本檔核心不變量）：偵測器未觸發時，所有輸出必須逐位元回退現況——一般幀
（睜眼正視）與既有測試場景（眨眼、真閉眼、pitch gate）皆不受影響。

Landmark 慣例：沿用 tests/test_fatigue_engine_behavior.py 的 _face_landmarks()（幾何合理
假臉，通過 face_area/roll/yaw 品質 gate）與 _gaze_landmarks()（眼角/眼高/虹膜點可控凝視
位置）慣例，疊加 EAR 6 點（RIGHT_EYE_IDX/LEFT_EYE_IDX）獨立控制張闔程度。EAR 垂直點
（160/158/153/144、385/387/373/380）與凝視用眼高點（159/145、386/374）索引不重疊，
可各自獨立控制、互不干擾。

關鍵設計筆記（除錯後確認，供未來維護者參考）：
1. `EyeCognitiveModule` 的 blink/fatigue 閉眼狀態機用「原始/平滑 EAR < close_blink/
   close_fat（= base_ear_th，即 1.0×）」判斷，而 `GazeTrackingModule.step()` 一旦
   `eyes_closed=True` 就會直接 return、凍結 gaze_x/gaze_y（不更新也不歸零）。因此若
   要讓下視偵測器在「眼睛仍睜開、凝視仍持續更新」的狀態下量到有效 gaze_y，測試用的
   EAR 必須落在 (close_blink=1.0×base, downgaze_ear_hi=1.10×base) 這個更窄的子區間，
   而非 downgaze_ear_floor(0.45×) ~ downgaze_ear_hi(1.10×) 的整個下視偵測帶——後者
   下半段（0.45×~1.0×）在真實系統中會先被既有 blink 狀態機判成「已閉眼」而凍結
   gaze，本檔用 EAR_DOWNGAZE_GAP 精確控制落在該窄帶內以求得可測的正向案例。
2. `EyeCognitiveModule.step()` 的 `if self._fatigue_closed and self._fat_enter_t:`
   用真值判斷 `_fat_enter_t`（非 `is not None`），若進入閉眼的時刻恰為 t_now=0.0，
   `0.0` 為 falsy 導致 `fat_dur` 恆算不出來——這是既有程式碼的既存行為，非本次改動
   引入。沿用 tests/test_eye_closure_channel.py 的既有慣例（該檔 `_settle_closed`
   一律從 t0=1.0 起算）：本檔任何預期「真閉眼累積」的測試一律不從 t_now=0.0 開始。
3. `_p()` 將正規化座標轉整數像素（`int(x*w)`），640×480 解析度下對極小的 EAR gap
   差異量化過粗；改用等比放大的 6400×4800（同 4:3 長寬比，不影響 face_area/roll/
   yaw 等以比例表示的品質 gate）取得足夠精細的 EAR 控制粒度。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_engine import (  # noqa: E402
    FatigueEngine,
    FatigueMetrics,
    FatigueParams,
)

# 合成影格解析度：與 640×480 同 4:3 比例等比放大，只為取得夠精細的 EAR 控制粒度
# （face_area/roll/yaw 等品質 gate 皆以比例表示，解析度縮放不影響其數值）。
W, H = 6400, 4800


# ── 幾何假臉（沿用 test_fatigue_engine_behavior._face_landmarks 慣例）───────────

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


# EAR gap（v_top/v_bot 對稱於 y=0.50 的垂直間距）→ 搭配 base_ear_th=0.20 的實測值
# （見檔頭筆記 3；W,H=6400,4800 下用 eye_aspect_ratio() 實測校準，非理論公式估算）：
EAR_OPEN_GAP      = 0.06    # EAR=0.45，遠高於 downgaze_ear_hi(0.22)：正常睜眼
EAR_DOWNGAZE_GAP  = 0.028   # EAR≈0.2109，落在 (close_blink=0.20, hi=0.22) 窄帶內：
                            # 眼睛仍睜開（blink 狀態機不判閉眼、凝視持續更新），
                            # 但落入下視偵測器的判定帶（見檔頭筆記 1）
EAR_MIDBAND_GAP   = 0.02    # EAR=0.15，落在 (floor=0.09, close_fat=0.20) 中間帶：
                            # 實機誤判真正發生的區間——blink/fatigue 狀態機會判「閉眼」
                            # 並凍結 gaze，無偵測器時 closure 強通道開始累積
EAR_CLOSED_GAP    = 0.00    # EAR=0.00，遠低於 floor(0.09)：真閉眼

GAZE_STRAIGHT_DY = 0.00  # gy=0，正視
GAZE_DOWN_DY     = 0.03  # gy=0.25（眼高 0.12），> downgaze_gy_th(0.12)：視線往下看

BASE_EAR_TH = 0.20


def _eye_gaze_landmarks(*, ear_gap: float, gaze_dy: float) -> list[SimpleNamespace]:
    """在幾何合理假臉上疊加可控 EAR 與可控垂直凝視位置。

    眼角（33/133/263/362）同時是 EAR 水平分母與 gaze 眼心/眼寬分母——沿用真實
    landmark 語意（同一角點在兩種計算中重複使用是既有設計，非本檔杜撰）。
    EAR 垂直點（160/144/158/153、385/380/387/373）與凝視眼高點
    （LEFT/RIGHT_EYE_TOP/BOT=159/145/386/374）索引不重疊，可獨立控制。
    """
    pts = _face_landmarks()
    v_top = 0.50 - ear_gap / 2.0
    v_bot = 0.50 + ear_gap / 2.0
    # 眼角
    pts[33]  = SimpleNamespace(x=0.35, y=0.50)   # LEFT_EYE_OUTER / EAR-A p1
    pts[133] = SimpleNamespace(x=0.45, y=0.50)   # LEFT_EYE_INNER / EAR-A p4
    pts[362] = SimpleNamespace(x=0.55, y=0.50)   # RIGHT_EYE_INNER / EAR-B p1
    pts[263] = SimpleNamespace(x=0.65, y=0.50)   # RIGHT_EYE_OUTER / EAR-B p4
    # EAR 垂直點
    pts[160] = SimpleNamespace(x=0.38, y=v_top)
    pts[144] = SimpleNamespace(x=0.38, y=v_bot)
    pts[158] = SimpleNamespace(x=0.42, y=v_top)
    pts[153] = SimpleNamespace(x=0.42, y=v_bot)
    pts[385] = SimpleNamespace(x=0.58, y=v_top)
    pts[380] = SimpleNamespace(x=0.58, y=v_bot)
    pts[387] = SimpleNamespace(x=0.62, y=v_top)
    pts[373] = SimpleNamespace(x=0.62, y=v_bot)
    # 眼高（凝視用；與上方 EAR 垂直點索引不同，互不干擾）
    pts[159] = SimpleNamespace(x=0.40, y=0.44)   # LEFT_EYE_TOP
    pts[145] = SimpleNamespace(x=0.40, y=0.56)   # LEFT_EYE_BOT
    pts[386] = SimpleNamespace(x=0.60, y=0.44)   # RIGHT_EYE_TOP
    pts[374] = SimpleNamespace(x=0.60, y=0.56)   # RIGHT_EYE_BOT
    # 虹膜（凝視位置）
    iris_y = 0.50 + gaze_dy
    pts[468] = SimpleNamespace(x=0.40, y=iris_y)  # LEFT_IRIS_CTR
    pts[473] = SimpleNamespace(x=0.60, y=iris_y)  # RIGHT_IRIS_CTR
    return pts


def _prepared_engine() -> FatigueEngine:
    """繞過真實 5 秒 EAR 校準流程，直接就緒（沿用既有測試慣例，
    見 tests/test_fatigue_engine_behavior.py 的 _engine_with_pitch）。"""
    engine = FatigueEngine()
    engine.eye.calibrated = True
    engine.eye.base_ear_th = BASE_EAR_TH
    return engine


def _run(engine: FatigueEngine, lm, n: int, dt: float = 0.05, t0: float = 0.0) -> FatigueMetrics:
    """連續餵入同一組假臉 n 幀，回傳最後一幀的 FatigueMetrics。"""
    t = t0
    m: FatigueMetrics | None = None
    for _ in range(n):
        m = engine.step(lm, W, H, t)
        t += dt
    assert m is not None
    return m


# ── 1. 下視 → 不累積 ─────────────────────────────────────────────────────────

def test_downgaze_latches_and_suppresses_ear_accumulation() -> None:
    engine = _prepared_engine()
    lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)

    m = _run(engine, lm, 20)

    assert m.down_gaze_active is True
    assert m.eye_closure_sec == 0.0
    # fatigue_level 不應因下視被強通道誤判拉高（closure additive 恆 0）
    assert m.fatigue_level < 0.2


# ── 1b. 中間帶正例＋對照組：抑制效果的直接證明（審查軸C Critical 的解法）────────
# 上方 test 1 的 EAR≈0.2109 高於 close_fat(0.20)，本來就不會被判閉眼——它驗證的是
# latch 行為，不是抑制效果。真正的誤判帶是 (floor=0.09, close_fat=0.20) 中間帶：
# 兩階段建構（先窄帶建立 gaze_y 並 latch，再降到中間帶；此時 blink/fatigue 狀態機
# 判閉眼、gaze 凍結在下視值，偵測器維持成立）。正例＋反例對照才能證明抑制生效。

def test_downgaze_suppresses_midband_ear_that_would_be_misjudged_as_closure() -> None:
    engine = _prepared_engine()
    latch_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)
    midband_lm = _eye_gaze_landmarks(ear_gap=EAR_MIDBAND_GAP, gaze_dy=GAZE_DOWN_DY)

    # 階段一：窄帶 latch on（t0=1.0 避開 _fat_enter_t==0.0 falsy 陷阱，見檔頭筆記 2）
    m1 = _run(engine, latch_lm, 20, t0=1.0)
    assert m1.down_gaze_active is True

    # 階段二：EAR 降到中間帶 0.15——無偵測器時會被判閉眼、closure 開始累積
    t = 2.0
    m = None
    for _ in range(30):
        m = engine.step(midband_lm, W, H, t)
        t += 0.05

    assert m.down_gaze_active is True
    assert m.eye_closure_sec == 0.0          # 抑制生效：closure 不累積
    assert engine.eye._fatigue_closed is False


def test_midband_ear_without_downgaze_accumulates_as_closure() -> None:
    """對照組（反例）：同樣中間帶 EAR=0.15 但視線正視、無 latch → 走既有閉眼累積
    路徑。證明上一個測試的 eye_closure_sec==0.0 確實來自下視偵測器的抑制，
    而非中間帶本身不會累積。"""
    engine = _prepared_engine()
    midband_lm = _eye_gaze_landmarks(ear_gap=EAR_MIDBAND_GAP, gaze_dy=GAZE_STRAIGHT_DY)

    t = 1.0
    m = None
    for _ in range(30):
        m = engine.step(midband_lm, W, H, t)
        assert m.down_gaze_active is False
        t += 0.05

    assert engine.eye._fatigue_closed is True
    assert m.eye_closure_sec > 0.5


# ── 2. 真閉眼不受影響（floor guard：防漏報核心）───────────────────────────────

def test_true_closure_never_latches_downgaze_and_accumulates_normally() -> None:
    engine = _prepared_engine()
    # 刻意搭配「視線往下看」證明 floor guard 本身（EAR<floor）足以排除偵測器，
    # 不依賴 gaze_y 方向。t0 從 1.0 起算，避開 _fat_enter_t==0.0 的既存 falsy 陷阱
    # （見檔頭筆記 2）。
    closed_lm = _eye_gaze_landmarks(ear_gap=EAR_CLOSED_GAP, gaze_dy=GAZE_DOWN_DY)

    t = 1.0
    m = None
    for _ in range(30):
        m = engine.step(closed_lm, W, H, t)
        assert m.down_gaze_active is False
        t += 0.05

    assert m.eye_closure_sec > 1.0   # 累積未被下視偵測器打斷


# ── 3. 眨眼不受影響 ──────────────────────────────────────────────────────────

def test_brief_blink_unaffected_by_downgaze_detector() -> None:
    engine = _prepared_engine()
    open_lm = _eye_gaze_landmarks(ear_gap=EAR_OPEN_GAP, gaze_dy=GAZE_STRAIGHT_DY)
    closed_lm = _eye_gaze_landmarks(ear_gap=EAR_CLOSED_GAP, gaze_dy=GAZE_STRAIGHT_DY)

    t = 1.0
    m = engine.step(open_lm, W, H, t)
    assert m.down_gaze_active is False

    # 短閉眼（眨眼），EMA 收斂需要數幀，沿用既有測試的 settle 慣例
    for _ in range(6):
        t += 0.03
        m = engine.step(closed_lm, W, H, t)
        assert m.down_gaze_active is False

    for _ in range(20):
        t += 0.03
        m = engine.step(open_lm, W, H, t)
        assert m.down_gaze_active is False
        if not engine.eye._blink_closed:
            break

    assert engine.eye.blink_count >= 1


# ── 4. 下視中途真閉眼 → 恢復 ─────────────────────────────────────────────────

def test_downgaze_then_real_closure_resumes_accumulation_after_exit_debounce() -> None:
    engine = _prepared_engine()
    downgaze_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)
    closed_lm = _eye_gaze_landmarks(ear_gap=EAR_CLOSED_GAP, gaze_dy=GAZE_DOWN_DY)

    # 階段一：下視 latch on，不累積（t0=1.0，同避開 _fat_enter_t==0.0 陷阱）
    m1 = _run(engine, downgaze_lm, 20, t0=1.0)
    assert m1.down_gaze_active is True
    assert m1.eye_closure_sec == 0.0

    # 階段二：轉真閉眼，經 exit 去抖後解除 latch、開始累積
    t = 2.0
    m = None
    for _ in range(40):
        m = engine.step(closed_lm, W, H, t)
        t += 0.05

    assert m.down_gaze_active is False
    assert m.eye_closure_sec > 0.5


# ── 5. pitch gate 與下視同時成立：抑制仍正確 ─────────────────────────────────
# 誠實註記（審查軸C Warning）：pitch 分支與下視分支的抑制效果完全相同
# （blink_ok/fatigue_ok=False），最終輸出無法區分「哪個分支先擋」——本測試驗證的是
# 「兩者同時成立時 EAR 路徑仍被正確抑制、且兩個 gate 狀態可同時共存」，
# elif 短路的優先順序屬程式碼層事實（見 fatigue_engine.py pitch gate 鏈尾註解），
# 非本測試可觀測行為。

def test_pitch_gate_and_downgaze_coexist_suppression_intact() -> None:
    import gui.fatigue_engine as fe

    engine = _prepared_engine()
    engine.head._pitch_calibrated = True
    engine.head._pitch_offset = 0.0
    engine.head.head_pitch = -20.0   # 超過 head_pitch_down/pitch_eye_gate 皆會觸發的低頭
    engine.head._last_pose_ok_t = 0.0

    downgaze_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)

    original = fe.solve_head_pose
    fe.solve_head_pose = lambda lm, w, h: (-20.0, 0.0, 0.0)
    try:
        m = _run(engine, downgaze_lm, 20, t0=1.0)
    finally:
        fe.solve_head_pose = original

    # 行為與純 pitch gate 一致：EAR 路徑同樣被暫停，eye_closure_sec 不累積；
    # 且下視偵測器確實同時 latch（證明本情境真的是「兩 gate 共存」而非只有 pitch）
    assert m.eye_closure_sec == 0.0
    assert engine.eye._eligible_start is None
    assert engine._downgaze_active is True


# ── 6. 未觸發 bit-identical：一般幀（睜眼正視）─────────────────────────────────

def test_normal_open_eyes_straight_gaze_never_activates_downgaze() -> None:
    engine = _prepared_engine()
    lm = _eye_gaze_landmarks(ear_gap=EAR_OPEN_GAP, gaze_dy=GAZE_STRAIGHT_DY)

    t = 1.0
    m = None
    for _ in range(25):
        m = engine.step(lm, W, H, t)
        assert m.down_gaze_active is False
        t += 0.05

    assert engine.eye.blink_count == 0
    assert m.eye_closure_sec == 0.0
    # bit-identical 強化（仿 tests/test_eye_closure_channel.py 的公式化寫法）：
    # 本場景所有 fatigue_level 構成項獨立推導皆為 0（perclos=0、無 microsleep、
    # blink_temporal=0、無 squint/frown/gaze_mental/blendshape 超標/哈欠、closure
    # additive=0），期望值恆等於 0.0；早期預警與狀態亦須回退現況。
    assert m.fatigue_level == 0.0
    assert m.early_warning is False
    assert m.status == "OK"


# ── 7. early_warning gate：down_gaze_active 時該條款不得觸發 ───────────────────

def _bare_engine() -> FatigueEngine:
    """no-op 掉三個子模組的 step()，直接控制屬性隔離 early_warning 公式
    （沿用 tests/test_eye_closure_channel.py 的 _bare_engine 慣例）。"""
    engine = FatigueEngine()
    engine.eye.step = lambda *a, **k: None
    engine.gaze.step = lambda *a, **k: None
    engine.head.step = lambda *a, **k: (False, False)
    engine.eye.has_iris = False
    engine.eye.long_closed = False
    engine.eye.calib_progress = 1.0
    engine.eye.ear = 1.0
    return engine


def _early_warning_for(*, down_gaze_active: bool) -> bool:
    engine = _bare_engine()
    eye = engine.eye
    eye.calibrated = True
    eye.last_perclos = 0.0
    eye.blink_temporal_score = 0.0
    eye.is_squinting = False
    eye.squint_duration = 0.0
    eye.is_frowning = False
    eye.blend_eye_squint = 0.0
    eye.blend_brow_down = 0.0
    eye.eye_closure_sec = 0.0
    engine.gaze.gaze_mental_fatigue = False
    engine.gaze.fixation_duration = 0.0
    engine.head.yawn_count = 0
    # 目標條款：lid_balance > gate 且 ear_smooth < base*1.25
    eye.lid_balance = FatigueParams().lid_balance_gate_th + 0.1
    eye.base_ear_th = 0.20
    eye.ear_smooth = 0.20 * 1.10   # < base*1.25
    engine._downgaze_active = down_gaze_active

    m = engine.step(_face_landmarks(), W, H, 5.0)
    return m.early_warning


def test_early_warning_lid_balance_clause_suppressed_when_downgaze_active() -> None:
    assert _early_warning_for(down_gaze_active=False) is True
    assert _early_warning_for(down_gaze_active=True) is False


# ── 8. 校準期內偵測器一律不成立 ───────────────────────────────────────────────

def test_downgaze_blocked_before_calibration() -> None:
    engine = FatigueEngine()   # eye.calibrated 預設 False，未手動繞過
    downgaze_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)

    t = 0.0
    for _ in range(20):
        m = engine.step(downgaze_lm, W, H, t)
        assert m.down_gaze_active is False
        assert engine.eye.calibrated is False   # 確認本測試真的還在校準期
        t += 0.05


# ── 9. 無虹膜（has_iris=False）偵測器一律不成立 ────────────────────────────────

def test_no_iris_landmarks_never_activate_downgaze() -> None:
    engine = _prepared_engine()
    # 截去虹膜點（468+）：EyeCognitiveModule 以 len(lm) >= 478 判定 has_iris=False
    lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)[:468]
    # 模擬殘留的舊 gaze 值：即使 gaze_y 超門檻，偵測器仍須因 has_iris=False 不成立
    engine.gaze.gaze_y = 0.25

    t = 1.0
    for _ in range(20):
        m = engine.step(lm, W, H, t)
        assert m.down_gaze_active is False
        t += 0.05
    assert engine._downgaze_active is False


# ── 10. 短暫掉臉與去抖交互（審查軸A Critical 的回歸測試）──────────────────────
# on_no_face 期間 step() 不執行、條件無觀測，空窗時間不得計入 enter/exit 去抖；
# 修法：一掉臉即清兩個去抖計時器（不等 1 秒寬限期），_downgaze_active 沿用寬限期語意。

def test_brief_no_face_does_not_bypass_enter_debounce() -> None:
    engine = _prepared_engine()
    lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)

    # 條件才真連續成立 ~0.10s（< enter_sec=0.30），未 latch
    t = 1.0
    for _ in range(3):
        engine.step(lm, W, H, t)
        t += 0.05
    assert engine._downgaze_active is False

    # 短暫掉臉 0.5s（< no_face_reset_sec=1.0 寬限期，校準/active 不清）
    engine.on_no_face(t)
    t += 0.5

    # 臉回來且條件成立的第一幀：不得立刻 latch（掉臉空窗不得計入 enter 去抖）
    m = engine.step(lm, W, H, t)
    assert m.down_gaze_active is False

    # 臉回來後重新連續成立達 enter_sec 才 latch
    for _ in range(8):
        t += 0.05
        m = engine.step(lm, W, H, t)
    assert m.down_gaze_active is True


def test_brief_no_face_does_not_bypass_exit_debounce() -> None:
    engine = _prepared_engine()
    downgaze_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)
    open_lm = _eye_gaze_landmarks(ear_gap=EAR_OPEN_GAP, gaze_dy=GAZE_STRAIGHT_DY)

    # latch on
    _run(engine, downgaze_lm, 20, t0=1.0)
    assert engine._downgaze_active is True

    # 條件開始不成立：偵測器用「前一幀」屬性判定，第一幀 open_lm 仍以 stale 下視
    # 屬性為真、lost_since 不會起跑——必須餵兩幀讓 exit 計時真正在掉臉前起算
    # （t=2.05 起跑），否則本測試無鑑別力（無修法時 lost_since 也是臉回來才起算）。
    t = 2.0
    engine.step(open_lm, W, H, t)
    engine.step(open_lm, W, H, t + 0.05)
    assert engine._downgaze_active is True

    # 短暫掉臉 0.5s（< 寬限期）：active 須保留、exit 計時須清空
    engine.on_no_face(t + 0.10)
    assert engine._downgaze_active is True
    t += 0.60

    # 臉回來第一幀（條件不成立）：不得立刻解除
    # （若空窗被計入 exit 去抖，2.60-2.05=0.55 >= 0.3 會誤解除）
    engine.step(open_lm, W, H, t)
    assert engine._downgaze_active is True

    # 重新連續不成立達 exit_sec 才解除
    for _ in range(8):
        t += 0.05
        engine.step(open_lm, W, H, t)
    assert engine._downgaze_active is False


def test_long_no_face_fully_resets_downgaze_state() -> None:
    engine = _prepared_engine()
    downgaze_lm = _eye_gaze_landmarks(ear_gap=EAR_DOWNGAZE_GAP, gaze_dy=GAZE_DOWN_DY)

    _run(engine, downgaze_lm, 20, t0=1.0)
    assert engine._downgaze_active is True

    # 掉臉超過 no_face_reset_sec：走既有全重置路徑，active 與計時器全清
    engine.on_no_face(2.0)
    engine.on_no_face(2.0 + FatigueParams().no_face_reset_sec + 0.1)

    assert engine._downgaze_active is False
    assert engine._downgaze_since is None
    assert engine._downgaze_lost_since is None
