"""V2 Behavior Alertness Worker — QObject that runs in its own QThread.

Signal pipeline:
    CameraStreamWorker → BGR queue → FatigueWorker (own QThread)
    → MediaPipe Face Landmarker → FatigueEngine
    → FatigueMetrics → Overlay

Uses the same face_landmarker.task model as RppgWorker (shared download).
"""

from __future__ import annotations

import functools
import os
import queue
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage
from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageFont as _PILImageFont

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

_HAS_MP = True
_ANNOTATED_PREVIEW_MAX_FPS = 30.0

from .fatigue_engine import FatigueEngine, FatigueMetrics, FatigueParams
from .personal_profile import PersonalProfile
from .frame_queue import get_latest
from .mediapipe_tuning import load_mediapipe_tuning
from rppg.rppg_worker import ensure_face_model, _MODELS_DIR


# ── Drawing constants ────────────────────────────────────────────────────────

# Eye 6-point contour
_EYE_L_IDX = [362, 385, 387, 263, 373, 380]
_EYE_R_IDX = [33,  160, 158, 133, 153, 144]

# Iris (478-pt model): centre + 4 edge points
_IRIS_L_CTR   = 468
_IRIS_L_EDGES = [469, 470, 471, 472]
_IRIS_R_CTR   = 473
_IRIS_R_EDGES = [474, 475, 476, 477]

# Inner brow anchor points
_BROW_L_INNER = 55
_BROW_R_INNER = 285

# Nose anchor points (bridge + tip)
_NOSE_TIP = 1
_NOSE_BRIDGE = [6, 168]

# Outer brow ridge (for drawing the full brow arc)
_BROW_L = [336, 296, 334, 293, 300, 276, 283, 282, 295]
_BROW_R = [107,  66, 105,  63,  70,  46,  53,  52,  65]

# Outer lip contour
_MOUTH_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409,
                291, 375, 321, 405, 314, 17, 84, 181, 91, 146]

# Face oval
_FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172,  58, 132,  93, 234, 127, 162,  21,  54, 103,  67, 109,
]

# 疲勞狀態色對齊 gui/fatigue_scorer.py 的 _LEVELS BGR 漸層
# （清醒綠 → 輕度青綠 → 中度橙 → 高度紅橙 → 極度危險紅），僅顏色數值對齊，
# CALIBRATING/NO_FACE 非疲勞等級，維持原本的中性提示色。
_STATUS_COLOR = {
    "OK":            (0, 200,   0),   # 對齊「清醒」
    "CALIBRATING":   (180, 180,   0),
    "ALERT":         (0, 200, 160),   # 對齊「輕度疲勞」
    "LOW_VIGILANCE": (0, 200, 160),   # 對齊「輕度疲勞」
    "TIRED":         (0, 140, 255),   # 對齊「中度疲勞」
    "DROWSY":        (0,  60, 255),   # 對齊「高度疲勞」
    "CRITICAL":      (0,   0, 200),   # 對齊「極度危險」
    "MICROSLEEP":    (0,   0, 200),   # 對齊「極度危險」
    "NO_FACE":       (120, 120, 120),
}


# ── Overlay 樣式常數（僅影響畫法：字級/粗細/顏色/底板透明度，不影響任何數值或判斷邏輯）──

# 小型隨標記文字（鼻動速度、EAR、眼瞼開合、皺眉、嘴部比例等，貼在關鍵點旁）
_LM_LABEL_FONT_SCALE      = 0.40   # 原 0.34–0.38
_LM_SUBLABEL_FONT_SCALE   = 0.34   # 次要小字（如眼瞼 L/R 數值），原 0.30
_LM_LABEL_THICKNESS       = 1
_LM_LABEL_OUTLINE_THICK   = 3      # 黑色描邊粗細，提升在任意背景下的對比

# 哈欠提示（比一般隨標記文字更醒目）
_YAWN_LABEL_FONT_SCALE    = 0.46   # 原 0.40

# 底部 HUD 狀態列
_HUD_BAR_HEIGHT           = 30     # 原 22
_HUD_BAR_BG_COLOR         = (0, 0, 0)
_HUD_BAR_BG_ALPHA         = 0.65   # 原 0.60
_HUD_FONT_SCALE           = 0.58   # 原 0.38
_HUD_TEXT_THICKNESS       = 2
_HUD_OUTLINE_THICK        = 4

