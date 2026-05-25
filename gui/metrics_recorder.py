"""SQLite metrics recorder for V2 fatigue + rPPG + fused scores."""

from __future__ import annotations

import sqlite3
import time
from typing import Any


class MetricsRecorder:
    """SQLite-based recorder for V2 metrics."""

    COLUMNS = [
        "timestamp",
        "fps",
        "frame_width",
        "frame_height",
        "codec",
        "camera_label",
        "rppg_face_detected",
        "bpm",
        "rmssd",
        "sdnn",
        "lf_hf",
        "sqi",
        "rppg_quality_score",
        "rppg_pose_roll_deg",
        "rppg_pose_yaw_deg",
        "rppg_pose_pitch_deg",
        "rppg_roi_valid_count",
        "rppg_roi_weight_forehead",
        "rppg_roi_weight_l_cheek",
        "rppg_roi_weight_r_cheek",
        "rppg_roi_weight_glabella",
        "rppg_landmark_jitter_norm",
        "rppg_roi_area_stability",
        "rppg_roi_area_jitter_ratio",
        "rppg_roi_smoothing_applied",
        "rppg_canonical_roi_warp_used",
        "stress_prob",
        "stress_status",
        "hrv_confidence",
        "ibi_artifact_ratio",
        "peak_freq_hz",
        "frame_brightness",
        "warmup_progress",
        "fatigue_face_detected",
        "calibrated",
        "status",
        "fatigue_level",
        "early_warning",
        "ear",
        "ear_smooth",
        "blink_count",
        "perclos",
        "blink_rate_pm",
        "is_squinting",
        "squint_duration",
        "is_frowning",
        "brow_dist_norm",
        "iris_ratio",
        "iris_ratio_trend",
        "gaze_x",
        "gaze_y",
        "gaze_stability_index",
        "gaze_mental_fatigue",
        "saccadic_velocity",
        "is_saccade",
        "fixation_duration",
        "saccade_freq_pm",
        "head_pitch",
        "head_yaw",
        "head_roll",
        "fatigue_quality_score",
        "fatigue_blend_calib_progress",
        "microsleep_alert",
        "microsleep_count",
        "mar",
        "yawn_detected",
        "yawn_count",
        "has_iris",
        "calib_progress",
        "fused_score",
        "fused_level",
        "fused_level_en",
        "fused_rppg_sub",
        "fused_behavior_sub",
        "fused_rppg_weight_eff",
        "fused_behavior_weight_eff",
        "fused_trend",
        "fused_trend_symbol",
        "fused_rppg_available",
        "fused_behavior_available",
        "fused_rppg_stress_score",
        "fused_rppg_bpm_score",
        "fused_beh_perclos_score",
        "fused_beh_squint_score",
        "fused_beh_microsleep_score",
        "fused_beh_gaze_score",
        "fused_beh_frown_score",
        "fused_beh_yawn_score",
    ]

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        fps REAL,
        frame_width INTEGER,
        frame_height INTEGER,
        codec TEXT,
        camera_label TEXT,
        rppg_face_detected BOOLEAN,
        bpm REAL,
        rmssd REAL,
        sdnn REAL,
        lf_hf REAL,
        sqi REAL,
        rppg_quality_score REAL,
        rppg_pose_roll_deg REAL,
        rppg_pose_yaw_deg REAL,
        rppg_pose_pitch_deg REAL,
        rppg_roi_valid_count INTEGER,
        rppg_roi_weight_forehead REAL,
        rppg_roi_weight_l_cheek REAL,
        rppg_roi_weight_r_cheek REAL,
        rppg_roi_weight_glabella REAL,
        rppg_landmark_jitter_norm REAL,
        rppg_roi_area_stability REAL,
        rppg_roi_area_jitter_ratio REAL,
        rppg_roi_smoothing_applied BOOLEAN,
        rppg_canonical_roi_warp_used BOOLEAN,
        stress_prob REAL,
        stress_status TEXT,
        hrv_confidence TEXT,
        ibi_artifact_ratio REAL,
        peak_freq_hz REAL,
        frame_brightness REAL,
        warmup_progress REAL,
        fatigue_face_detected BOOLEAN,
        calibrated BOOLEAN,
        status TEXT,
        fatigue_level REAL,
        early_warning BOOLEAN,
        ear REAL,
        ear_smooth REAL,
        blink_count INTEGER,
        perclos REAL,
        blink_rate_pm REAL,
        is_squinting BOOLEAN,
        squint_duration REAL,
        is_frowning BOOLEAN,
        brow_dist_norm REAL,
        iris_ratio REAL,
        iris_ratio_trend REAL,
        gaze_x REAL,
        gaze_y REAL,
        gaze_stability_index REAL,
        gaze_mental_fatigue BOOLEAN,
        saccadic_velocity REAL,
        is_saccade BOOLEAN,
        fixation_duration REAL,
        saccade_freq_pm REAL,
        head_pitch REAL,
        head_yaw REAL,
        head_roll REAL,
        fatigue_quality_score REAL,
        fatigue_blend_calib_progress REAL,
        microsleep_alert BOOLEAN,
        microsleep_count INTEGER,
        mar REAL,
        yawn_detected BOOLEAN,
        yawn_count INTEGER,
        has_iris BOOLEAN,
        calib_progress REAL,
        fused_score REAL,
        fused_level TEXT,
        fused_level_en TEXT,
        fused_rppg_sub REAL,
        fused_behavior_sub REAL,
        fused_rppg_weight_eff REAL,
        fused_behavior_weight_eff REAL,
        fused_trend REAL,
        fused_trend_symbol TEXT,
        fused_rppg_available BOOLEAN,
        fused_behavior_available BOOLEAN,
        fused_rppg_stress_score REAL,
        fused_rppg_bpm_score REAL,
        fused_beh_perclos_score REAL,
        fused_beh_squint_score REAL,
        fused_beh_microsleep_score REAL,
        fused_beh_gaze_score REAL,
        fused_beh_frown_score REAL,
        fused_beh_yawn_score REAL
    )
    """

    CREATE_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp)
    """

    BATCH_SIZE = 100
    FLUSH_INTERVAL = 1.0

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        self.conn: sqlite3.Connection | None = None
        self._buffer: list[tuple] = []
        self._last_flush_time = 0.0
        self._start_time: float | None = None
        self._record_count = 0

        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self.conn.execute("PRAGMA temp_store = MEMORY")
            self.conn.execute("PRAGMA cache_size = -8000")
            self.conn.execute(self.CREATE_TABLE_SQL)
            self.conn.execute(self.CREATE_INDEX_SQL)
            self._migrate_schema()
            self.conn.commit()
            self._start_time = time.time()
            self._last_flush_time = time.time()
        except Exception as exc:
            self._cleanup()
            raise RuntimeError(f"Failed to initialize recorder at {db_path}: {exc}")

        placeholders = ", ".join(["?"] * len(self.COLUMNS))
        cols = ", ".join(self.COLUMNS)
        self.INSERT_SQL = f"INSERT INTO metrics ({cols}) VALUES ({placeholders})"

    @staticmethod
    def _b(value: Any) -> int:
        return 1 if bool(value) else 0

    def _migrate_schema(self) -> None:
        if self.conn is None:
            return
        cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(metrics)").fetchall()
        }
        migrations = {
            "rppg_quality_score": "REAL",
            "rppg_pose_roll_deg": "REAL",
            "rppg_pose_yaw_deg": "REAL",
            "rppg_pose_pitch_deg": "REAL",
            "rppg_roi_valid_count": "INTEGER",
            "rppg_roi_weight_forehead": "REAL",
            "rppg_roi_weight_l_cheek": "REAL",
            "rppg_roi_weight_r_cheek": "REAL",
            "rppg_roi_weight_glabella": "REAL",
            "rppg_landmark_jitter_norm": "REAL",
            "rppg_roi_area_stability": "REAL",
            "rppg_roi_area_jitter_ratio": "REAL",
            "rppg_roi_smoothing_applied": "BOOLEAN",
            "rppg_canonical_roi_warp_used": "BOOLEAN",
            "fatigue_quality_score": "REAL",
            "fatigue_blend_calib_progress": "REAL",
        }
        for name, col_type in migrations.items():
            if name not in cols:
                self.conn.execute(f"ALTER TABLE metrics ADD COLUMN {name} {col_type}")

    def record(self, data: dict) -> None:
        if self.conn is None:
            return
        try:
            row = tuple(data.get(col) for col in self.COLUMNS)
            self._buffer.append(row)
            now = time.time()
            if (len(self._buffer) >= self.BATCH_SIZE or
                    (now - self._last_flush_time) >= self.FLUSH_INTERVAL):
                self._flush()
        except Exception:
            pass

    def _flush(self) -> None:
        if not self._buffer or self.conn is None:
            return
        try:
            self.conn.executemany(self.INSERT_SQL, self._buffer)
            self.conn.commit()
            self._record_count += len(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.time()
        except Exception:
            self._buffer.clear()
            self._last_flush_time = time.time()

    def close(self) -> None:
        self._flush()
        self._cleanup()

    def _cleanup(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def get_recording_stats(self) -> tuple[int, float | None, float | None]:
        duration = None
        if self._start_time is not None:
            duration = time.time() - self._start_time
        total = self._record_count + len(self._buffer)
        return total, self._start_time, duration

    def __del__(self) -> None:
        try:
            self._flush()
        except Exception:
            pass
        self._cleanup()
