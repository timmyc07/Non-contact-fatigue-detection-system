"""File Browser API client."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)

_REFRESH_BEFORE_SECS = 300
_HEARTBEAT_INTERVAL = 20 * 60
_TOKEN_TTL_ESTIMATE = 110 * 60


class FileBrowserClient:
    def __init__(self) -> None:
        self._base_url: Optional[str] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()

    def configure(self, base_url: str, username: str, password: str) -> bool:
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
        return bool(self._token and self._base_url)

    def get_info(self) -> dict:
        return {
            "base_url": self._base_url,
            "username": self._username,
        }

    def logout(self) -> None:
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

    def download_db(self, remote_path: str, cache_dir: Path) -> Path:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(remote_path).name
        local_path = cache_dir / filename

        if local_path.exists() and local_path.stat().st_size > 0:
            log.debug("FB cache hit: %s", local_path)
            return local_path

        log.info("FB downloading DB: %s", remote_path)
        api_path = f"/api/raw/{remote_path.lstrip('/')}"
        resp = self._request("GET", api_path, stream=True, timeout=120)
        resp.raise_for_status()

        tmp = local_path.with_suffix(".tmp")
        try:
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.replace(local_path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return local_path

    def stream_video(self, remote_path: str, range_header: Optional[str] = None) -> requests.Response:
        extra: dict = {}
        if range_header:
            extra["headers"] = {"Range": range_header}
        api_path = f"/api/raw/{remote_path.lstrip('/')}"
        resp = self._request("GET", api_path, stream=True, timeout=60, **extra)
        resp.raise_for_status()
        return resp

    def upload_file(self, local_path: Path, remote_path: str, progress_cb: Optional[Callable[[float], None]] = None) -> None:
        local_path = Path(local_path)
        total = local_path.stat().st_size
        api_path = f"/api/resources/{remote_path.lstrip('/')}"

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

    def _do_login_locked(self) -> bool:
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
        if resp.status_code == 401:
            with self._lock:
                if self._do_login_locked():
                    resp.close()
                    if data_factory is not None:
                        kwargs["data"] = data_factory()
                    headers = {**self._auth_headers(), **existing_headers}
                    resp = self._session.request(
                        method, f"{self._base_url}{path}", headers=headers, **kwargs
                    )
        return resp

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.is_set():
            if not self.is_authenticated():
                break
            self._ensure_token()
            self._heartbeat_stop.wait(_HEARTBEAT_INTERVAL)

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=1.0)
        self._heartbeat_thread = None