# 右上角頭部姿態角度讀數
_POSE_FONT_SCALE          = 0.50   # 原 0.38
_POSE_TEXT_THICKNESS      = 2
_POSE_OUTLINE_THICK       = 4
_POSE_BG_ALPHA            = 0.60   # 原 0.55
_POSE_BG_PAD              = 6

# 左上警示徽章
_BADGE_FONT_SCALE         = 0.50   # 原 0.40
_BADGE_TEXT_THICKNESS     = 2
_BADGE_OUTLINE_THICK      = 4
_BADGE_BG_ALPHA           = 0.65   # 原 0.60
_BADGE_BG_PAD_X           = 10
_BADGE_BG_PAD_Y           = 8
_BADGE_GAP                = 6      # 原 4（徽章間距，避免視覺黏在一起）

# 左側 PERCLOS 熱度條
_PERCLOS_BAR_WIDTH        = 14     # 原硬編碼 5px，太細難以辨識
_PERCLOS_BAR_BORDER_COLOR = (230, 230, 230)
_PERCLOS_BAR_LABEL_SCALE  = 0.40   # 原 0.32

# 微睡眠/嗜睡/危險全屏閃爍：略降 alpha，避免蓋掉 HUD/徽章等其他資訊
_FLASH_ALPHA_DROWSY       = 0.18   # 原 0.22
_FLASH_ALPHA_CRITICAL     = 0.30   # 原 0.35


def _lm_px(lm, w: int, h: int, idx: int) -> tuple[int, int]:
    return int(lm[idx].x * w), int(lm[idx].y * h)


def _lm_mean_px(lm, w: int, h: int, idxs: list[int]) -> tuple[int, int]:
    pts = np.array([_lm_px(lm, w, h, i) for i in idxs], dtype=np.float64)
    return int(np.mean(pts[:, 0])), int(np.mean(pts[:, 1]))


def _draw_head_pose_axes(
    out: np.ndarray,
    nose_px: tuple[int, int],
    pitch_deg: float,
    yaw_deg: float,
    roll_deg: float,
    scale: int,
) -> None:
    """Draw three coloured head-pose axes at the nose tip (BGR colours)."""
    p = np.radians(-pitch_deg)   # image Y flipped
    y = np.radians(yaw_deg)
    r = np.radians(roll_deg)

    cp, sp = float(np.cos(p)), float(np.sin(p))
    cy, sy = float(np.cos(y)), float(np.sin(y))
    cr, sr = float(np.cos(r)), float(np.sin(r))

    # ZYX rotation matrix (matches solvePnP conventions)
    R = np.array([
        [cy * cr + sy * sp * sr,  -cy * sr + sy * sp * cr,  sy * cp],
        [cp * sr,                   cp * cr,                 -sp    ],
        [-sy * cr + cy * sp * sr,   sy * sr + cy * sp * cr,  cy * cp],
    ], dtype=np.float64)

    nx, ny = nose_px
    # Red = X (right), Green = Y (up), Blue = Z (toward camera)
    for axis_vec, color in [
        (np.array([1, 0, 0]), (0,   50, 220)),
        (np.array([0, 1, 0]), (0,  200,   0)),
        (np.array([0, 0, 1]), (220,  80,   0)),
    ]:
        rv = R @ axis_vec
        tx = int(nx + scale * rv[0])
        ty = int(ny - scale * rv[1])   # negate Y for image coords (down = positive)
        cv2.arrowedLine(out, (nx, ny), (tx, ty), color, 2,
                        tipLength=0.25, line_type=cv2.LINE_AA)


# ── CJK-capable text rendering (Pillow) ──────────────────────────────────────
#
# cv2.putText's built-in Hershey fonts have no CJK glyphs — Chinese labels
# (鼻動/皺眉/口/哈欠/DROWSY 狀態文字等) render as "?" boxes. All *text* now
# renders through Pillow instead; every non-text cv2 drawing primitive
# (lines/circles/rectangles/arrows/PERCLOS bar) is untouched.
#
# Perf: `draw_fatigue_annotations` is called once per frame on the hot path
# with ~15 text draws. Doing a numpy<->PIL round trip per text call would be
# far too slow, so callers *queue* text draws via `_put_outlined_text` (now a
# queue-append, not an immediate draw) and the frame is flushed to PIL and
# back only at a small, fixed number of checkpoints per frame — see the two
# `_flush_text_queue` call sites in `draw_fatigue_annotations`.

