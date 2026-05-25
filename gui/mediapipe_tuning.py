"""MediaPipe tuning configuration and persisted calibration helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "mediapipe_tuning.json"
CALIBRATION_PATH = ROOT / "config" / "mediapipe_calibration.json"


@dataclass
class FaceLandmarkerTuning:
    min_face_detection_confidence: float = 0.55
    min_face_presence_confidence: float = 0.55
    min_tracking_confidence: float = 0.60
    num_faces: int = 1


@dataclass
class RppgRoiTuning:
    base_weights: dict[str, float] = field(default_factory=lambda: {
        "forehead": 0.34,
        "L_cheek": 0.25,
        "R_cheek": 0.25,
        "glabella": 0.16,
    })
    roll_full_penalty_deg: float = 42.0
    yaw_full_penalty_deg: float = 42.0
    pitch_free_deg: float = 8.0
    pitch_full_penalty_deg: float = 34.0
    obstruction_dark_luma: float = 35.0
    obstruction_bright_luma: float = 232.0
    obstruction_low_chroma: float = 2.5
    obstruction_high_chroma: float = 48.0
    min_roi_weight: float = 0.04
    roi_smoothing_enabled: bool = True
    roi_smoothing_alpha: float = 0.35
    roi_smoothing_max_shift_ratio: float = 0.12
    landmark_jitter_full_norm: float = 0.020
    roi_area_jitter_full_ratio: float = 0.25
    canonical_roi_warp_enabled: bool = False
    canonical_roi_warp_strength: float = 0.35


@dataclass
class QualityTuning:
    pose_weight: float = 0.30
    motion_weight: float = 0.25
    coverage_weight: float = 0.25
    roi_weight: float = 0.20
    signal_weight: float = 0.45
    face_weight: float = 0.55


@dataclass
class BlendshapeTuning:
    calib_sec: float = 4.0
    min_samples: int = 24
    ema_alpha: float = 0.22
    blink_gate: float = 0.20
    squint_gate: float = 0.18
    brow_gate: float = 0.18
    jaw_gate: float = 0.20


@dataclass
class MediaPipeTuning:
    active_profile: str = "default"
    face_landmarker: FaceLandmarkerTuning = field(default_factory=FaceLandmarkerTuning)
    rppg_roi: RppgRoiTuning = field(default_factory=RppgRoiTuning)
    quality: QualityTuning = field(default_factory=QualityTuning)
    blendshape: BlendshapeTuning = field(default_factory=BlendshapeTuning)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


def _deep_update(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            dst[key] = _deep_update(dict(dst[key]), value)
        else:
            dst[key] = value
    return dst


def load_mediapipe_tuning(path: Path | None = None) -> MediaPipeTuning:
    path = path or CONFIG_PATH
    default_data = asdict(MediaPipeTuning())
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                default_data = _deep_update(default_data, loaded)
        except Exception as exc:
            log.warning("MediaPipe tuning 設定讀取失敗，使用預設值：%s", exc)
    else:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(default_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("MediaPipe tuning 預設設定寫入失敗：%s", exc)
    active_profile = str(default_data.get("active_profile", "default") or "default")
    profiles = default_data.get("profiles", {})
    if active_profile != "default" and isinstance(profiles, dict):
        profile_data = profiles.get(active_profile)
        if isinstance(profile_data, dict):
            merged = dict(default_data)
            merged["profiles"] = profiles
            default_data = _deep_update(merged, profile_data)
        else:
            log.warning("MediaPipe tuning profile 不存在：%s，使用 default", active_profile)
            default_data["active_profile"] = "default"
    return MediaPipeTuning(
        active_profile=str(default_data.get("active_profile", "default") or "default"),
        face_landmarker=FaceLandmarkerTuning(**default_data.get("face_landmarker", {})),
        rppg_roi=RppgRoiTuning(**default_data.get("rppg_roi", {})),
        quality=QualityTuning(**default_data.get("quality", {})),
        blendshape=BlendshapeTuning(**default_data.get("blendshape", {})),
        profiles=default_data.get("profiles", {}) if isinstance(default_data.get("profiles", {}), dict) else {},
    )


class CalibrationStore:
    """Small JSON store for per-user/session MediaPipe baselines."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CALIBRATION_PATH
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = raw if isinstance(raw, dict) else {}
        except Exception as exc:
            log.warning("MediaPipe calibration 讀取失敗：%s", exc)
            self.data = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("MediaPipe calibration 寫入失敗：%s", exc)

    def get_section(self, name: str) -> dict[str, Any]:
        section = self.data.get(name)
        return dict(section) if isinstance(section, dict) else {}

    def set_section(self, name: str, value: dict[str, Any]) -> None:
        self.data[name] = dict(value)
        self.save()
