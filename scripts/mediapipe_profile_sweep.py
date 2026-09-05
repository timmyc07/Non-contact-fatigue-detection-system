from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.mediapipe_tuning import (  # noqa: E402
    CONFIG_PATH,
    FaceLandmarkerTuning,
    MediaPipeTuning,
    RppgRoiTuning,
    QualityTuning,
    BlendshapeTuning,
    _deep_update,
)
from gui.platforms import create_face_landmarker_base_options  # noqa: E402
from rppg.rppg_worker import (  # noqa: E402
    RoiGeometryTracker,
    collect_rppg_roi_sample,
    ensure_face_model,
    _MODELS_DIR,
)


def _load_profile_tuning(profile: str, config_path: Path = CONFIG_PATH) -> MediaPipeTuning:
    base = asdict(MediaPipeTuning())
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            base = _deep_update(base, loaded)
    profiles = base.get("profiles", {})
    if profile != "default":
        prof = profiles.get(profile) if isinstance(profiles, dict) else None
        if not isinstance(prof, dict):
            raise ValueError(f"找不到 profile: {profile}")
        base = _deep_update(base, prof)
    base["active_profile"] = profile
    return MediaPipeTuning(
        active_profile=profile,
        face_landmarker=FaceLandmarkerTuning(**base.get("face_landmarker", {})),
        rppg_roi=RppgRoiTuning(**base.get("rppg_roi", {})),
        quality=QualityTuning(**base.get("quality", {})),
        blendshape=BlendshapeTuning(**base.get("blendshape", {})),
        profiles=profiles if isinstance(profiles, dict) else {},
    )


def _profiles_from_config(config_path: Path) -> list[str]:
    names = ["default"]
    if not config_path.exists():
        return names
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = loaded.get("profiles", {}) if isinstance(loaded, dict) else {}
    if isinstance(profiles, dict):
        names.extend(str(name) for name in profiles.keys())
    return names


def run_profile(video_path: Path, profile: str, max_frames: int, stride: int) -> dict[str, Any]:
    tuning = _load_profile_tuning(profile)
    model_path = ensure_face_model(_MODELS_DIR)
    options = _mp_vision.FaceLandmarkerOptions(
        base_options=create_face_landmarker_base_options(_mp_python, model_path),
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        min_face_detection_confidence=tuning.face_landmarker.min_face_detection_confidence,
        min_face_presence_confidence=tuning.face_landmarker.min_face_presence_confidence,
        min_tracking_confidence=tuning.face_landmarker.min_tracking_confidence,
        num_faces=max(1, int(tuning.face_landmarker.num_faces)),
        running_mode=_mp_vision.RunningMode.VIDEO,
    )
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"無法開啟影片: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    tracker = RoiGeometryTracker()
    frame_idx = 0
    used = 0
    face_frames = 0
    roi_counts: list[int] = []
    jitters: list[float] = []
    area_stabilities: list[float] = []
    smoothing_count = 0
    canonical_count = 0
    ts_ms_prev = 0
    with _mp_vision.FaceLandmarker.create_from_options(options) as landmarker:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            frame_idx += 1
            if stride > 1 and (frame_idx - 1) % stride != 0:
                continue
            used += 1
            if max_frames > 0 and used > max_frames:
                break
            ts_ms = max(ts_ms_prev + 1, int((frame_idx - 1) * 1000.0 / max(fps, 1e-6)))
            ts_ms_prev = ts_ms
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            result = landmarker.detect_for_video(mp_img, ts_ms)
            if not result.face_landmarks:
                tracker.reset()
                continue
            face_frames += 1
            lm = result.face_landmarks[0]
            transform_matrix = (
                result.facial_transformation_matrixes[0]
                if result.facial_transformation_matrixes else None
            )
            _, _, roi_valid_count = collect_rppg_roi_sample(
                bgr, lm, transform_matrix, tracker, tuning
            )
            roi_counts.append(roi_valid_count)
            jitters.append(tracker.landmark_jitter_norm)
            area_stabilities.append(tracker.roi_area_stability)
            smoothing_count += int(tracker.roi_smoothing_applied)
            canonical_count += int(tracker.canonical_roi_warp_used)
    cap.release()
    return {
        "profile": profile,
        "frames": used,
        "face_frames": face_frames,
        "face_rate": face_frames / max(used, 1),
        "avg_roi_valid": float(np.mean(roi_counts)) if roi_counts else 0.0,
        "avg_landmark_jitter": float(np.mean(jitters)) if jitters else 0.0,
        "avg_roi_area_stability": float(np.mean(area_stabilities)) if area_stabilities else 0.0,
        "smoothing_rate": smoothing_count / max(face_frames, 1),
        "canonical_rate": canonical_count / max(face_frames, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="以錄影檔回放比較 MediaPipe tuning profiles")
    parser.add_argument("video_path", type=Path, help="錄製影片路徑，例如 recordings/video_YYYYMMDD_HHMMSS.mp4")
    parser.add_argument("--profile", action="append", help="指定 profile，可重複；預設跑 default 與設定檔 profiles")
    parser.add_argument("--max-frames", type=int, default=0, help="最多處理幀數，0 代表不限制")
    parser.add_argument("--stride", type=int, default=1, help="每 N 幀處理一次")
    parser.add_argument("--csv", type=Path, help="輸出 CSV 路徑")
    args = parser.parse_args()

    profiles = args.profile or _profiles_from_config(CONFIG_PATH)
    rows = [run_profile(args.video_path, name, args.max_frames, max(1, args.stride)) for name in profiles]
    for row in rows:
        print(
            f"{row['profile']}: face_rate={row['face_rate']:.3f}, "
            f"avg_roi={row['avg_roi_valid']:.2f}, jitter={row['avg_landmark_jitter']:.4f}, "
            f"area_stability={row['avg_roi_area_stability']:.3f}, smoothing={row['smoothing_rate']:.3f}, "
            f"canonical={row['canonical_rate']:.3f}"
        )
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