_CV2_SCALE_TO_PX = 34   # heuristic px-per-cv2-font-scale-unit, tuned to roughly
                        # match the visual size of the previous Hershey text.

# Windows (Traditional-Chinese-friendly) → common Linux CJK font paths, in
# priority order. First existing path wins; if none exist we fall back to
# PIL's built-in default font (readable for ASCII, CJK glyphs will be boxes —
# same degraded behaviour as before, never a crash).
_CJK_FONT_CANDIDATES: tuple[str, ...] = (
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/msjhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-TC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
)


@functools.lru_cache(maxsize=1)
def _cjk_font_path() -> Optional[str]:
    """Resolve the first existing CJK font path on this machine (cached once)."""
    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


@functools.lru_cache(maxsize=None)
def _resolve_cjk_font(size: int):
    """Return a cached Pillow font object for `size` px (loaded at most once per size)."""
    path = _cjk_font_path()
    if path:
        try:
            return _PILImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return _PILImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow without the `size` kwarg on load_default — still usable,
        # just not scalable; never crashes the overlay.
        return _PILImageFont.load_default()


def _put_outlined_text(
    text_queue: list,
    text: str,
    org: tuple[int, int],
    font: int,
    scale: float,
    color: tuple,
    thickness: int = 1,
    outline_thickness: int = 3,
    outline_color: tuple = (0, 0, 0),
) -> None:
    """Queue a text draw for later batched PIL rendering.

    Signature-compatible with the old immediate-draw helper (`font` — a cv2
    font id — and `thickness` are accepted but unused; kept so call sites
    below did not need to change). Appends to `text_queue`, drawn by
    `_flush_text_queue`. Does not touch text content — only how/when it renders.
    """
    text_queue.append((text, org, scale, color, outline_thickness, outline_color))


def _flush_text_queue(out: np.ndarray, text_queue: list) -> np.ndarray:
    """Render all queued text onto `out` via a single numpy<->PIL round trip.

    BGR (cv2) <-> RGB (PIL) converted once regardless of queue length, so the
    per-frame cost is a small, fixed number of these (see call sites) rather
    than one per text label.
    """
    if not text_queue:
        return out
    rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    pil_img = _PILImage.fromarray(rgb)
    draw = _PILImageDraw.Draw(pil_img)
    for text, org, scale, color_bgr, outline_thickness, outline_color_bgr in text_queue:
        px = max(8, round(scale * _CV2_SCALE_TO_PX))
        pil_font = _resolve_cjk_font(px)
        color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
        outline_rgb = (int(outline_color_bgr[2]), int(outline_color_bgr[1]), int(outline_color_bgr[0]))
        stroke_w = max(1, outline_thickness // 2)
        try:
            draw.text(org, text, font=pil_font, fill=color_rgb,
                      stroke_width=stroke_w, stroke_fill=outline_rgb, anchor="ls")
        except (ValueError, TypeError):
            # Extreme fallback (e.g. bitmap default font without anchor/stroke
            # support): draw without those kwargs rather than crash the overlay.
            draw.text(org, text, font=pil_font, fill=color_rgb)
    text_queue.clear()
    out_rgb = np.array(pil_img)
    return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)


def _pil_text_size(text: str, scale: float) -> tuple[int, int]:
    """Measure text pixel size the same way it will be rendered (PIL).

    Used only to size cv2-drawn background boxes behind text (pose readout /
    alert badges) — `cv2.getTextSize` uses Hershey font metrics and cannot
    measure CJK glyph widths, so a box sized from it no longer matches the
    PIL-rendered text once Chinese labels are involved.
    """
    px = max(8, round(scale * _CV2_SCALE_TO_PX))
    pil_font = _resolve_cjk_font(px)
    probe = _PILImage.new("RGB", (1, 1))
    draw = _PILImageDraw.Draw(probe)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=pil_font, anchor="la")
        return max(1, right - left), max(1, bottom - top)
    except Exception:
        # Never let a measurement fallback crash the overlay.
        return max(1, int(len(text) * px * 0.6)), max(1, px)


