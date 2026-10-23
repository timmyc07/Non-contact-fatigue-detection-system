"""File Browser API client."""
from __future__ import annotations

import logging
import hashlib
import threading
import time
import weakref
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

_REFRESH_BEFORE_SECS = 300
_HEARTBEAT_INTERVAL = 20 * 60
_TOKEN_TTL_ESTIMATE = 110 * 60


class FileBrowserClient:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = Path(cache_dir)
        self._base_url: Optional[str] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._lock = threading.RLock()
        self._download_lock = threading.Lock()
        self._closing = threading.Event()
        self._closed = threading.Event()
        self._session = requests.Session()
        self._active_streams: weakref.WeakSet[requests.Response] = weakref.WeakSet()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_threads: list[threading.Thread] = []
        self._heartbeat_stop = threading.Event()

    def configure(self, base_url: str, username: str, password: str) -> bool:
        with self._download_lock:
            self._require_open()
            self._stop_heartbeat()
            with self._lock:
                self._token = None
                self._token_expires = 0.0
                self._session.cookies.clear()
                self._base_url = base_url.rstrip("/")
                self._username = username
                self._password = password
                ok = self._do_login_locked()
            if ok:
                self._start_heartbeat()
            return ok

    def is_authenticated(self) -> bool:
        return not self.is_closing and bool(self._token and self._base_url)

    @property
    def is_closing(self) -> bool:
        return self._closing.is_set()

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    def _require_open(self) -> None:
        if self.is_closing:
            raise RuntimeError("FileBrowserClient is closed")

    def request_close(self) -> None:
        """拒絕新連線並停止 heartbeat；不等待 HTTP 或執行緒。"""
        self._closing.set()
        self._heartbeat_stop.set()

    def close(self) -> None:
        """由背景 owner 等待已發出的 HTTP，關閉所有 session 資源。"""
        self.request_close()
        with self._download_lock:
            if self.is_closed:
                return
            self._stop_heartbeat()
            for heartbeat in self._heartbeat_threads:
                heartbeat.join()
            self._heartbeat_threads.clear()
            with self._lock:
                error: Exception | None = None
                for response in list(self._active_streams):
                    try:
                        response.close()
                        self._active_streams.discard(response)
                    except Exception as exc:
                        error = error or exc
                try:
                    self._session.close()
                except Exception as exc:
                    error = error or exc
                self._token = None
                self._token_expires = 0.0
                self._base_url = None
                self._username = None
                self._password = None
                if error is not None:
                    raise error
                self._closed.set()

    def get_info(self) -> dict:
        return {
            "base_url": self._base_url,
            "username": self._username,
        }

    def logout(self) -> None:
        with self._download_lock:
            self._stop_heartbeat()
            with self._lock:
                self._token = None
                self._token_expires = 0.0
                self._base_url = None
                self._username = None
                self._password = None

    def list_recordings(self) -> list[dict]:
        resp = self._request("GET", "/api/resources/")
        resp.raise_for_status()
        items = resp.json().get("items") or []

        db_files: dict[str, dict] = {}
        mp4_files: dict[str, dict] = {}

        for item in items:
            name: str = item.get("name", "")
            if name.startswith("metrics_") and name.endswith(".db"):
                stem = name[len("metrics_") : -len(".db")]
                db_files[stem] = item
            elif name.startswith("video_") and name.endswith(".mp4"):
                stem = name[len("video_") : -len(".mp4")]
                mp4_files[stem] = item

        all_stems = sorted(set(db_files) | set(mp4_files), reverse=True)
        result = []
        for stem in all_stems:
            db = db_files.get(stem)
            mp4 = mp4_files.get(stem)
            result.append(
                {
                    "name": stem,
                    "db_path": f"metrics_{stem}.db" if db else None,
                    "mp4_path": f"video_{stem}.mp4" if mp4 else None,
                    "has_db": db is not None,
                    "has_mp4": mp4 is not None,
                    "db_size": (db or {}).get("size", 0),
                    "mp4_size": (mp4 or {}).get("size", 0),
                    "modified": (db or mp4 or {}).get("modified", ""),
                }
            )
        return result

    @staticmethod
    def _normalize_remote_path(remote_path: str) -> str:
        """接受未經 URL 編碼的 resource path；快取與 HTTP 共用此路徑。"""
        resource = PurePosixPath(remote_path.lstrip("/"))
        if not resource.parts or ".." in resource.parts or "\\" in remote_path or "\0" in remote_path:
            raise ValueError("Invalid File Browser resource path")
        return resource.as_posix()

    def _cached_db_path(self, resource_path: str) -> Path:
        namespace = hashlib.sha256(f"{self._base_url}\0{self._username}".encode()).hexdigest()
        filename = hashlib.sha256(resource_path.encode()).hexdigest() + ".db"
        return self._cache_dir / namespace / filename

    def download_db(self, remote_path: str) -> Path:
        # 下載與切換站點互斥，避免快取歸屬及同名 temporary file 競態。
        with self._download_lock:
            self._require_open()
            resource_path = self._normalize_remote_path(remote_path)
            local_path = self._cached_db_path(resource_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            if local_path.exists() and local_path.stat().st_size > 0:
                log.debug("FB cache hit: %s", local_path)
                return local_path

            log.info("FB downloading DB: %s", remote_path)
            api_path = f"/api/raw/{quote(resource_path, safe='/')}"
            resp = self._request("GET", api_path, stream=True, timeout=120)

            tmp = local_path.with_suffix(".tmp")
            try:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        self._require_open()
                        if chunk:
                            f.write(chunk)
                tmp.replace(local_path)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
            finally:
                resp.close()
            return local_path

    def stream_video(self, remote_path: str, range_header: Optional[str] = None) -> requests.Response:
        extra: dict = {}
        if range_header:
            extra["headers"] = {"Range": range_header}
        resource_path = self._normalize_remote_path(remote_path)
        api_path = f"/api/raw/{quote(resource_path, safe='/')}"
        resp = self._request("GET", api_path, stream=True, timeout=60, **extra)
        try:
            resp.raise_for_status()
        except Exception:
            resp.close()
            raise
        return resp

    def upload_file(self, local_path: Path, remote_path: str, progress_cb: Optional[Callable[[float], None]] = None) -> None:
        with self._download_lock:
            self._require_open()
            resource_path = self._normalize_remote_path(remote_path)
            local_path = Path(local_path)
            total = local_path.stat().st_size
            api_path = f"/api/resources/{quote(resource_path, safe='/')}"

            def _make_reader():
                uploaded = 0
                with open(local_path, "rb") as f:
                    while True:
                        chunk = f.read(256 * 1024)
                        if not chunk:
                            break
                        yield chunk
                        uploaded += len(chunk)
                        if progress_cb and total > 0:
                            progress_cb(uploaded / total)

            resp = self._request(
                "POST", api_path,
                data_factory=_make_reader,
                headers={"Content-Type": "application/octet-stream"},
                timeout=600,
            )
            if resp.status_code == 409:
                resp = self._request(
                    "POST", api_path + "?override=true",
                    data_factory=_make_reader,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=600,
                )
            resp.raise_for_status()
            self._cached_db_path(resource_path).unlink(missing_ok=True)

    def _do_login_locked(self) -> bool:
        if self.is_closing:
            return False
        try:
            resp = self._session.post(
                f"{self._base_url}/api/login",
                json={"username": self._username, "password": self._password},
                timeout=10,
            )
            if resp.status_code == 200:
                token = resp.text.strip().strip('"')
                self._token = token
                self._token_expires = time.time() + _TOKEN_TTL_ESTIMATE
                log.info("FileBrowser login OK (user=%s)", self._username)
                return True
            log.warning("FileBrowser login failed: HTTP %s", resp.status_code)
            return False
        except Exception as exc:
            log.warning("FileBrowser login error: %s", exc)
            return False

    def _ensure_token(self) -> None:
        if time.time() > self._token_expires - _REFRESH_BEFORE_SECS:
            with self._lock:
                if time.time() > self._token_expires - _REFRESH_BEFORE_SECS:
                    self._do_login_locked()

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {"X-Auth": self._token} if self._token else {}

    def _request(
        self, method: str, path: str, *,
        data_factory: Optional[Callable] = None, **kwargs,
    ) -> requests.Response:
        with self._lock:
            self._require_open()
            if not self._base_url:
                raise RuntimeError("FileBrowserClient: 尚未設定連線")

            existing_headers = kwargs.pop("headers", {}) or {}
            headers = {**self._auth_headers(), **existing_headers}
            kwargs.setdefault("timeout", 30)
            if data_factory is not None:
                kwargs["data"] = data_factory()

            resp = self._session.request(
                method, f"{self._base_url}{path}", headers=headers, **kwargs
            )
            if resp.status_code == 401 and self._do_login_locked():
                resp.close()
                if data_factory is not None:
                    kwargs["data"] = data_factory()
                headers = {**self._auth_headers(), **existing_headers}
                resp = self._session.request(
                    method, f"{self._base_url}{path}", headers=headers, **kwargs
                )
            if kwargs.get("stream"):
                self._active_streams.add(resp)
            return resp

    def _heartbeat_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            if not self.is_authenticated():
                break
            self._ensure_token()
            stop_event.wait(_HEARTBEAT_INTERVAL)

    def _start_heartbeat(self) -> None:
        if self.is_closing:
            return
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, args=(self._heartbeat_stop,), daemon=True,
        )
        self._heartbeat_threads = [thread for thread in self._heartbeat_threads if thread.is_alive()]
        self._heartbeat_threads.append(self._heartbeat_thread)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=1.0)
        self._heartbeat_thread = None
