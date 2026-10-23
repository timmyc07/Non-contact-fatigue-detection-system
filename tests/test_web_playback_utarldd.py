from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import requests
from werkzeug.http import parse_options_header

from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread, create_app, format_web_dashboard_urls


def _write_minimal_metrics_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                fps REAL,
                status TEXT,
                fatigue_level REAL
            )
            """
        )
        conn.execute("INSERT INTO metrics (timestamp, fps, status, fatigue_level) VALUES (0.0, 30.0, 'OK', 0.1)")
        conn.execute("INSERT INTO metrics (timestamp, fps, status, fatigue_level) VALUES (1.0, 30.0, 'DROWSY', 0.8)")


@pytest.mark.parametrize("endpoint", ["/api/playback", "/api/playback/full", "/api/recordings"])
@pytest.mark.parametrize("valid_schema", [True, False])
def test_playback_connections_close_after_success_and_query_error(tmp_path, monkeypatch, endpoint, valid_schema):
    db_path = tmp_path / "metrics_20260101_010101.db"
    if valid_schema:
        _write_minimal_metrics_db(db_path)
    else:
        db_path.touch()
    connections = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    app, _ = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    app.test_client().get(endpoint, query_string={"db_path": str(db_path)})
    try:
        assert connections
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()


def test_file_browser_download_closes_upstream_after_http_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gui import web_server

    response = requests.Response()
    response.status_code = 500
    response._content_consumed = True
    closed = []
    monkeypatch.setattr(response, "close", lambda: closed.append(True))
    monkeypatch.setattr(web_server, "FileBrowserClient", lambda _cache_dir: SimpleNamespace(
        is_authenticated=lambda: True,
        _normalize_remote_path=lambda path: path,
        _request=lambda *args, **kwargs: response,
    ))
    app, _ = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    result = app.test_client().get("/api/fb/download", query_string={"filename": "metrics_test.db"})
    assert result.status_code == 502
    assert closed == [True]


@pytest.mark.parametrize("operation", ["stream-video", "download", "delete"])
def test_file_browser_resource_operations_keep_uploaded_raw_filename(tmp_path, monkeypatch, operation):
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    browser = app.extensions["ncfd_file_browser_client"]
    browser._base_url = "https://file-browser.invalid"
    browser._username = "user"
    browser._token = "synthetic-token"
    browser._token_expires = float("inf")
    filename = "影片 %?#.mp4"
    stored = {}
    calls = []

    def request(method, url, **kwargs):
        parsed = urlsplit(url)
        assert not parsed.query and not parsed.fragment
        resource = unquote(parsed.path.split("/", 3)[3])
        calls.append((method, resource))
        if method == "POST":
            stored[resource] = b"".join(kwargs["data"])
        body = stored[resource]
        if method == "DELETE":
            del stored[resource]
        response = requests.Response()
        response.status_code = 204 if method == "DELETE" else 200
        response._content_consumed = True
        monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([body]))
        return response

    monkeypatch.setattr(browser._session, "request", request)
    source = tmp_path / "upload.mp4"
    source.write_bytes(b"uploaded video")
    try:
        browser.upload_file(source, filename)
        if operation == "delete":
            result = app.test_client().delete("/api/fb/delete", json={"filename": filename})
            assert result.json == {"success": True}
            assert not stored
        else:
            argument = "path" if operation == "stream-video" else "filename"
            result = app.test_client().get(f"/api/fb/{operation}", query_string={argument: filename})
            assert result.data == b"uploaded video"
        assert result.status_code == 200
        assert calls == [("POST", filename), ("DELETE" if operation == "delete" else "GET", filename)]
    finally:
        browser.close()


@pytest.mark.parametrize("filename", ["影片 %?#.mp4", 'quoted"percent%20?#.mp4', "line\r\nX-Injected: yes.mp4"])
def test_file_browser_download_filename_is_safe_on_real_http_wire(tmp_path, monkeypatch, filename):
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    browser = server.app.extensions["ncfd_file_browser_client"]
    browser._base_url = "https://file-browser.invalid"
    browser._token = "synthetic-token"
    browser._token_expires = float("inf")
    body = b"downloaded video"

    def request(_method, url, **kwargs):
        parsed = urlsplit(url)
        assert not parsed.query and not parsed.fragment
        assert unquote(parsed.path.split("/", 3)[3]) == filename
        response = requests.Response()
        response.status_code = 200
        response._content_consumed = True
        response.headers["Content-Length"] = str(len(body))
        monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([body]))
        return response

    monkeypatch.setattr(browser._session, "request", request)
    server.start()
    try:
        deadline = time.monotonic() + 2.0
        while server.port == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert server.port != 0
        with requests.get(
            f"http://127.0.0.1:{server.port}/api/fb/download",
            params={"filename": filename}, timeout=0.5,
        ) as response:
            assert response.status_code == 200
            assert response.content == body
            disposition = response.headers["Content-Disposition"]
            assert disposition.isascii()
            assert "\r" not in disposition and "\n" not in disposition
            assert "X-Injected" not in response.headers
            value, options = parse_options_header(disposition)
            assert value == "attachment"
            assert options["filename"] == filename
    finally:
        assert server.stop(join_timeout=3.0)
        server.join(timeout=3.0)
        assert not server.is_alive()


@pytest.mark.parametrize("run_dir", ["utarldd_runs", "replay_runs"])
def test_playback_manager_lists_nested_replay_recordings(tmp_path: Path, run_dir: str) -> None:
    db_path = tmp_path / run_dir / "run1" / "metrics_replay_01_0_20260606_010203.db"
    _write_minimal_metrics_db(db_path)

    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()

    assert len(recordings) == 1
    assert recordings[0]["filename"] == f"{run_dir}/run1/{db_path.name}"
    assert recordings[0]["path"] == str(db_path)
    assert recordings[0]["record_count"] == 2


@pytest.mark.parametrize("run_dir", ["utarldd_runs", "replay_runs"])
def test_playback_api_reads_nested_replay_db(tmp_path: Path, run_dir: str) -> None:
    db_path = tmp_path / run_dir / "run1" / "metrics_replay_01_10_20260606_010203.db"
    _write_minimal_metrics_db(db_path)
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))

    client = app.test_client()
    recordings_resp = client.get("/api/recordings")
    playback_resp = client.get("/api/playback/full", query_string={"db_path": str(db_path)})

    recordings_json = recordings_resp.get_json()
    playback_json = playback_resp.get_json()
    assert recordings_json["success"] is True
    assert recordings_json["data"][0]["filename"].startswith(f"{run_dir}/")
    assert playback_json["success"] is True
    assert playback_json["total"] == 2
    assert playback_json["data"][1]["status"] == "DROWSY"


def test_generic_labeled_and_root_recordings_coexist_with_sidecar_and_cache_refresh(tmp_path: Path):
    paths = [
        tmp_path / "metrics_root.db",
        tmp_path / "utarldd_runs" / "run1" / "metrics_labeled.db",
        tmp_path / "replay_runs" / "run1" / "metrics_generic.db",
    ]
    for path in paths:
        _write_minimal_metrics_db(path)
    generic = paths[-1]
    generic.with_name(generic.name + ".meta.json").write_text(json.dumps({
        "schema_version": 1, "rows": 42, "ts_min": 10.0, "ts_max": 99.0,
    }), encoding="utf-8")
    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()
    assert {entry["filename"] for entry in recordings} == {
        path.relative_to(tmp_path).as_posix() for path in paths
    }
    assert next(entry for entry in recordings if entry["path"] == str(generic))["record_count"] == 42
    previous_marker = manager._recordings_cache_mtime
    new = tmp_path / "replay_runs" / "run2" / "metrics_new.db"
    _write_minimal_metrics_db(new)
    os.utime(new, (previous_marker - 10, previous_marker - 10))
    os.utime(new.parent.parent, (previous_marker + 10, previous_marker + 10))
    assert len(manager.list_recordings()) == 4


def _write_paged_metrics_db(path: Path, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                fps REAL,
                status TEXT,
                fatigue_level REAL
            )
            """
        )
        for i in range(row_count):
            conn.execute(
                "INSERT INTO metrics (timestamp, fps, status, fatigue_level) VALUES (?, 30.0, ?, 0.1)",
                (float(i), f"S{i}"),
            )


