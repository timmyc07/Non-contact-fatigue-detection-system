"""SQLite metrics recorder for V2 fatigue + rPPG + fused scores.

寫入採「背景 writer thread + queue」設計：呼叫端 ``record()`` 只做 dict→tuple
組裝並丟進 thread-safe queue，實際 SQLite 連線建立、schema migration、批次
flush 全部在背景 writer thread 執行，呼叫端執行緒（GUI 主執行緒 / replay
子行程）不再被 sqlite flush 卡頓。``close()`` 會等待 writer thread 把佇列中
所有資料落盤後才回傳，維持既有的「close 後資料齊全」語意（video_replay 的
determinism 依賴此點）。``close()`` 完成後另外寫一份 ``<db>.meta.json``
sidecar（schema_version/rows/ts_min/ts_max），供 web dashboard 免逐一開連線
掃描即可列出錄製清單。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel 用來通知 writer thread：把目前緩衝區清空後結束迴圈。
_STOP = object()


class MetricsRecorder:
    """SQLite-based recorder for V2 metrics（背景執行緒寫入）。"""

    COLUMNS = [
        "timestamp",
        "fps",
        "frame_width",
        "frame_height",
        "codec",
        "camera_label",
        "rppg_face_detected",
        "bpm",
        "raw_bpm",
        "bpm_delta",
        "bpm_guarded",
        "bpm_guard_reason",
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
        "blink_duration_sec",
        "blink_duration_mean_sec",
        "blink_duration_z",
        "blink_amplitude",
        "blink_opening_velocity",
        "blink_opening_velocity_z",
        "blink_temporal_score",
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
        "fused_beh_blink_temporal_score",
        "fused_beh_squint_score",
        "fused_beh_microsleep_score",
        "fused_beh_gaze_score",
        "fused_beh_frown_score",
        "fused_beh_yawn_score",
        "bpm_calibrated",
        "calibration_version_id",
        "peak_freq_hz_calibrated",
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
        raw_bpm REAL,
        bpm_delta REAL,
        bpm_guarded BOOLEAN,
        bpm_guard_reason TEXT,
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
        blink_duration_sec REAL,
        blink_duration_mean_sec REAL,
        blink_duration_z REAL,
        blink_amplitude REAL,
        blink_opening_velocity REAL,
        blink_opening_velocity_z REAL,
        blink_temporal_score REAL,
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
        fused_beh_blink_temporal_score REAL,
        fused_beh_squint_score REAL,
        fused_beh_microsleep_score REAL,
        fused_beh_gaze_score REAL,
        fused_beh_frown_score REAL,
        fused_beh_yawn_score REAL,
        bpm_calibrated REAL,
        calibration_version_id TEXT,
        peak_freq_hz_calibrated REAL
    )
    """

    CREATE_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp)
    """

    BATCH_SIZE = 100
    FLUSH_INTERVAL = 1.0
    QUEUE_MAXSIZE = 10000
    INIT_TIMEOUT_SEC = 10.0
    JOIN_TIMEOUT_SEC = 15.0

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        self.conn: sqlite3.Connection | None = None
        self._start_time: float | None = None
        self._closed = False

        self._stats_lock = threading.Lock()
        self._record_count = 0
        self._dropped_count = 0
        self._write_error_count = 0

        placeholders = ", ".join(["?"] * len(self.COLUMNS))
        cols = ", ".join(self.COLUMNS)
        self.INSERT_SQL = f"INSERT INTO metrics ({cols}) VALUES ({placeholders})"

        self._queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._init_error: Exception | None = None

        self._writer_thread = threading.Thread(
            target=self._writer_main,
            name=f"MetricsRecorderWriter-{os.path.basename(self.db_path)}",
            daemon=True,
        )
        self._writer_thread.start()

        if not self._ready_event.wait(self.INIT_TIMEOUT_SEC):
            raise RuntimeError(
                f"Failed to initialize recorder at {db_path}: writer thread startup timed out"
            )
        if self._init_error is not None:
            raise RuntimeError(f"Failed to initialize recorder at {db_path}: {self._init_error}")

        self._start_time = time.time()

    @staticmethod
    def _b(value: Any) -> int:
        return 1 if bool(value) else 0

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(metrics)").fetchall()
        }
        migrations = {
            "rppg_quality_score": "REAL",
            "raw_bpm": "REAL",
            "bpm_delta": "REAL",
            "bpm_guarded": "BOOLEAN",
            "bpm_guard_reason": "TEXT",
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
            "blink_duration_sec": "REAL",
            "blink_duration_mean_sec": "REAL",
            "blink_duration_z": "REAL",
            "blink_amplitude": "REAL",
            "blink_opening_velocity": "REAL",
            "blink_opening_velocity_z": "REAL",
            "blink_temporal_score": "REAL",
            "fused_beh_blink_temporal_score": "REAL",
        }
        extra_migrations = {
            "bpm_calibrated": "REAL",
            "calibration_version_id": "TEXT",
            "peak_freq_hz_calibrated": "REAL",
        }
        migrations.update(extra_migrations)
        for name, col_type in migrations.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE metrics ADD COLUMN {name} {col_type}")

    # ------------------------------------------------------------------
    # 呼叫端執行緒 API（GUI 主執行緒 / replay 子行程）
    # ------------------------------------------------------------------

    def record(self, data: dict) -> None:
        if self._closed:
            return
        try:
            row = tuple(data.get(col) for col in self.COLUMNS)
        except Exception as exc:
            logger.warning(
                "MetricsRecorder(%s): failed to build row from data: %s", self.db_path, exc
            )
            return

        ts_raw = data.get("timestamp")
        try:
            ts_val = float(ts_raw) if ts_raw is not None else None
        except (TypeError, ValueError):
            ts_val = None

        try:
            self._queue.put_nowait((row, ts_val))
        except queue.Full:
            with self._stats_lock:
                self._dropped_count += 1
                dropped = self._dropped_count
            if dropped == 1 or dropped % 100 == 0:
                logger.warning(
                    "MetricsRecorder(%s): write queue full, dropping metrics record "
                    "(dropped_total=%d)",
                    self.db_path, dropped,
                )
            return
        except Exception as exc:
            logger.warning(
                "MetricsRecorder(%s): failed to enqueue record: %s", self.db_path, exc
            )
            return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        thread = getattr(self, "_writer_thread", None)
        q = getattr(self, "_queue", None)
        if thread is not None and thread.is_alive() and q is not None:
            # 主要停止訊號是 event（不受佇列滿影響）；sentinel 僅為了立刻喚醒
            # 正在 queue.get 等待的 writer，塞不進去也無妨。
            self._stop_event.set()
            try:
                q.put_nowait(_STOP)
            except queue.Full:
                pass
            thread.join(timeout=self.JOIN_TIMEOUT_SEC)
            if thread.is_alive():
                logger.warning(
                    "MetricsRecorder(%s): writer thread did not terminate within timeout",
                    self.db_path,
                )
        # writer 正常結束時自行關閉連線；逾時未終止則連線仍歸 writer 所有，
        # 此處關閉會與其 executemany/commit 競態，故僅在 writer 已停止時清理。
        if thread is None or not thread.is_alive():
            self._cleanup()

    def _cleanup(self) -> None:
        conn = getattr(self, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self.conn = None

    def get_recording_stats(self) -> tuple[int, float | None, float | None]:
        """回傳（實際成功落盤筆數, 開始時間, 已錄製秒數）。

        total 為 writer thread 批次寫入成功的筆數；入列後因批次寫入失敗
        被捨棄的資料不計入。
        """
        duration = None
        if self._start_time is not None:
            duration = time.time() - self._start_time
        with self._stats_lock:
            total = self._record_count
        return total, self._start_time, duration

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 背景 writer thread：連線建立、schema、批次 flush、sidecar 皆在此執行
    # ------------------------------------------------------------------

    def _writer_main(self) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = -8000")
            conn.execute(self.CREATE_TABLE_SQL)
            conn.execute(self.CREATE_INDEX_SQL)
            self._migrate_schema(conn)
            conn.commit()
        except Exception as exc:
            self._init_error = exc
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            self._ready_event.set()
            return

        self.conn = conn
        self._ready_event.set()

        buffer_rows: list[tuple] = []
        buffer_ts: list[float | None] = []
        last_flush = time.time()
        total_rows = 0
        ts_min: float | None = None
        ts_max: float | None = None

        def flush_buffer() -> None:
            nonlocal buffer_rows, buffer_ts, last_flush, total_rows, ts_min, ts_max
            if not buffer_rows:
                last_flush = time.time()
                return
            try:
                with conn:
                    conn.executemany(self.INSERT_SQL, buffer_rows)
                total_rows += len(buffer_rows)
                for ts in buffer_ts:
                    if ts is not None:
                        ts_min = ts if ts_min is None else min(ts_min, ts)
                        ts_max = ts if ts_max is None else max(ts_max, ts)
                with self._stats_lock:
                    self._record_count = total_rows
            except Exception as exc:
                self._write_error_count += 1
                if self._write_error_count == 1 or self._write_error_count % 50 == 0:
                    logger.warning(
                        "MetricsRecorder(%s): batch write failed (error #%d, %d rows dropped): %s",
                        self.db_path, self._write_error_count, len(buffer_rows), exc,
                    )
            finally:
                buffer_rows = []
                buffer_ts = []
                last_flush = time.time()

        while True:
            try:
                item = self._queue.get(timeout=self.FLUSH_INTERVAL)
            except queue.Empty:
                item = None

            # 停止條件：收到 sentinel，或 close() 已設 stop event 且佇列已排空
            # （record() 在 _closed 後不再入列，故 get 超時＋event 即代表排空）。
            stop = item is _STOP or (item is None and self._stop_event.is_set())
            if item is not None and not stop:
                try:
                    row, ts = item
                    buffer_rows.append(row)
                    buffer_ts.append(ts)
                except Exception as exc:
                    logger.warning(
                        "MetricsRecorder(%s): dropped malformed queue item: %s", self.db_path, exc
                    )

            now = time.time()
            if stop or len(buffer_rows) >= self.BATCH_SIZE or (now - last_flush) >= self.FLUSH_INTERVAL:
                flush_buffer()

            if stop:
                break

        try:
            conn.close()
        except Exception:
            pass
        self.conn = None

        self._write_meta_sidecar(total_rows, ts_min, ts_max)

    def _write_meta_sidecar(self, rows: int, ts_min: float | None, ts_max: float | None) -> None:
        meta_path = f"{self.db_path}.meta.json"
        payload = {
            "schema_version": 1,
            "rows": int(rows),
            "ts_min": ts_min,
            "ts_max": ts_max,
        }
        tmp_path = f"{meta_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, meta_path)
        except Exception as exc:
            logger.warning(
                "MetricsRecorder(%s): failed to write metadata sidecar: %s", self.db_path, exc
            )
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