def draw_fatigue_annotations(
    frame: np.ndarray,
    lm: list,
    metrics: FatigueMetrics,
) -> np.ndarray:
    """Draw rich fatigue / behaviour-alertness annotations on the frame."""
    if cv2 is None:
        return frame

    out = frame.copy()
    h, w = out.shape[:2]
    font  = cv2.FONT_HERSHEY_SIMPLEX
    s_col = _STATUS_COLOR.get(metrics.status, (180, 180, 180))
    # 待畫文字佇列：批次走 PIL（支援中文），只在固定幾個檢查點做 numpy<->PIL
    # 往返，而非每則文字各做一次（見下方兩處 _flush_text_queue）。
    text_q: list = []

    # ── 1. Face oval ─────────────────────────────────────────────────────────
    oval_pts = np.array([_lm_px(lm, w, h, i) for i in _FACE_OVAL], np.int32)
    cv2.polylines(out, [oval_pts], isClosed=True,
                  color=(60, 60, 60), thickness=1, lineType=cv2.LINE_AA)

    # ── 1b. Nose anchor (tip + bridge) ───────────────────────────────────────
    nose_tip = _lm_px(lm, w, h, _NOSE_TIP)
    nose_bridge = _lm_mean_px(lm, w, h, _NOSE_BRIDGE)
    nose_col = (0, 200, 255) if metrics.nose_speed < 120 else (0, 120, 255)
    cv2.line(out, nose_bridge, nose_tip, nose_col, 1, lineType=cv2.LINE_AA)
    cv2.circle(out, nose_tip, 2, nose_col, -1, lineType=cv2.LINE_AA)
    _put_outlined_text(
        text_q,
        f"鼻動:{metrics.nose_speed:.0f}",
        (nose_tip[0] + 4, nose_tip[1] - 4),
        font, _LM_LABEL_FONT_SCALE, nose_col, _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK,
    )

    # ── 2. Brow arcs + inner-brow furrowing indicator ─────────────────────────
    for brow_idxs, inner_idx in [(_BROW_L, _BROW_L_INNER), (_BROW_R, _BROW_R_INNER)]:
        pts = np.array([_lm_px(lm, w, h, i) for i in brow_idxs], np.int32)
        brow_col = (0, 80, 220) if metrics.is_frowning else (80, 80, 160)
        cv2.polylines(out, [pts], isClosed=False,
                      color=brow_col, thickness=1, lineType=cv2.LINE_AA)

    # Inner-brow distance line (highlights furrowing)
    lb = _lm_px(lm, w, h, _BROW_L_INNER)
    rb = _lm_px(lm, w, h, _BROW_R_INNER)
    brow_line_col = (0, 60, 255) if metrics.is_frowning else (60, 60, 120)
    cv2.line(out, lb, rb, brow_line_col, 1, lineType=cv2.LINE_AA)
    if metrics.is_frowning:
        mid = ((lb[0] + rb[0]) // 2, (lb[1] + rb[1]) // 2 - 6)
        _put_outlined_text(text_q, "皺眉", mid, font, _LM_LABEL_FONT_SCALE, (0, 60, 255),
                            _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)

    # ── 3. Eye contours (colour-coded) ────────────────────────────────────────
    # Normal=green, squinting=yellow, PERCLOS alarm=red
    if metrics.is_squinting:
        eye_col = (0, 200, 255)    # yellow-ish
    elif metrics.perclos > 0.20:
        eye_col = (0, 80, 220)     # orange-red alarm
    else:
        eye_col = (40, 200, 80)    # green normal

    for eye_idxs in (_EYE_L_IDX, _EYE_R_IDX):
        pts = np.array([_lm_px(lm, w, h, i) for i in eye_idxs], np.int32)
        cv2.polylines(out, [pts], isClosed=True,
                      color=eye_col, thickness=1, lineType=cv2.LINE_AA)

    # EAR label beside each eye
    l_outer = _lm_px(lm, w, h, 263)
    r_outer = _lm_px(lm, w, h, 33)
    _put_outlined_text(text_q, f"{metrics.ear_smooth:.2f}",
                        (l_outer[0] + 4, l_outer[1] - 4),
                        font, _LM_LABEL_FONT_SCALE, eye_col,
                        _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)
    _put_outlined_text(text_q, f"{metrics.ear_smooth:.2f}",
                        (r_outer[0] - 30, r_outer[1] - 4),
                        font, _LM_LABEL_FONT_SCALE, eye_col,
                        _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)
    _put_outlined_text(text_q, f"L:{metrics.lid_open_left:.2f}", (l_outer[0] + 4, l_outer[1] + 10),
                        font, _LM_SUBLABEL_FONT_SCALE, (120, 220, 120),
                        _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)
    _put_outlined_text(text_q, f"R:{metrics.lid_open_right:.2f}", (r_outer[0] - 30, r_outer[1] + 10),
                        font, _LM_SUBLABEL_FONT_SCALE, (120, 220, 120),
                        _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)

    # ── 4. Iris circles + crosshair ───────────────────────────────────────────
    if metrics.has_iris:
        for ctr_idx, edge_idxs in [(_IRIS_L_CTR, _IRIS_L_EDGES),
                                    (_IRIS_R_CTR, _IRIS_R_EDGES)]:
            cx, cy = _lm_px(lm, w, h, ctr_idx)
            # Radius: mean pixel distance from centre to 4 edge points
            edge_pts = [_lm_px(lm, w, h, ei) for ei in edge_idxs]
            radii = [int(np.hypot(ex - cx, ey - cy)) for ex, ey in edge_pts]
            radius = max(1, int(np.mean(radii)))

            # Outer iris ring
            cv2.circle(out, (cx, cy), radius,
                       (0, 200, 200), 1, lineType=cv2.LINE_AA)
            # Inner pupil approximation (iris centre dot)
            pupil_r = max(1, radius // 3)
            cv2.circle(out, (cx, cy), pupil_r,
                       (0, 255, 220), -1, lineType=cv2.LINE_AA)
            # Crosshair
            arm = radius + 4
            cv2.line(out, (cx - arm, cy), (cx + arm, cy),
                     (0, 180, 160), 1, lineType=cv2.LINE_AA)
            cv2.line(out, (cx, cy - arm), (cx, cy + arm),
                     (0, 180, 160), 1, lineType=cv2.LINE_AA)

        # ── 5. Gaze arrow from nose tip ───────────────────────────────────────
        nx, ny = _lm_px(lm, w, h, 1)
        arrow_len = int(w * 0.08)
        ax = int(nx + metrics.gaze_x * arrow_len)
        ay = int(ny + metrics.gaze_y * arrow_len)
        saccade_col = (0, 50, 255) if metrics.is_saccade else (0, 220, 255)
        cv2.arrowedLine(out, (nx, ny), (ax, ay),
                        saccade_col, 2, tipLength=0.3, line_type=cv2.LINE_AA)

    # ── 6. Head pose 3-axis indicator ─────────────────────────────────────────
    nose_px = _lm_px(lm, w, h, 1)
    axis_scale = int(min(w, h) * 0.13)
    _draw_head_pose_axes(out, nose_px,
                         metrics.head_pitch, metrics.head_yaw, metrics.head_roll,
                         axis_scale)

    # ── 7. Mouth / MAR contour (visible when yawning or MAR > 0.3) ────────────
    if metrics.mar > 0.30 or metrics.mouth_open_ratio > 0.18:
        mouth_pts = np.array([_lm_px(lm, w, h, i) for i in _MOUTH_OUTER], np.int32)
        mouth_col = (0, 50, 255) if metrics.yawn_count > 0 or metrics.mar > 0.55 else (80, 80, 200)
        cv2.polylines(out, [mouth_pts], isClosed=True,
                      color=mouth_col, thickness=1, lineType=cv2.LINE_AA)
        _put_outlined_text(text_q, f"口:{metrics.mouth_open_ratio:.2f}",
                            (mouth_pts[0][0] - 8, mouth_pts[0][1] - 8),
                            font, _LM_LABEL_FONT_SCALE, mouth_col,
                            _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)
        if metrics.mar > 0.55:
            mc = _lm_px(lm, w, h, 13)
            _put_outlined_text(text_q, "哈欠", (mc[0] - 12, mc[1] - 6),
                                font, _YAWN_LABEL_FONT_SCALE, (0, 50, 255),
                                _LM_LABEL_THICKNESS + 1, _LM_LABEL_OUTLINE_THICK)

    # 檢查點 1：步驟 1–7 的文字先落版（維持「文字被閃爍疊層蓋暗」的原有視覺
    # 層次——閃爍疊層在下面步驟 8 用 cv2 直接畫在 `out` 上，時序不變）。
    out = _flush_text_queue(out, text_q)

    # ── 8. Microsleep / drowsy flash overlay ──────────────────────────────────
    if metrics.status in ("MICROSLEEP", "DROWSY", "CRITICAL"):
        overlay = out.copy()
        alpha   = _FLASH_ALPHA_DROWSY if metrics.status == "DROWSY" else _FLASH_ALPHA_CRITICAL
        col     = (0, 30, 180) if metrics.status in ("MICROSLEEP", "CRITICAL") else (0, 0, 160)
        cv2.rectangle(overlay, (0, 0), (w, h), col, -1)
        cv2.addWeighted(overlay, alpha, out, 1 - alpha, 0, out)

    # ── 9. Bottom HUD ─────────────────────────────────────────────────────────
    # Status + key metrics on a semi-transparent dark bar
    hud_h   = _HUD_BAR_HEIGHT
    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - hud_h), (w, h), _HUD_BAR_BG_COLOR, -1)
    cv2.addWeighted(overlay, _HUD_BAR_BG_ALPHA, out, 1 - _HUD_BAR_BG_ALPHA, 0, out)

    hud_txt = (
        f"{metrics.status}"
        f"  EAR:{metrics.ear_smooth:.2f}"
        f"  PERCLOS:{metrics.perclos*100:.0f}%"
        f"  眨眼:{metrics.blink_rate_pm:.0f}/min"
    )
    _put_outlined_text(text_q, hud_txt, (6, h - 8), font, _HUD_FONT_SCALE, s_col,
                        _HUD_TEXT_THICKNESS, _HUD_OUTLINE_THICK)

    # ── 10. Top-right: head pose angles ───────────────────────────────────────
    pose_txt = (
        f"P:{metrics.head_pitch:+.0f}"
        f" Y:{metrics.head_yaw:+.0f}"
        f" R:{metrics.head_roll:+.0f}"
    )
    # 用 PIL 量測（而非 cv2.getTextSize，其 Hershey 字型量不出中文寬度），
    # 讓底板尺寸與實際渲染的文字一致。
    pw, ph = _pil_text_size(pose_txt, _POSE_FONT_SCALE)
    ox = w - pw - _POSE_BG_PAD - 2
    overlay2 = out.copy()
    cv2.rectangle(overlay2, (ox - _POSE_BG_PAD, 2), (w - 2, ph + _POSE_BG_PAD + 6), (0, 0, 0), -1)
    cv2.addWeighted(overlay2, _POSE_BG_ALPHA, out, 1 - _POSE_BG_ALPHA, 0, out)
    # Pitch colour warning
    p_col = (0, 60, 220) if metrics.head_pitch < -12.0 else (150, 200, 100)
    _put_outlined_text(text_q, pose_txt, (ox, ph + _POSE_BG_PAD), font, _POSE_FONT_SCALE, p_col,
                        _POSE_TEXT_THICKNESS, _POSE_OUTLINE_THICK)

    # ── 11. Top-left: alert badges ────────────────────────────────────────────
    alerts: list[tuple[str, tuple]] = []
    if metrics.microsleep_alert:
        alerts.append(("⚠ 微睡眠", (0, 0, 220)))
    if metrics.gaze_mental_fatigue:
        alerts.append(("空洞凝視", (0, 140, 255)))
    if metrics.is_squinting:
        alerts.append((f"瞇眼 {metrics.squint_duration:.0f}s", (0, 190, 255)))
    if metrics.is_frowning:
        alerts.append(("皺眉", (0, 100, 255)))
    if metrics.lid_balance > 0.35:
        alerts.append((f"眼瞼差 {metrics.lid_balance:.2f}", (0, 180, 255)))
    if metrics.mouth_open_ratio > 0.30:
        alerts.append((f"嘴部 {metrics.mouth_open_ratio:.2f}", (0, 140, 255)))
    if metrics.nose_speed > 120.0:
        alerts.append((f"鼻動 {metrics.nose_speed:.0f}", (0, 200, 255)))

    y_off = 4
    for badge_txt, badge_col in alerts:
        # 同上：改用 PIL 量測，中文徽章底板才會貼合實際文字寬高。
        bw, bh = _pil_text_size(badge_txt, _BADGE_FONT_SCALE)
        overlay3 = out.copy()
        cv2.rectangle(overlay3, (0, y_off),
                      (bw + _BADGE_BG_PAD_X * 2, y_off + bh + _BADGE_BG_PAD_Y * 2), (0, 0, 0), -1)
        cv2.addWeighted(overlay3, _BADGE_BG_ALPHA, out, 1 - _BADGE_BG_ALPHA, 0, out)
        _put_outlined_text(text_q, badge_txt, (_BADGE_BG_PAD_X - 5, y_off + bh + _BADGE_BG_PAD_Y),
                            font, _BADGE_FONT_SCALE, badge_col,
                            _BADGE_TEXT_THICKNESS, _BADGE_OUTLINE_THICK)
        y_off += bh + _BADGE_BG_PAD_Y * 2 + _BADGE_GAP

    # ── 12. PERCLOS heat bar (left edge) ──────────────────────────────────────
    if metrics.calibrated and metrics.perclos > 0.0:
        bar_w     = _PERCLOS_BAR_WIDTH
        bar_max_h = h - 40
        bar_h     = int(bar_max_h * min(metrics.perclos / 0.40, 1.0))
        bar_y0    = h - 20 - bar_h
        intensity = int(min(metrics.perclos / 0.40, 1.0) * 255)
        bar_col   = (0, max(0, 180 - intensity), min(255, intensity * 2))
        # 底板：整條軌道先鋪深色背景，再疊填充色，讓短短的低值也清楚可見
        cv2.rectangle(out, (0, h - 20 - bar_max_h), (bar_w, h - 20), (30, 30, 30), -1)
        cv2.rectangle(out, (0, bar_y0), (bar_w, h - 20), bar_col, -1)
        cv2.rectangle(out, (0, h - 20 - bar_max_h), (bar_w, h - 20),
                      _PERCLOS_BAR_BORDER_COLOR, 1, lineType=cv2.LINE_AA)
        _put_outlined_text(text_q, f"{metrics.perclos*100:.0f}%",
                            (bar_w + 2, h - 20), font, _PERCLOS_BAR_LABEL_SCALE, bar_col,
                            _LM_LABEL_THICKNESS, _LM_LABEL_OUTLINE_THICK)

    # 檢查點 2：步驟 9–12 的剩餘文字一次落版。
    out = _flush_text_queue(out, text_q)

    return out