def test_playback_full_paginates_with_offset_and_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics_paged.db"
    _write_paged_metrics_db(db_path, 5)

    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    client = app.test_client()

    first = client.get(
        "/api/playback/full", query_string={"db_path": str(db_path), "offset": 0, "limit": 2}
    ).get_json()
    assert first["success"] is True
    assert first["total"] == 5
    assert first["offset"] == 0
    assert first["limit"] == 2
    assert [d["status"] for d in first["data"]] == ["S0", "S1"]

    second = client.get(
        "/api/playback/full", query_string={"db_path": str(db_path), "offset": 2, "limit": 2}
    ).get_json()
    assert [d["status"] for d in second["data"]] == ["S2", "S3"]

    third = client.get(
        "/api/playback/full", query_string={"db_path": str(db_path), "offset": 4, "limit": 2}
    ).get_json()
    assert third["total"] == 5
    assert [d["status"] for d in third["data"]] == ["S4"]


def test_playback_full_without_params_returns_all_rows_under_default_limit(tmp_path: Path) -> None:
    # 無 offset/limit 參數時，行數在預設 limit（2000）以下應與改動前一樣一次拿到全部資料，
    # 對既有不帶參數呼叫端維持向後相容。
    db_path = tmp_path / "metrics_small.db"
    _write_paged_metrics_db(db_path, 5)

    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    client = app.test_client()

    resp = client.get("/api/playback/full", query_string={"db_path": str(db_path)}).get_json()
    assert resp["success"] is True
    assert resp["total"] == 5
    assert resp["offset"] == 0
    assert len(resp["data"]) == 5


