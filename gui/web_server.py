"""Flask + Socket.IO Web Server for real-time metrics and playback."""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable, cast

from flask import Flask, render_template, jsonify, request, Response, send_file, abort
from flask_socketio import SocketIO, emit
import gzip
import re
import sqlite3

from gui.file_browser_client import FileBrowserClient

_ws_connected_clients: set = set()

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_PLAYBACK_DEFAULT_LIMIT = 100
_PLAYBACK_MAX_LIMIT = 1000
WEB_DASHBOARD_DEFAULT_PORT = 5000


def get_lan_ipv4_addresses() -> list[str]:
    """列舉本機可用於區域網存取的 IPv4 位址（不含 loopback）。"""
    seen: set[str] = set()
    addresses: list[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith("127.") or ip in seen:
            return
        seen.add(ip)
        addresses.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            add(sock.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            host = info[4][0]
            if isinstance(host, str):
                add(host)
    except OSError:
        pass

    return addresses


def format_web_dashboard_urls(
    port: int = WEB_DASHBOARD_DEFAULT_PORT,
    *,
    allow_lan: bool = False,
) -> list[str]:
    urls = [f"http://127.0.0.1:{port}"]
    if allow_lan:
        urls.extend(f"http://{ip}:{port}" for ip in get_lan_ipv4_addresses())
    return urls


def _build_allowed_origins(host: str, port: int) -> list[str]:
    """Socket.IO 允許連線的 Origin 白名單。

    本機一律允許；僅在 LAN 模式（host 綁非 loopback）時再加入各 LAN IPv4，
    避免使用萬用字元 ``*`` 讓任意惡意網頁連上本機竊取即時生理資料。
    以主機 IP 連線（README 建議方式）仍可正常運作；若以主機名稱連線則需自行加入。
    """
    origins = [
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    ]
    if host not in ("127.0.0.1", "localhost", ""):
        origins.extend(f"http://{ip}:{port}" for ip in get_lan_ipv4_addresses())
    return origins


def _is_local_request() -> bool:
    remote_addr = (request.remote_addr or "").strip()
    if remote_addr in _LOCAL_HOSTS:
        return True
    if remote_addr.startswith("::ffff:"):
        return remote_addr.split("::ffff:", 1)[1] in _LOCAL_HOSTS
    return False


def _ensure_lan_endpoint_allowed() -> Optional[Response]:
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _parse_pagination_args() -> tuple[Optional[tuple[int, int]], Optional[Any]]:
    raw_offset = request.args.get("offset", "0")
    raw_limit = request.args.get("limit", str(_PLAYBACK_DEFAULT_LIMIT))
    try:
        offset = int(raw_offset)
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None, (jsonify({"success": False, "error": "Invalid offset or limit"}), 400)

    if offset < 0:
        return None, (jsonify({"success": False, "error": "offset must be >= 0"}), 400)
    if limit < 1 or limit > _PLAYBACK_MAX_LIMIT:
        return None, (
            jsonify({
                "success": False,
                "error": f"limit must be between 1 and {_PLAYBACK_MAX_LIMIT}",
            }),
            400,
        )
    return (offset, limit), None


def _row_get(row: dict[str, Any], columns: set[str], key: str, default: Any = None) -> Any:
    if key in columns:
        return row.get(key, default)
    return default


class MetricsBuffer:
    def __init__(self, maxsize: int = 300):
        self.maxsize = maxsize
        self.data = deque(maxlen=maxsize)
        self._lock = threading.Lock()

    def append(self, metrics: dict) -> None:
        with self._lock:
            self.data.append(metrics)

    def get_all(self) -> list:
        with self._lock:
            return list(self.data)

    def clear(self) -> None:
        with self._lock:
            self.data.clear()


class PlaybackManager:
    def __init__(self, recordings_dir: str | Path) -> None:
        self.recordings_dir = Path(recordings_dir)
        self.current_db: Optional[str] = None
        self.current_position: int = 0
        self._lock = threading.Lock()
        self._recordings_cache: list = []
        self._recordings_cache_time: float = 0.0
        self._recordings_cache_mtime: float = 0.0
        self._RECORDINGS_CACHE_TTL: float = 60.0

    def _candidate_recording_dbs(self) -> list[Path]:
        db_files = set(self.recordings_dir.glob("metrics_*.db"))
        db_files.update(self.recordings_dir.glob("utarldd_runs/*/metrics_*.db"))
        return sorted(db_files, key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)

    def _recordings_mtime_marker(self) -> float:
        mtimes: list[float] = []
        for path in (self.recordings_dir, self.recordings_dir / "utarldd_runs"):
            if path.exists():
                try:
                    mtimes.append(path.stat().st_mtime)
                except OSError:
                    pass
        for db_file in self._candidate_recording_dbs():
            try:
                mtimes.append(db_file.stat().st_mtime)
            except OSError:
                pass
        return max(mtimes) if mtimes else 0.0

    @staticmethod
    def _parse_filename_datetime(filename: str) -> Optional[datetime]:
        m = re.match(r"metrics_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
        if m:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), int(m.group(6)),
            )
        return None

    def list_recordings(self) -> list[dict]:
        now = time.time()
        dir_mtime = self._recordings_mtime_marker()
        if (
            now - self._recordings_cache_time < self._RECORDINGS_CACHE_TTL
            and self._recordings_cache
            and dir_mtime == self._recordings_cache_mtime
        ):
            return self._recordings_cache

        recordings = []
        if not self.recordings_dir.exists():
            return recordings

        for db_file in self._candidate_recording_dbs():
            try:
                conn = sqlite3.connect(str(db_file))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM metrics")
                count = cursor.fetchone()[0]
                cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM metrics")
                ts_row = cursor.fetchone()
                if ts_row is None:
                    min_ts_raw, max_ts_raw = None, None
                else:
                    min_ts_raw, max_ts_raw = ts_row
                conn.close()

                if count > 0:
                    duration = max(_safe_float(max_ts_raw) - _safe_float(min_ts_raw), 0.0)
                    dt = self._parse_filename_datetime(db_file.name)
                    if dt is None:
                        dt = datetime.fromtimestamp(db_file.stat().st_ctime)

                    video_stem = db_file.name.replace("metrics_", "video_").replace(".db", "")
                    video_name = None
                    has_video = False
                    for _ext in (".mp4", ".avi"):
                        _vn = video_stem + _ext
                        video_path = db_file.parent / _vn
                        if video_path.exists():
                            video_name = str(video_path.relative_to(self.recordings_dir).as_posix())
                            has_video = True
                            break

                    filename = str(db_file.relative_to(self.recordings_dir).as_posix())
                    recordings.append(
                        {
                            "filename": filename,
                            "path": str(db_file),
                            "session_name": dt.strftime("%Y/%m/%d %H:%M:%S"),
                            "created": dt.timestamp(),
                            "created_str": dt.strftime("%Y/%m/%d %H:%M:%S"),
                            "record_count": count,
                            "duration_sec": duration,
                            "duration_str": self._fmt_duration(duration),
                            "has_video": has_video,
                            "video_filename": video_name if has_video else None,
                        }
                    )
            except Exception as e:
                print(f"[WebServer] 讀取錄製檔 {db_file.name} 失敗: {e}")

        self._recordings_cache = recordings
        self._recordings_cache_time = time.time()
        self._recordings_cache_mtime = dir_mtime
        return recordings

    @staticmethod
    def _fmt_duration(sec: float) -> str:
        if sec <= 0:
            return "0 秒"
        m = int(sec // 60)
        s = int(sec % 60)
        if m > 0:
            return f"{m} 分 {s} 秒"
        return f"{s} 秒"

    def get_recording_data(self, db_path: str, offset: int = 0, limit: int = 100) -> dict:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM metrics")
            total_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT * FROM metrics
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )
            rows = cursor.fetchall()
            conn.close()

            data = []
            for row in rows:
                data.append(dict(row))

            return {
                "success": True,
                "total": total_count,
                "offset": offset,
                "limit": limit,
                "data": data,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _safe_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        number = float(cast(Any, value))
        return number if number == number else 0.0
    except (TypeError, ValueError):
        return 0.0


def create_app(
    metrics_buffer: MetricsBuffer,
    playback_manager: PlaybackManager,
    recording_manager: Optional[Any] = None,
    get_latest_packet: Optional[Callable] = None,
    shutdown_token: Optional[str] = None,
    allowed_origins: Optional[list[str]] = None,
) -> tuple[Flask, SocketIO]:
    _fb_client = FileBrowserClient()
    _fb_lock = threading.Lock()
    _fb_cache_dir = playback_manager.recordings_dir / ".fb_cache"

    def resolve_allowed_db_path(raw_db_path: str) -> Optional[Path]:
        candidate = Path(raw_db_path).expanduser().resolve(strict=False)
        allowed_roots = [playback_manager.recordings_dir.resolve()]
        allowed_roots.append(_fb_cache_dir.resolve())
        if candidate.suffix.lower() != ".db" or not candidate.exists():
            return None
        if any(_is_relative_to(candidate, root) for root in allowed_roots):
            return candidate
        return None

    app_dir = Path(__file__).parent
    template_dir = app_dir / "web_ui" / "templates"
    static_dir = app_dir / "web_ui" / "static"

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        static_url_path="/static",
    )
    app.config["SECRET_KEY"] = secrets.token_hex(32)

    socketio = SocketIO(
        app,
        # 收斂 CORS：正式路徑（WebServerThread）會傳入本機 + LAN Origin 白名單；
        # 未指定時（如直接建立/測試）才退回 "*"。
        cors_allowed_origins=allowed_origins if allowed_origins is not None else "*",
        async_mode="threading",
        ping_timeout=60,
        ping_interval=25,
        max_http_buffer_size=10_000_000,
    )

    @app.before_request
    def _restrict_fb_endpoints() -> Optional[Response]:
        # File Browser 端點操作伺服器端共用的遠端憑證；限制為本機發起，
        # 避免同網段其他裝置盜用已登入的 File Browser session。
        if request.path.startswith("/api/fb/") and not _is_local_request():
            abort(403)
        return None

    latest_packet_error_logged = False

    def get_latest_metrics_packet() -> Optional[dict[str, Any]]:
        nonlocal latest_packet_error_logged
        if get_latest_packet is None:
            return None
        try:
            packet = get_latest_packet()
        except Exception as exc:
            if not latest_packet_error_logged:
                print(f"[WebServer] get_latest_packet failed: {exc}")
                latest_packet_error_logged = True
            return None
        if not isinstance(packet, dict):
            return None
        return dict(packet)

    def get_metrics_history_with_latest() -> tuple[list, Optional[dict[str, Any]]]:
        data = metrics_buffer.get_all()
        latest = get_latest_metrics_packet()
        if latest is not None and (not data or data[-1] != latest):
            data = [*data, latest]
        return data, latest

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/api/recordings")
    def get_recordings():
        try:
            recordings = (
                recording_manager.list_local_recordings()
                if recording_manager is not None
                else playback_manager.list_recordings()
            )
            return jsonify({"success": True, "data": recordings})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/playback")
    def playback_data():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        from urllib.parse import unquote

        db_path = request.args.get("db_path")
        pagination, pagination_error = _parse_pagination_args()
        if pagination_error is not None:
            return pagination_error
        assert pagination is not None
        offset, limit = pagination

        if not db_path:
            return jsonify({"success": False, "error": "Missing db_path"}), 400

        db_path = unquote(db_path)
        allowed_db_path = resolve_allowed_db_path(db_path)
        if allowed_db_path is None:
            return jsonify({"success": False, "error": "Invalid db_path"}), 403
        result = playback_manager.get_recording_data(str(allowed_db_path), offset, limit)
        return jsonify(result)

    @app.route("/api/playback/full")
    def playback_full():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        from urllib.parse import unquote

        db_path = request.args.get("db_path")
        if not db_path:
            return jsonify({"success": False, "error": "Missing db_path"}), 400

        allowed_db_path = resolve_allowed_db_path(unquote(db_path))
        if allowed_db_path is None:
            return jsonify({"success": False, "error": "Invalid db_path"}), 403

        try:
            with sqlite3.connect(str(allowed_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(metrics)")
                columns = {str(item[1]) for item in cursor.fetchall()}
                cursor.execute("SELECT COUNT(*) FROM metrics")
                total = cursor.fetchone()[0]
                cursor.execute("SELECT * FROM metrics ORDER BY timestamp ASC")
                rows = cursor.fetchall()

            data = []
            for row in rows:
                row = dict(row)
                perclos = _safe_float(_row_get(row, columns, "perclos")) * 100.0
                entry = {
                    "t": _safe_float(_row_get(row, columns, "timestamp")),
                    "fps": _safe_float(_row_get(row, columns, "fps")),
                    "face": bool(
                        _row_get(row, columns, "fatigue_face_detected")
                        or _row_get(row, columns, "rppg_face_detected")
                    ),
                    "cal": bool(_row_get(row, columns, "calibrated")),
                    "ear": _safe_float(_row_get(row, columns, "ear")),
                    "perclos": perclos,
                    "blink": int(_row_get(row, columns, "blink_count") or 0),
                    "blink_rate_pm": _safe_float(_row_get(row, columns, "blink_rate_pm")),
                    "blink_duration_sec": _safe_float(_row_get(row, columns, "blink_duration_sec")),
                    "blink_duration_mean_sec": _safe_float(_row_get(row, columns, "blink_duration_mean_sec")),
                    "blink_duration_z": _safe_float(_row_get(row, columns, "blink_duration_z")),
                    "blink_amplitude": _safe_float(_row_get(row, columns, "blink_amplitude")),
                    "blink_opening_velocity": _safe_float(_row_get(row, columns, "blink_opening_velocity")),
                    "blink_opening_velocity_z": _safe_float(_row_get(row, columns, "blink_opening_velocity_z")),
                    "blink_temporal_score": _safe_float(_row_get(row, columns, "blink_temporal_score")),
                    "status": str(_row_get(row, columns, "status", "--") or "--"),
                    "early_warning": bool(_row_get(row, columns, "early_warning")),
                    "bpm": _safe_float(_row_get(row, columns, "bpm")),
                    "raw_bpm": _safe_float(_row_get(row, columns, "raw_bpm")),
                    "bpm_delta": _safe_float(_row_get(row, columns, "bpm_delta")),
                    "bpm_guarded": bool(_row_get(row, columns, "bpm_guarded")),
                    "bpm_guard_reason": str(_row_get(row, columns, "bpm_guard_reason", "") or ""),
                    "rmssd": _safe_float(_row_get(row, columns, "rmssd")),
                    "sdnn": _safe_float(_row_get(row, columns, "sdnn")),
                    "lf_hf": _safe_float(_row_get(row, columns, "lf_hf")),
                    "sqi": _safe_float(_row_get(row, columns, "sqi")),
                    "rppg_quality_score": _safe_float(_row_get(row, columns, "rppg_quality_score")),
                    "rppg_pose_roll_deg": _safe_float(_row_get(row, columns, "rppg_pose_roll_deg")),
                    "rppg_pose_yaw_deg": _safe_float(_row_get(row, columns, "rppg_pose_yaw_deg")),
                    "rppg_pose_pitch_deg": _safe_float(_row_get(row, columns, "rppg_pose_pitch_deg")),
                    "rppg_roi_valid_count": int(_row_get(row, columns, "rppg_roi_valid_count") or 0),
                    "rppg_roi_weight_forehead": _safe_float(_row_get(row, columns, "rppg_roi_weight_forehead")),
                    "rppg_roi_weight_l_cheek": _safe_float(_row_get(row, columns, "rppg_roi_weight_l_cheek")),
                    "rppg_roi_weight_r_cheek": _safe_float(_row_get(row, columns, "rppg_roi_weight_r_cheek")),
                    "rppg_roi_weight_glabella": _safe_float(_row_get(row, columns, "rppg_roi_weight_glabella")),
                    "rppg_landmark_jitter_norm": _safe_float(_row_get(row, columns, "rppg_landmark_jitter_norm")),
                    "rppg_roi_area_stability": _safe_float(_row_get(row, columns, "rppg_roi_area_stability")),
                    "rppg_roi_area_jitter_ratio": _safe_float(_row_get(row, columns, "rppg_roi_area_jitter_ratio")),
                    "rppg_roi_smoothing_applied": bool(_row_get(row, columns, "rppg_roi_smoothing_applied")),
                    "rppg_canonical_roi_warp_used": bool(_row_get(row, columns, "rppg_canonical_roi_warp_used")),
                    "prob": _safe_float(_row_get(row, columns, "stress_prob")),
                    "f_state": str(_row_get(row, columns, "fused_level", "--") or "--"),
                    "f_conf": _safe_float(_row_get(row, columns, "fused_score")),
                    "head_pitch": _safe_float(_row_get(row, columns, "head_pitch")),
                    "head_yaw": _safe_float(_row_get(row, columns, "head_yaw")),
                    "head_roll": _safe_float(_row_get(row, columns, "head_roll")),
                    "fatigue_quality_score": _safe_float(_row_get(row, columns, "fatigue_quality_score")),
                    "fatigue_blend_calib_progress": _safe_float(_row_get(row, columns, "fatigue_blend_calib_progress")),
                    "microsleep_alert": bool(_row_get(row, columns, "microsleep_alert")),
                    "microsleep_count": int(_row_get(row, columns, "microsleep_count") or 0),
                    "yawn_count": int(_row_get(row, columns, "yawn_count") or 0),
                    "mar": _safe_float(_row_get(row, columns, "mar")),
                    "gaze_stability_index": _safe_float(_row_get(row, columns, "gaze_stability_index")),
                    "gaze_mental_fatigue": bool(_row_get(row, columns, "gaze_mental_fatigue")),
                    "fixation_duration": _safe_float(_row_get(row, columns, "fixation_duration")),
                    "saccade_freq_pm": _safe_float(_row_get(row, columns, "saccade_freq_pm")),
                    "is_squinting": bool(_row_get(row, columns, "is_squinting")),
                    "is_frowning": bool(_row_get(row, columns, "is_frowning")),
                    "iris_ratio_trend": _safe_float(_row_get(row, columns, "iris_ratio_trend")),
                }
                entry["dl_bpm"] = 0.0
                entry["dl_conf"] = 0.0
                entry["dl_avail"] = False
                entry["dl_st"] = ""
                data.append(entry)

            payload = json.dumps(
                {"success": True, "total": total, "data": data},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            accept_enc = request.headers.get("Accept-Encoding", "")
            if "gzip" in accept_enc and len(payload) > 1024:
                compressed = gzip.compress(payload, compresslevel=4)
                return Response(
                    compressed,
                    content_type="application/json",
                    headers={"Content-Encoding": "gzip"},
                )
            return Response(payload, content_type="application/json")
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/video/<path:filename>")
    def serve_video(filename):
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        rel_name = str(filename or "").strip().replace("\\", "/")
        rel_path = Path(rel_name)
        if not rel_name or rel_path.is_absolute() or any(part in ("", ".", "..") for part in rel_path.parts):
            abort(400)
        if not rel_name.lower().endswith((".mp4", ".avi")):
            abort(400)

        video_path = (playback_manager.recordings_dir / rel_path).resolve()
        allowed_dir = playback_manager.recordings_dir.resolve()
        if not _is_relative_to(video_path, allowed_dir):
            abort(403)
        if not video_path.exists():
            abort(404)

        mimetype = "video/mp4" if rel_name.lower().endswith(".mp4") else "video/x-msvideo"
        return send_file(
            str(video_path),
            mimetype=mimetype,
            conditional=True,
        )

    @app.route("/api/fb/login", methods=["POST"])
    def fb_login():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        data = request.get_json(silent=True) or {}
        url = str(data.get("url") or "").strip().rstrip("/")
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "").strip()
        if not url or not username or not password:
            return jsonify({"success": False, "error": "url / username / password 不可為空"}), 400
        with _fb_lock:
            ok = _fb_client.configure(url, username, password)
        if not ok:
            return jsonify({"success": False, "error": "登入失敗，請確認 URL / 帳號 / 密碼"}), 401
        return jsonify({"success": True, "base_url": url, "username": username})

    @app.route("/api/fb/status")
    def fb_status():
        if not _fb_client.is_authenticated():
            return jsonify({"authenticated": False})
        info = _fb_client.get_info()
        return jsonify({"authenticated": True, "base_url": info["base_url"], "username": info["username"]})

    @app.route("/api/fb/logout", methods=["POST"])
    def fb_logout():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        _fb_client.logout()
        return jsonify({"success": True})

    @app.route("/api/fb/recordings")
    def fb_recordings():
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        try:
            recordings = _fb_client.list_recordings()
            return jsonify({"success": True, "recordings": recordings})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/fb/cache-db", methods=["POST"])
    def fb_cache_db():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        data = request.get_json(silent=True) or {}
        remote_path = str(data.get("remote_path") or "").strip()
        if not remote_path or not remote_path.endswith(".db"):
            return jsonify({"success": False, "error": "remote_path 必須是 .db 路徑"}), 400
        if ".." in remote_path or "/" in remote_path or remote_path.startswith("\\"):
            return jsonify({"success": False, "error": "不合法的路徑"}), 400
        try:
            local_path = _fb_client.download_db(remote_path, _fb_cache_dir)
            return jsonify({"success": True, "db_path": str(local_path)})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/fb/stream-video")
    def fb_stream_video():
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        remote_path = (request.args.get("path") or "").strip()
        if not remote_path or not remote_path.endswith(".mp4"):
            return jsonify({"success": False, "error": "path 必須是 .mp4 路徑"}), 400
        if ".." in remote_path or "/" in remote_path or remote_path.startswith("\\"):
            return jsonify({"success": False, "error": "不合法的路徑"}), 400
        range_header = request.headers.get("Range")
        try:
            fb_resp = _fb_client.stream_video(remote_path, range_header)
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 502

        status = fb_resp.status_code

        def _generate():
            try:
                for chunk in fb_resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        yield chunk
            finally:
                fb_resp.close()

        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
        }
        for h in ("Content-Length", "Content-Range"):
            val = fb_resp.headers.get(h)
            if val:
                headers[h] = val

        return Response(_generate(), status=status, headers=headers)

    @app.route("/api/fb/upload", methods=["POST"])
    def fb_upload():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        data = request.get_json(silent=True) or {}
        recording_name = str(data.get("recording_name") or "").strip()
        if not recording_name:
            return jsonify({"success": False, "error": "recording_name 不可為空"}), 400
        if not re.match(r'^[\w\-]+$', recording_name):
            return jsonify({"success": False, "error": "recording_name 含有不合法字元"}), 400

        rec_dir = playback_manager.recordings_dir
        db_file = rec_dir / f"{recording_name}.db"
        video_stem = recording_name.replace("metrics_", "video_", 1)
        mp4_file = next(
            (rec_dir / f"{video_stem}{ext}" for ext in (".mp4", ".avi")
             if (rec_dir / f"{video_stem}{ext}").exists()),
            None,
        )

        if not db_file.exists():
            return jsonify({"success": False, "error": f"找不到 {db_file.name}"}), 404

        uploaded = []
        errors = []

        def _emit_progress(filename: str, pct: float):
            try:
                socketio.emit("fb_upload_progress", {
                    "recording": recording_name,
                    "file": filename,
                    "progress": round(pct, 3),
                })
            except Exception:
                pass

        try:
            _fb_client.upload_file(
                db_file,
                db_file.name,
                progress_cb=lambda p: _emit_progress(db_file.name, p),
            )
            uploaded.append(db_file.name)
        except Exception as exc:
            errors.append(f"{db_file.name}: {exc}")

        if mp4_file:
            try:
                _fb_client.upload_file(
                    mp4_file,
                    mp4_file.name,
                    progress_cb=lambda p: _emit_progress(mp4_file.name, p),
                )
                uploaded.append(mp4_file.name)
            except Exception as exc:
                errors.append(f"{mp4_file.name}: {exc}")

        if errors and not uploaded:
            return jsonify({"success": False, "error": "; ".join(errors)}), 500
        return jsonify({"success": True, "uploaded": uploaded, "errors": errors})

    @app.route("/api/fb/delete", methods=["DELETE"])
    def fb_delete():
        lan_guard = _ensure_lan_endpoint_allowed()
        if lan_guard is not None:
            return lan_guard
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        data = request.get_json(silent=True) or {}
        filename = str(data.get("filename") or "").strip()
        if not filename or ".." in filename or "/" in filename or filename.startswith("\\"):
            return jsonify({"success": False, "error": "不合法的檔名"}), 400
        try:
            resp = _fb_client._request("DELETE", f"/api/resources/{filename}")
            if resp.status_code in (200, 204):
                return jsonify({"success": True})
            return jsonify({"success": False, "error": f"HTTP {resp.status_code}"}), 500
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/fb/download")
    def fb_download():
        if not _fb_client.is_authenticated():
            return jsonify({"success": False, "error": "尚未連線 File Browser"}), 401
        filename = (request.args.get("filename") or "").strip()
        if not filename or ".." in filename or "/" in filename or filename.startswith("\\"):
            return jsonify({"success": False, "error": "不合法的檔名"}), 400
        try:
            fb_resp = _fb_client._request("GET", f"/api/raw/{filename}", stream=True, timeout=300)
            fb_resp.raise_for_status()
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 502

        def _generate():
            try:
                for chunk in fb_resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        yield chunk
            finally:
                fb_resp.close()

        mime = "video/mp4" if filename.endswith(".mp4") else "application/octet-stream"
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime,
        }
        if "Content-Length" in fb_resp.headers:
            headers["Content-Length"] = fb_resp.headers["Content-Length"]
        return Response(_generate(), status=200, headers=headers)

    @socketio.on("connect")
    def handle_connect():
        sid = getattr(request, "sid", None)
        if sid is not None:
            _ws_connected_clients.add(sid)
        latest = get_latest_metrics_packet()
        if latest is not None:
            emit("metrics_update", {"metrics": latest})
        emit("connect_response", {"data": "連接成功"})

    @socketio.on("disconnect")
    def handle_disconnect():
        sid = getattr(request, "sid", None)
        if sid is not None:
            _ws_connected_clients.discard(sid)

    @socketio.on("request_metrics")
    def handle_metrics_request():
        data, latest = get_metrics_history_with_latest()
        payload: dict[str, Any] = {"data": data}
        if latest is not None:
            payload["latest"] = latest
        emit("metrics_history", payload)
        if latest is not None:
            emit("metrics_update", {"metrics": latest})

    @socketio.on("clear_buffer")
    def handle_clear_buffer():
        metrics_buffer.clear()
        emit("buffer_cleared", {"success": True})

    @app.post("/__server/shutdown")
    def shutdown_server():
        if not shutdown_token:
            abort(404)
        if not _is_local_request():
            abort(403)
        data = request.get_json(silent=True) or {}
        if not secrets.compare_digest(str(data.get("token") or ""), shutdown_token):
            abort(403)
        # threading + Werkzeug 模式下 socketio.stop() 會拋出
        # RuntimeError('Cannot stop unknown web server')，導致舊伺服器殘留。
        shutdown = request.environ.get("werkzeug.server.shutdown")
        if shutdown is None:
            return jsonify({
                "success": False,
                "error": "werkzeug shutdown unavailable",
            }), 503
        shutdown()
        return jsonify({"success": True})

    return app, socketio


class WebServerThread(threading.Thread):
    def __init__(
        self,
        metrics_buffer: MetricsBuffer,
        playback_manager: PlaybackManager,
        recording_manager: Optional[Any] = None,
        get_latest_packet: Optional[Callable] = None,
        host: str = "0.0.0.0",
        port: int = 5000,
        debug: bool = False,
    ):
        super().__init__(daemon=True, name="WebServerThread")
        self.metrics_buffer = metrics_buffer
        self.playback_manager = playback_manager
        self.recording_manager = recording_manager
        self.get_latest_packet = get_latest_packet
        self.host = host
        self.port = port
        self.debug = debug

        self._shutdown_token = secrets.token_urlsafe(32)
        self.app, self.socketio = create_app(
            metrics_buffer,
            playback_manager,
            recording_manager,
            get_latest_packet,
            shutdown_token=self._shutdown_token,
            allowed_origins=_build_allowed_origins(host, port),
        )
        self._stop_flag = threading.Event()
        self._stopped_event = threading.Event()

    def run(self) -> None:
        try:
            self.socketio.run(
                self.app,
                host=self.host,
                port=self.port,
                debug=False,
                use_reloader=False,
                allow_unsafe_werkzeug=True,
            )
        except Exception as e:
            print(f"Web服務器啟動出錯: {e}")
        finally:
            self._stopped_event.set()

    def stop(self, *, join_timeout: float = 5.0) -> bool:
        self._stop_flag.set()
        if self._stopped_event.is_set():
            return True
        try:
            import requests

            response = requests.post(
                f"http://127.0.0.1:{self.port}/__server/shutdown",
                json={"token": self._shutdown_token},
                timeout=2.0,
            )
            if response.status_code != 200:
                if not getattr(self, "_stop_err_logged", False):
                    print(
                        f"[WebServer] stop request returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                    self._stop_err_logged = True
        except Exception as e:
            if not getattr(self, "_stop_err_logged", False):
                print(f"[WebServer] stop request failed: {e}")
                self._stop_err_logged = True
        return self._stopped_event.wait(timeout=join_timeout)

    def broadcast_metrics(self, metrics: dict) -> None:
        try:
            with self.app.app_context():
                self.socketio.emit(
                    "metrics_update",
                    {"metrics": metrics},
                    namespace="/",
                )
        except Exception as e:
            if not getattr(self, '_broadcast_err_logged', False):
                print(f"[WebServer] broadcast_metrics 出錯: {e}")
                self._broadcast_err_logged = True

    @property
    def client_count(self) -> int:
        return len(_ws_connected_clients)

    def broadcast_frame(self, frame_b64: str) -> None:
        try:
            with self.app.app_context():
                self.socketio.emit(
                    "frame_update",
                    {"frame": frame_b64},
                    namespace="/",
                )
        except Exception as e:
            if not getattr(self, '_broadcast_frame_err_logged', False):
                print(f"[WebServer] broadcast_frame 出錯: {e}")
                self._broadcast_frame_err_logged = True
