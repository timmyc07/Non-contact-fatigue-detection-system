"""rPPG BPM calibration store, live feed, and apply helpers.

Used by the main GUI calibration dialog at runtime.
Watch heart rate is only for calibration sessions; normal operation applies
saved version parameters without a watch.
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from gui.runtime_paths import data_path, data_root

ORIGIN_VERSION_ID = "v000_origin"

# 保留既有公開路徑常數供外部整合使用；實際讀寫函式仍動態解析 data root，
# 確保 Tauri 在啟動前注入的使用者資料目錄生效。
ROOT = data_root()
CALIBRATION_DIR = data_path("config", "rppg_calibration")
VERSIONS_DIR = CALIBRATION_DIR / "versions"
MANIFEST_PATH = CALIBRATION_DIR / "manifest.json"
LIVE_FEED_PATH = data_path("config", "rppg_live_feed.json")
FEED_ENABLED_FLAG = data_path("config", "rppg_calibration_feed.enabled")

DEFAULT_QUALITY_GATES = {
    "min_sqi": 0.45,
    "min_quality_score": 0.55,
    "min_roi_valid": 3,
    "require_warmup": True,
    "reject_bpm_guarded": True,
}

# 校準 session 專用：session 本身已有暖機期，門檻略放寬並允許 guarded 樣本
# （以 raw_bpm 參與中位數，避免穩定器鎖住舊值導致整窗無效）。
CALIBRATION_SESSION_QUALITY_GATES = {
    "min_sqi": 0.35,
    "min_quality_score": 0.45,
    "min_roi_valid": 2,
    "require_warmup": False,
    "reject_bpm_guarded": False,
}


@dataclass
class CalibrationParams:
    bpm_offset: float = 0.0
    bpm_scale: float = 1.0
    # P6：心跳帶有護欄自適應學到的 rPPG 解析參數（ROI 權重 / 頻帶 / PSD 峰選）。
    # None（預設，且所有既有版本檔）→ rPPG 走 config/mediapipe_tuning.json，逐位元不變。
    # 僅在離線驗證通過並主動採用的版本才非 None。結構如：
    #   {"roi_weights": {"forehead": 0.4, ...}, "band": [0.65, 3.7]}
    rppg_params: dict[str, Any] | None = None


@dataclass
class CalibrationVersion:
    id: str
    name: str
    model: str
    params: CalibrationParams
    created_at: str = ""
    builtin: bool = False
    note: str = ""
    session: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        # 條件式序列化 params：rppg_params 為 None 時不寫出，維持既有版本檔逐位元不變。
        params_dict: dict[str, Any] = {
            "bpm_offset": self.params.bpm_offset,
            "bpm_scale": self.params.bpm_scale,
        }
        if self.params.rppg_params is not None:
            params_dict["rppg_params"] = self.params.rppg_params
        data = {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "params": params_dict,
            "created_at": self.created_at,
            "builtin": self.builtin,
            "note": self.note,
        }
        if self.session is not None:
            data["session"] = self.session
        if self.metrics is not None:
            data["metrics"] = self.metrics
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationVersion":
        params_raw = data.get("params") or {}
        rppg_params_raw = params_raw.get("rppg_params")
        params = CalibrationParams(
            bpm_offset=float(params_raw.get("bpm_offset", 0.0) or 0.0),
            bpm_scale=float(params_raw.get("bpm_scale", 1.0) or 1.0),
            rppg_params=dict(rppg_params_raw) if isinstance(rppg_params_raw, dict) else None,
        )
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            model=str(data.get("model", "bias")),
            params=params,
            created_at=str(data.get("created_at", "") or ""),
            builtin=bool(data.get("builtin", False)),
            note=str(data.get("note", "") or ""),
            session=dict(data["session"]) if isinstance(data.get("session"), dict) else None,
            metrics=dict(data["metrics"]) if isinstance(data.get("metrics"), dict) else None,
        )

    @property
    def is_identity(self) -> bool:
        # 帶 rppg_params 的版本即使 BPM 修正為零也非 identity（它改變解析參數）。
        return self.model == "identity" or (
            abs(self.params.bpm_offset) < 1e-9
            and abs(self.params.bpm_scale - 1.0) < 1e-9
            and self.params.rppg_params is None
        )


def origin_version() -> CalibrationVersion:
    return CalibrationVersion(
        id=ORIGIN_VERSION_ID,
        name="最初版本（未校準）",
        model="identity",
        params=CalibrationParams(),
        created_at="",
        builtin=True,
        note="不套用任何 BPM 修正。",
    )


def apply_bpm_calibration(
    bpm: float,
    version: CalibrationVersion | Mapping[str, Any] | None,
) -> float:
    if bpm <= 0 or version is None:
        return float(bpm)
    if isinstance(version, Mapping):
        version = CalibrationVersion.from_dict(version)
    if version.is_identity:
        return float(bpm)
    return float(version.params.bpm_scale * bpm + version.params.bpm_offset)


def apply_calibration_dict(metrics: Mapping[str, Any], version: CalibrationVersion) -> dict[str, Any]:
    out = dict(metrics)
    bpm = float(metrics.get("bpm", 0.0) or 0.0)
    out["bpm_calibrated"] = apply_bpm_calibration(bpm, version) if bpm > 0 else 0.0
    out["calibration_version_id"] = version.id
    if out["bpm_calibrated"] > 0:
        out["peak_freq_hz_calibrated"] = out["bpm_calibrated"] / 60.0
    else:
        out["peak_freq_hz_calibrated"] = 0.0
    return out


def apply_calibration_to_metrics(metrics: Any, version: CalibrationVersion | None) -> Any:
    """Return a copy of RppgMetrics with calibrated BPM fields filled."""
    if metrics is None or version is None:
        return metrics
    if not is_dataclass(metrics):
        return metrics
    bpm = float(getattr(metrics, "bpm", 0.0) or 0.0)
    bpm_cal = apply_bpm_calibration(bpm, version) if bpm > 0 else 0.0
    peak_cal = bpm_cal / 60.0 if bpm_cal > 0 else 0.0
    return replace(
        metrics,
        bpm_calibrated=bpm_cal,
        calibration_version_id=version.id,
        peak_freq_hz_calibrated=peak_cal,
    )


def effective_bpm(metrics: Any) -> float:
    """BPM used for display/fusion: calibrated when available."""
    if metrics is None:
        return 0.0
    bpm_cal = float(getattr(metrics, "bpm_calibrated", 0.0) or 0.0)
    if bpm_cal > 0:
        return bpm_cal
    return float(getattr(metrics, "bpm", 0.0) or 0.0)


def calibration_rppg_bpm(sample: Mapping[str, Any]) -> float:
    """BPM used when pairing with watch during calibration."""
    raw = float(sample.get("raw_bpm", 0.0) or 0.0)
    bpm = float(sample.get("bpm", 0.0) or 0.0)
    if bool(sample.get("bpm_guarded", False)) and raw > 0:
        return raw
    return bpm if bpm > 0 else raw


def rppg_sample_quality_ok(sample: Mapping[str, Any], gates: Mapping[str, Any] | None = None) -> bool:
    merged = {**DEFAULT_QUALITY_GATES, **(gates or {})}
    if merged.get("require_warmup") and float(sample.get("warmup_progress", 0.0) or 0.0) < 1.0:
        return False
    if float(sample.get("sqi", 0.0) or 0.0) < float(merged["min_sqi"]):
        return False
    if float(sample.get("quality_score", 0.0) or 0.0) < float(merged["min_quality_score"]):
        return False
    if int(sample.get("roi_valid_count", 0) or 0) < int(merged["min_roi_valid"]):
        return False
    if merged.get("reject_bpm_guarded") and bool(sample.get("bpm_guarded", False)):
        return False
    bpm = float(sample.get("bpm", 0.0) or 0.0)
    return bpm > 0


def compute_offset_from_residuals(residuals: list[float]) -> float:
    if not residuals:
        return 0.0
    return float(statistics.median(residuals))


def compute_mae(pairs: list[tuple[float, float]], offset: float = 0.0) -> float:
    if not pairs:
        return 0.0
    errs = [abs((rppg + offset) - watch) for watch, rppg in pairs]
    return float(statistics.mean(errs))


@dataclass
class WindowResidual:
    start_ts: float
    end_ts: float
    watch_median: float
    rppg_median: float
    residual: float
    accepted: bool
    reason: str = ""


class CalibrationSessionAnalyzer:
    """Pair watch and rPPG samples into fixed windows and estimate offset."""

    def __init__(
        self,
        window_sec: float = 30.0,
        warmup_sec: float = 30.0,
        quality_gates: Mapping[str, Any] | None = None,
    ) -> None:
        self.window_sec = float(window_sec)
        self.warmup_sec = float(warmup_sec)
        self.quality_gates = dict(DEFAULT_QUALITY_GATES)
        if quality_gates:
            self.quality_gates.update(dict(quality_gates))
        self._watch: list[tuple[float, float]] = []
        self._rppg: list[tuple[float, float, dict[str, Any]]] = []
        self.windows: list[WindowResidual] = []

    @property
    def watch_sample_count(self) -> int:
        return len(self._watch)

    def watch_time_range(self) -> tuple[float | None, float | None]:
        if not self._watch:
            return None, None
        times = [ts for ts, _ in self._watch]
        return float(min(times)), float(max(times))

    def add_watch(self, received_at: float, bpm: float) -> None:
        if bpm > 0:
            self._watch.append((received_at, float(bpm)))

    def add_rppg(self, received_at: float, sample: Mapping[str, Any]) -> None:
        bpm = calibration_rppg_bpm(sample)
        if bpm > 0:
            self._rppg.append((received_at, bpm, dict(sample)))

    def _median_watch(self, start: float, end: float) -> float | None:
        vals = [bpm for ts, bpm in self._watch if start <= ts < end]
        return float(statistics.median(vals)) if vals else None

    def _median_rppg(
        self, start: float, end: float
    ) -> tuple[float | None, dict[str, Any] | None, str]:
        vals = [(ts, bpm, sample) for ts, bpm, sample in self._rppg if start <= ts < end]
        if not vals:
            return None, None, "no_rppg_samples"
        good = [item for item in vals if rppg_sample_quality_ok(item[2], self.quality_gates)]
        if not good:
            return None, None, "no_quality_rppg"
        bpms = [bpm for _, bpm, _ in good]
        return float(statistics.median(bpms)), good[-1][2], ""

    def analyze(self, start_ts: float, end_ts: float) -> list[WindowResidual]:
        self.windows.clear()
        t = start_ts + self.warmup_sec
        while t + self.window_sec <= end_ts:
            w_start = t
            w_end = t + self.window_sec
            watch_med = self._median_watch(w_start, w_end)
            rppg_med, sample, rppg_reason = self._median_rppg(w_start, w_end)
            accepted = watch_med is not None and rppg_med is not None
            reason = ""
            if watch_med is None:
                reason = "no_watch"
            elif rppg_med is None:
                reason = rppg_reason or "no_quality_rppg"
            residual = float(watch_med - rppg_med) if accepted else 0.0
            self.windows.append(
                WindowResidual(
                    start_ts=w_start,
                    end_ts=w_end,
                    watch_median=float(watch_med or 0.0),
                    rppg_median=float(rppg_med or 0.0),
                    residual=residual,
                    accepted=accepted,
                    reason=reason,
                )
            )
            t += self.window_sec
        return list(self.windows)

    def estimate(self, start_ts: float, end_ts: float) -> dict[str, Any]:
        windows = self.analyze(start_ts, end_ts)
        accepted = [w for w in windows if w.accepted]
        residuals = [w.residual for w in accepted]
        pairs = [(w.watch_median, w.rppg_median) for w in accepted]
        offset = compute_offset_from_residuals(residuals)
        return {
            "offset_bpm": offset,
            "windows": windows,
            "windows_used": len(accepted),
            "windows_rejected": len(windows) - len(accepted),
            "mae_before_bpm": compute_mae(pairs, offset=0.0),
            "mae_after_bpm": compute_mae(pairs, offset=offset),
            "median_residual": offset,
            "pairs": pairs,
        }


class CalibrationVersionStore:
    """Persistent versioned BPM calibration profiles."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else data_path("config", "rppg_calibration")
        self.versions_dir = self.root / "versions"
        self.manifest_path = self.root / "manifest.json"
        self._manifest_mtime: float = 0.0
        self._manifest: dict[str, Any] = {}
        self._version_cache: tuple[tuple[Path, int, int], CalibrationVersion] | None = None
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            origin = origin_version()
            self._manifest = {
                "active_version_id": ORIGIN_VERSION_ID,
                "updated_at": _now_iso(),
                "versions": [
                    {
                        "id": origin.id,
                        "name": origin.name,
                        "builtin": True,
                        "file": f"versions/{origin.id}.json",
                    }
                ],
            }
            self._write_json(self.manifest_path, self._manifest)
            self._write_json(self.versions_dir / f"{origin.id}.json", origin.to_dict())
        self.reload()

    def reload(self) -> None:
        if not self.manifest_path.exists():
            self.ensure_layout()
            return
        mtime = self.manifest_path.stat().st_mtime
        if mtime == self._manifest_mtime and self._manifest:
            return
        self._manifest = self._read_json(self.manifest_path)
        self._manifest_mtime = mtime

    def list_versions(self) -> list[dict[str, Any]]:
        self.reload()
        versions = self._manifest.get("versions") or []
        return [dict(v) for v in versions if isinstance(v, dict)]

    def get_active_version_id(self) -> str:
        self.reload()
        return str(self._manifest.get("active_version_id") or ORIGIN_VERSION_ID)

    def get_version(self, version_id: str | None = None) -> CalibrationVersion:
        self.reload()
        vid = version_id or self.get_active_version_id()
        if vid == ORIGIN_VERSION_ID:
            path = self.versions_dir / f"{ORIGIN_VERSION_ID}.json"
        else:
            entry = self._find_entry(vid)
            if entry is None:
                raise KeyError(f"找不到校準版本：{vid}")
            rel = str(entry.get("file") or f"versions/{vid}.json")
            path = self.root / rel
        try:
            stat = path.stat()
        except FileNotFoundError:
            if vid == ORIGIN_VERSION_ID:
                return origin_version()
            raise FileNotFoundError(f"校準版本檔案不存在：{path}")
        fingerprint = (path, stat.st_mtime_ns, stat.st_size)
        cached = self._version_cache
        if cached is None or cached[0] != fingerprint:
            version = CalibrationVersion.from_dict(self._read_json(path))
            self._version_cache = (fingerprint, version)
        else:
            version = cached[1]
        # getter 保留獨立可變物件契約，呼叫端修改不污染後續讀取。
        return deepcopy(version)

    def get_active_version(self) -> CalibrationVersion:
        return self.get_version(self.get_active_version_id())

    def set_active_version(self, version_id: str) -> CalibrationVersion:
        self.reload()
        if version_id != ORIGIN_VERSION_ID and self._find_entry(version_id) is None:
            raise KeyError(f"找不到校準版本：{version_id}")
        manifest = {**self._manifest, "active_version_id": version_id, "updated_at": _now_iso()}
        self._write_json(self.manifest_path, manifest)
        self._manifest = manifest
        self._manifest_mtime = self.manifest_path.stat().st_mtime
        return self.get_version(version_id)

    def save_new_version(
        self,
        name: str,
        offset_bpm: float,
        *,
        note: str = "",
        session: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        scale: float = 1.0,
        rppg_params: Mapping[str, Any] | None = None,
    ) -> CalibrationVersion:
        self.reload()
        version_id = _new_version_id()
        created_at = _now_iso()
        version = CalibrationVersion(
            id=version_id,
            name=name.strip() or version_id,
            model="bias",
            params=CalibrationParams(bpm_offset=float(offset_bpm), bpm_scale=float(scale),
                                     rppg_params=dict(rppg_params) if rppg_params else None),
            created_at=created_at,
            builtin=False,
            note=note.strip(),
            session=dict(session) if session else None,
            metrics=dict(metrics) if metrics else None,
        )
        rel = f"versions/{version_id}.json"
        self._write_json(self.versions_dir / f"{version_id}.json", version.to_dict())
        entries = list(self.list_versions())
        entries.append({"id": version_id, "name": version.name, "file": rel, "created_at": created_at})
        manifest = {**self._manifest, "versions": entries,
                    "active_version_id": version_id, "updated_at": created_at}
        self._write_json(self.manifest_path, manifest)
        self._manifest = manifest
        self._manifest_mtime = self.manifest_path.stat().st_mtime
        return version

    def delete_version(self, version_id: str) -> None:
        if version_id == ORIGIN_VERSION_ID:
            raise ValueError("不能刪除最初版本 v000_origin")
        self.reload()
        entry = self._find_entry(version_id)
        if entry is None:
            raise KeyError(f"找不到校準版本：{version_id}")
        rel = str(entry.get("file") or f"versions/{version_id}.json")
        path = self.root / rel
        entries = [
            v for v in self.list_versions() if str(v.get("id")) != version_id
        ]
        active = self.get_active_version_id()
        manifest = {**self._manifest, "versions": entries,
                    "active_version_id": ORIGIN_VERSION_ID if active == version_id else active,
                    "updated_at": _now_iso()}
        self._write_json(self.manifest_path, manifest)
        self._manifest = manifest
        self._manifest_mtime = self.manifest_path.stat().st_mtime
        path.unlink(missing_ok=True)

    def _find_entry(self, version_id: str) -> dict[str, Any] | None:
        for entry in self.list_versions():
            if str(entry.get("id")) == version_id:
                return entry
        return None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _write_json(path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def write_live_feed(metrics: Any, *, enabled: bool | None = None) -> None:
    if enabled is None:
        enabled = is_live_feed_enabled()
    if not enabled or metrics is None:
        return
    payload = {
        "timestamp": time.time(),
        "bpm": float(getattr(metrics, "bpm", 0.0) or 0.0),
        "raw_bpm": float(getattr(metrics, "raw_bpm", 0.0) or 0.0),
        "sqi": float(getattr(metrics, "sqi", 0.0) or 0.0),
        "quality_score": float(getattr(metrics, "quality_score", 0.0) or 0.0),
        "warmup_progress": float(getattr(metrics, "warmup_progress", 0.0) or 0.0),
        "roi_valid_count": int(getattr(metrics, "roi_valid_count", 0) or 0),
        "bpm_guarded": bool(getattr(metrics, "bpm_guarded", False)),
        "bpm_guard_reason": str(getattr(metrics, "bpm_guard_reason", "") or ""),
        "face_detected": bool(getattr(metrics, "face_detected", False)),
    }
    path = data_path("config", "rppg_live_feed.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_live_feed(max_age_sec: float = 5.0) -> dict[str, Any] | None:
    path = data_path("config", "rppg_live_feed.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ts = float(data.get("timestamp", 0.0) or 0.0)
    if ts <= 0 or (time.time() - ts) > max_age_sec:
        return None
    return data


def set_live_feed_enabled(enabled: bool) -> None:
    path = data_path("config", "rppg_calibration_feed.enabled")
    path.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        path.write_text("enabled\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def is_live_feed_enabled() -> bool:
    return data_path("config", "rppg_calibration_feed.enabled").exists()


def metrics_to_feed_dict(metrics: Any) -> dict[str, Any]:
    if is_dataclass(metrics):
        return {f.name: getattr(metrics, f.name) for f in fields(metrics)}
    if isinstance(metrics, Mapping):
        return dict(metrics)
    return {}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_version_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"v{stamp}_{uuid4().hex}"