def test_playback_full_rejects_limit_over_max(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics_over_limit.db"
    _write_minimal_metrics_db(db_path)
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    client = app.test_client()

    resp = client.get(
        "/api/playback/full", query_string={"db_path": str(db_path), "limit": 999999}
    )
    assert resp.status_code == 400


def test_list_recordings_prefers_sidecar_meta_when_fresh(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics_20260101_010101.db"
    _write_minimal_metrics_db(db_path)  # 實際 SQL 掃描應得 record_count=2
    meta_path = db_path.with_name(db_path.name + ".meta.json")
    meta_path.write_text(
        json.dumps({"schema_version": 1, "rows": 42, "ts_min": 10.0, "ts_max": 99.0}),
        encoding="utf-8",
    )
    db_mtime = db_path.stat().st_mtime
    os.utime(meta_path, (db_mtime + 5, db_mtime + 5))  # 確保 sidecar 不早於 db

    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()

    assert len(recordings) == 1
    # 命中 sidecar：採用 sidecar 的 rows/ts_min/ts_max，而非 SQL 掃描出的 2 筆
    assert recordings[0]["record_count"] == 42
    assert recordings[0]["duration_sec"] == 89.0


def test_list_recordings_falls_back_to_sql_when_sidecar_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics_20260101_020202.db"
    _write_minimal_metrics_db(db_path)  # 2 筆，無 sidecar

    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()

    assert len(recordings) == 1
    assert recordings[0]["record_count"] == 2


def test_list_recordings_falls_back_to_sql_when_sidecar_stale(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics_20260101_030303.db"
    _write_minimal_metrics_db(db_path)  # 2 筆
    meta_path = db_path.with_name(db_path.name + ".meta.json")
    meta_path.write_text(
        json.dumps({"schema_version": 1, "rows": 999, "ts_min": 0.0, "ts_max": 1.0}),
        encoding="utf-8",
    )
    # 讓 sidecar 明顯早於 db（模擬 db 之後又被寫入、sidecar 過期未更新）
    meta_mtime = meta_path.stat().st_mtime
    os.utime(db_path, (meta_mtime + 5, meta_mtime + 5))

    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()

    assert len(recordings) == 1
    assert recordings[0]["record_count"] == 2  # 過期 sidecar 被忽略，回退 SQL 掃描


def test_format_web_dashboard_urls_local_only() -> None:
    urls = format_web_dashboard_urls(5000, allow_lan=False)
    assert urls == ["http://127.0.0.1:5000"]


def test_format_web_dashboard_urls_with_lan_includes_localhost() -> None:
    urls = format_web_dashboard_urls(5000, allow_lan=True)
    assert urls[0] == "http://127.0.0.1:5000"
    for url in urls[1:]:
        assert url.startswith("http://")
        assert ":5000" in url
        assert "127.0.0.1" not in url