# ── FatigueWorker ────────────────────────────────────────────────────────────

class FatigueWorker(QObject):
    """Behaviour alertness worker: runs MediaPipe + FatigueEngine in a QThread.

    Parameters
    ----------
    frame_queue : queue.Queue[tuple[float, np.ndarray]]
        Thread-safe queue fed by CameraStreamWorker.  Each item is
        (perf_counter_timestamp, bgr_frame).
    target_fps : float
        Expected frame rate; passed to FatigueEngine for calibration timing.
    params : FatigueParams, optional
        Engine configuration.  Default parameters are used if None.
    """

    metrics_ready:   Signal = Signal(object)         # FatigueMetrics
    frame_annotated: Signal = Signal(QImage)         # annotated preview frame
    face_detected:   Signal = Signal(bool)
    status_changed:  Signal = Signal(str)
    failed:          Signal = Signal(str)
    finished:        Signal = Signal()

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        target_fps: float = 30.0,
        params: Optional[FatigueParams] = None,
        personal_profile: Optional[PersonalProfile] = None,
    ) -> None:
        super().__init__()
        self._queue      = frame_queue
        self._target_fps = target_fps
        self._params     = params or FatigueParams()
        self._stop       = False
        # 個人清醒基線：建構期注入 + 執行中熱換（仿 request_stop 旗標輪詢）。
        self._personal_profile = personal_profile
        self._fatigue_engine: Optional[FatigueEngine] = None
        self._pending_profile: Optional[PersonalProfile] = None
        self._has_pending_profile = False

    def request_stop(self) -> None:
        self._stop = True

    def set_personal_profile(self, profile: Optional[PersonalProfile]) -> None:
        """執行緒安全熱換個人基線（主執行緒設旗標，run 迴圈輪詢套用）。"""
        self._pending_profile = profile
        self._has_pending_profile = True

    @Slot()
    def run(self) -> None:
        if not _HAS_MP:
            self.failed.emit("MediaPipe 未安裝。\n請執行：pip install mediapipe")
            self.finished.emit()
            return
        if cv2 is None:
            self.failed.emit("OpenCV 未安裝。")
            self.finished.emit()
            return

        # Download / verify model (shared with rPPG worker)
        try:
            model_path = ensure_face_model(
                _MODELS_DIR,
                status_cb=lambda s: self.status_changed.emit(s),
            )
        except Exception as exc:
            self.failed.emit(f"MediaPipe 模型下載失敗：{exc}")
            self.finished.emit()
            return

        base_opts  = _mp_python.BaseOptions(model_asset_path=str(model_path))
        tuning = load_mediapipe_tuning()
        lm_options = _mp_vision.FaceLandmarkerOptions(
            base_options=base_opts,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=tuning.face_landmarker.min_face_detection_confidence,
            min_face_presence_confidence=tuning.face_landmarker.min_face_presence_confidence,
            min_tracking_confidence=tuning.face_landmarker.min_tracking_confidence,
            num_faces=max(1, int(tuning.face_landmarker.num_faces)),
            running_mode=_mp_vision.RunningMode.VIDEO,
        )

        engine    = FatigueEngine(params=self._params,
                                  personal_profile=self._personal_profile)
        self._fatigue_engine = engine
        last_face = False
        t_origin: Optional[float] = None
        ts_ms_prev = 0
        last_preview_emit = 0.0
        preview_emit_interval = 1.0 / _ANNOTATED_PREVIEW_MAX_FPS

        self.status_changed.emit("行為警覺引擎就緒，等待幀資料…")

        with _mp_vision.FaceLandmarker.create_from_options(lm_options) as landmarker:
            while not self._stop:
                if self._has_pending_profile:
                    engine.set_personal_profile(self._pending_profile)
                    self._has_pending_profile = False
                try:
                    ts, bgr = get_latest(self._queue, timeout=0.1)
                except queue.Empty:
                    continue

                if t_origin is None:
                    t_origin = ts

                # Monotonically increasing ms timestamp (MediaPipe VIDEO mode requirement)
                ts_ms      = max(ts_ms_prev + 1, int((ts - t_origin) * 1000))
                ts_ms_prev = ts_ms

                rgb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(rgb),
                )

                try:
                    result = landmarker.detect_for_video(mp_img, ts_ms)
                except Exception:
                    continue

                has_face = bool(result.face_landmarks)
                if has_face != last_face:
                    self.face_detected.emit(has_face)
                    last_face = has_face

                blendshapes = result.face_blendshapes[0] if result.face_blendshapes else None

                annotated = bgr.copy()

                if has_face:
                    lm      = result.face_landmarks[0]
                    h_px, w_px = bgr.shape[:2]
                    metrics = engine.step(lm, w_px, h_px, ts, blendshapes=blendshapes)
                    metrics.face_detected = True

                    annotated = draw_fatigue_annotations(annotated, lm, metrics)

                    if not metrics.calibrated:
                        pct = int(metrics.calib_progress * 100)
                        self.status_changed.emit(f"校準中… {pct}%")
                    else:
                        self.status_changed.emit(
                            f"{metrics.status}  "
                            f"EAR {metrics.ear_smooth:.2f}  "
                            f"PERCLOS {metrics.perclos*100:.0f}%  "
                            f"眨眼 {metrics.blink_count}"
                        )
                else:
                    metrics = engine.on_no_face(ts)
                    self.status_changed.emit("未偵測到臉部…")

                self.metrics_ready.emit(metrics)

                if ts - last_preview_emit >= preview_emit_interval:
                    last_preview_emit = ts
                    rgb_ann  = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    rgb_ann  = np.ascontiguousarray(rgb_ann)
                    fh, fw   = rgb_ann.shape[:2]
                    qimg     = QImage(
                        rgb_ann.data, fw, fh,
                        rgb_ann.strides[0],
                        QImage.Format.Format_RGB888,
                    )
                    self.frame_annotated.emit(qimg.copy())

        self.finished.emit()
