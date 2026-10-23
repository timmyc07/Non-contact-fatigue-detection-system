from __future__ import annotations

import base64
import json
import queue
import socket
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest
import requests
import simple_websocket
import socketio as socketio_client

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui import camera_stream_worker, combined_worker, fatigue_worker
from gui.main_window import EngineApplication, WEB_PREVIEW_TARGET_FPS
from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread, create_app
from rppg import rppg_worker


def _event_payloads(events: Sequence[Mapping[str, Any]], name: str) -> list[Any]:
    return [event["args"][0] for event in events if event.get("name") == name]


def _acknowledge_received(socketio, client):
    # Flask-SocketIO test_client 不實作 server→client ACK，明確模擬已消費事件。
    manager = socketio.server.manager
    sid = manager.sid_from_eio_sid(client.eio_sid, "/")
    for callback_id in list(manager.callbacks.get(sid, {})):
        if callback_id != 0:
            manager.trigger_callback(sid, callback_id, [])


def test_socketio_connect_emits_connect_response(tmp_path: Path) -> None:
    app, socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))

    client = socketio.test_client(app)

    try:
        assert client.is_connected()
        events = client.get_received()
        assert _event_payloads(events, "connect_response")
    finally:
        client.disconnect()


def test_socketio_connect_emits_latest_metrics_update_when_callback_available(tmp_path: Path) -> None:
    latest = {"timestamp": 2.0, "pipeline_running": True, "stress_bpm": 72.0}
    app, socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        get_latest_packet=lambda: latest,
    )

    client = socketio.test_client(app)

    try:
        events = client.get_received()
        updates = _event_payloads(events, "metrics_update")
        assert _event_payloads(events, "connect_response")
        assert updates[0]["metrics"] == latest
    finally:
        client.disconnect()


def test_socketio_request_metrics_returns_buffer_history_without_latest(tmp_path: Path) -> None:
    buffer = MetricsBuffer()
    first = {"timestamp": 1.0, "pipeline_running": True}
    second = {"timestamp": 2.0, "pipeline_running": True}
    buffer.append(first)
    buffer.append(second)
    app, socketio = create_app(buffer, PlaybackManager(tmp_path))
    client = socketio.test_client(app)

    try:
        client.get_received()
        client.emit("request_metrics")
        events = client.get_received()
        histories = _event_payloads(events, "metrics_history")
        updates = _event_payloads(events, "metrics_update")
        assert histories[0]["data"] == [first, second]
        assert "latest" not in histories[0]
        assert updates == []
    finally:
        client.disconnect()


def test_socketio_request_metrics_appends_latest_and_rebroadcasts_latest(tmp_path: Path) -> None:
    buffer = MetricsBuffer()
    old = {"timestamp": 1.0, "pipeline_running": True, "stress_bpm": 65.0}
    latest = {"timestamp": 2.0, "pipeline_running": True, "stress_bpm": 72.0}
    buffer.append(old)
    app, socketio = create_app(
        buffer,
        PlaybackManager(tmp_path),
        get_latest_packet=lambda: latest,
    )
    client = socketio.test_client(app)

    try:
        client.get_received()
        _acknowledge_received(socketio, client)
        client.emit("request_metrics")
        events = client.get_received()
        histories = _event_payloads(events, "metrics_history")
        updates = _event_payloads(events, "metrics_update")
        assert histories[0]["data"] == [old, latest]
        assert histories[0]["latest"] == latest
        assert updates[0]["metrics"] == latest
    finally:
        client.disconnect()


def test_socketio_request_metrics_does_not_duplicate_current_latest(tmp_path: Path) -> None:
    buffer = MetricsBuffer()
    latest = {"timestamp": 2.0, "pipeline_running": True, "stress_bpm": 72.0}
    buffer.append(latest)
    app, socketio = create_app(
        buffer,
        PlaybackManager(tmp_path),
        get_latest_packet=lambda: latest,
    )
    client = socketio.test_client(app)

    try:
        client.get_received()
        _acknowledge_received(socketio, client)
        client.emit("request_metrics")
        events = client.get_received()
        histories = _event_payloads(events, "metrics_history")
        assert histories[0]["data"] == [latest]
        assert histories[0]["latest"] == latest
    finally:
        client.disconnect()


def test_socketio_latest_packet_callback_error_keeps_request_metrics_alive(tmp_path: Path) -> None:
    buffer = MetricsBuffer()
    first = {"timestamp": 1.0, "pipeline_running": True}
    buffer.append(first)

    def raise_error() -> dict:
        raise RuntimeError("latest unavailable")

    app, socketio = create_app(
        buffer,
        PlaybackManager(tmp_path),
        get_latest_packet=raise_error,
    )
    client = socketio.test_client(app)

    try:
        client.get_received()
        client.emit("request_metrics")
        events = client.get_received()
        histories = _event_payloads(events, "metrics_history")
        updates = _event_payloads(events, "metrics_update")
        assert histories[0]["data"] == [first]
        assert "latest" not in histories[0]
        assert updates == []
    finally:
        client.disconnect()


def test_web_preview_frame_encoder_returns_jpeg_base64() -> None:
    image = QImage(320, 240, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)

    encoded = EngineApplication._encode_frame_jpeg(image, max_width=160, quality=70)

    assert encoded is not None
    raw = base64.b64decode(encoded)
    assert raw.startswith(b"\xff\xd8")
    assert raw.endswith(b"\xff\xd9")


def test_socketio_broadcast_frame_event_reaches_client(tmp_path: Path) -> None:
    # 顯式綁定 127.0.0.1：此測試驗證 broadcast_frame 行為，與 LAN token 機制無關；
    # 預設 host="0.0.0.0" 會觸發自動產生 access token，導致無 token 的 test_client 連線被拒。
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1")
    client = server.socketio.test_client(server.app)

    try:
        client.get_received()
        server.broadcast_frame("jpeg-base64")
        events = client.get_received()
        frames = _event_payloads(events, "frame_update")
        assert frames == [{"frame": "jpeg-base64"}]
    finally:
        client.disconnect()


def test_slow_socket_client_keeps_only_inflight_and_latest_per_event(tmp_path, monkeypatch):
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1")
    callbacks = {"frame_update": [], "metrics_update": []}
    original = server.socketio.emit

    def emit(event, data, **kwargs):
        if event in callbacks and kwargs.get("callback"):
            callbacks[event].append(kwargs["callback"])
        original(event, data, **kwargs)

    monkeypatch.setattr(server.socketio, "emit", emit)
    slow = server.socketio.test_client(server.app)
    fast = server.socketio.test_client(server.app)
    try:
        slow.get_received()
        fast.get_received()
        for index in range(1000):
            server.broadcast_frame(f"frame-{index}")
            server.broadcast_metrics({"timestamp": index})
            fast_events = fast.get_received()
            assert _event_payloads(fast_events, "frame_update") == [{"frame": f"frame-{index}"}]
            assert _event_payloads(fast_events, "metrics_update") == [{"metrics": {"timestamp": index}}]
            _acknowledge_received(server.socketio, fast)
        events = slow.get_received()
        assert _event_payloads(events, "frame_update") == [{"frame": "frame-0"}]
        assert _event_payloads(events, "metrics_update") == [{"metrics": {"timestamp": 0}}]
        slow.emit("request_metrics")
        assert _event_payloads(slow.get_received(), "metrics_history") == [{"data": []}]
        _acknowledge_received(server.socketio, slow)
        latest = slow.get_received()
        assert _event_payloads(latest, "frame_update") == [{"frame": "frame-999"}]
        assert _event_payloads(latest, "metrics_update") == [{"metrics": {"timestamp": 999}}]
        assert len(server.app.extensions["ncfd_stream_publisher"]._pending) == 2
        slow.disconnect()
        fast.disconnect()
        for callback in callbacks["frame_update"]:
            callback()
        assert server.client_count == 0
        assert not server.app.extensions["ncfd_stream_publisher"]._pending
    finally:
        if slow.is_connected():
            slow.disconnect()
        if fast.is_connected():
            fast.disconnect()


def test_preview_skips_encoding_without_clients_and_sends_first_client_frame(monkeypatch):
    encoded = []
    delivered = []
    server = SimpleNamespace(client_count=0, broadcast_frame=delivered.append)
    application = SimpleNamespace(
        _web_server=server, _web_last_frame_emit=0.0, _web_frame_interval=0.1,
        _encode_frame_jpeg=lambda image: encoded.append(image) or "jpeg",
    )
    monkeypatch.setattr(time, "perf_counter", lambda: 1.0)
    image = object()
    EngineApplication._emit_web_frame(application, image)
    assert encoded == []
    assert application._web_last_frame_emit == 0.0
    server.client_count = 1
    EngineApplication._emit_web_frame(application, image)
    assert encoded == [image]
    assert delivered == ["jpeg"]
    assert application._web_last_frame_emit == 1.0


def test_real_client_ack_receives_initial_snapshot_and_continues_streaming(tmp_path):
    latest = [{"timestamp": 1.0}]
    server = WebServerThread(
        MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0,
        get_latest_packet=lambda: latest[0],
    )
    metrics = queue.Queue()
    frames = queue.Queue()
    histories = queue.Queue()
    with requests.Session() as session:
        client = socketio_client.Client(http_session=session, reconnection=False, request_timeout=2)
        client.on("metrics_update", metrics.put)
        client.on("frame_update", frames.put)
        client.on("metrics_history", histories.put)
        server.start()
        try:
            deadline = time.monotonic() + 3.0
            while server.port == 0 and server.is_alive() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert server.port != 0
            client.connect(f"http://127.0.0.1:{server.port}", transports=["polling"], wait_timeout=2)
            assert metrics.get(timeout=2) == {"metrics": {"timestamp": 1.0}}
            latest[0] = {"timestamp": 2.0}
            server.broadcast_metrics(latest[0])
            assert metrics.get(timeout=2) == {"metrics": {"timestamp": 2.0}}
            for frame in ("first-jpeg", "second-jpeg"):
                server.broadcast_frame(frame)
                assert frames.get(timeout=2) == {"frame": frame}
            client.emit("request_metrics")
            assert histories.get(timeout=2)["latest"] == {"timestamp": 2.0}
            assert metrics.get(timeout=2) == {"metrics": {"timestamp": 2.0}}
        finally:
            server.stop(join_timeout=3)
            if client.connected:
                client.disconnect()
            server.join(timeout=3)
    assert server.client_count == 0
    assert not server.app.extensions["ncfd_stream_publisher"]._pending


def test_server_stop_closes_websocket_and_half_open_polling_and_releases_port(tmp_path):
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    server.start()
    deadline = time.monotonic() + 3.0
    while server.port == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.port != 0
    base = f"http://127.0.0.1:{server.port}"
    ws = None
    try:
        polling = requests.get(base + "/socket.io/?EIO=4&transport=polling", timeout=2)
        assert polling.status_code == 200
        ws = simple_websocket.Client.connect(base.replace("http:", "ws:") + "/socket.io/?EIO=4&transport=websocket")
        assert ws.receive(timeout=2).startswith("0")
        ws.send("40")
        ws.send('42["request_metrics"]')
        events = [ws.receive(timeout=2) for _ in range(3)]
        assert any("metrics_history" in event for event in events)
        assert len(server.socketio.server.eio.sockets) == 2
        assert server.stop(join_timeout=2)
        server.join(timeout=2)
        assert not server.is_alive()
        assert not server.socketio.server.eio.sockets
        with pytest.raises(simple_websocket.ConnectionClosed):
            ws.receive(timeout=2)
    finally:
        if ws is not None and ws.connected:
            ws.close()
        server.stop(join_timeout=2)
    replacement = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=server.port)
    replacement.start()
    try:
        assert requests.get(base + "/api/metrics", timeout=2).status_code == 200
    finally:
        assert replacement.stop(join_timeout=2)


def test_request_completed_after_stop_cannot_create_engineio_session(tmp_path):
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    server.start()
    deadline = time.monotonic() + 3
    while server.port == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    with socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection:
        connection.sendall(b"GET /socket.io/?EIO=4&transport=polling HTTP/1.1\r\n")
        time.sleep(0.05)
        assert server.stop(join_timeout=2)
        connection.sendall(b"Host: localhost\r\n\r\n")
        assert b"503" in connection.recv(4096).split(b"\r\n", 1)[0]
        assert not server.socketio.server.eio.sockets


@pytest.mark.parametrize("host,origin,status", [
    ("evil.example:5055", "http://evil.example:5055", 403),
    ("127.0.0.1:5055", "http://evil.example", 403),
    ("127.0.0.1:5055", None, 200),
    ("[::1]:5055", "http://[::1]:5055", 200),
    ("localhost:5055", "http://localhost:5055", 200),
    *(("127.0.0.1:5055", origin, 200) for origin in (
        "http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost",
        "http://tauri.localhost", "https://tauri.localhost",
    )),
])
def test_sensitive_endpoints_validate_host_and_origin(tmp_path, host, origin, status):
    called = []
    app, _ = create_app(MetricsBuffer(), PlaybackManager(tmp_path), control_handler=lambda *args: called.append(args) or {})
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    response = app.test_client().post(
        "/api/control/command", json={"command": "app.shutdown", "args": {}},
        headers=headers, environ_overrides={"REMOTE_ADDR": "::ffff:127.0.0.1"},
    )
    assert response.status_code == status
    assert bool(called) is (status == 200)


def test_upload_database_snapshot_includes_committed_wal(tmp_path, monkeypatch):
    import sqlite3
    from gui import web_server

    captured = []

    class FakeFileBrowser:
        def is_authenticated(self):
            return True

        def upload_file(self, path, name, **kwargs):
            with sqlite3.connect(path) as conn:
                assert conn.execute("SELECT bpm FROM metrics").fetchall() == [(72.0,)]
            captured.append((path, name))

    monkeypatch.setattr(web_server, "FileBrowserClient", FakeFileBrowser)
    db_path = tmp_path / "metrics_session.db"
    source = sqlite3.connect(db_path)
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE metrics (bpm REAL)")
        source.execute("INSERT INTO metrics VALUES (72)")
        source.commit()
        assert Path(str(db_path) + "-wal").exists()
        app, _ = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
        response = app.test_client().post("/api/fb/upload", json={"recording_name": "metrics_session"})
        assert response.status_code == 200
        assert response.json["uploaded"] == [db_path.name]
        assert len(captured) == 1
        assert captured[0][1] == db_path.name
        assert not captured[0][0].exists()
    finally:
        source.close()


@pytest.mark.parametrize("failure", [False, True])
def test_upload_progress_is_bounded_per_client_and_http_keeps_final_result(tmp_path, monkeypatch, failure):
    import sqlite3
    from gui import web_server

    with sqlite3.connect(tmp_path / "metrics_session.db") as conn:
        conn.execute("CREATE TABLE metrics (timestamp REAL)")
        conn.execute("INSERT INTO metrics VALUES (1)")
    fast = None
    fast_progress = []

    class FakeFileBrowser:
        def is_authenticated(self):
            return True

        def upload_file(self, path, name, progress_cb):
            for index in range(10000):
                progress_cb((index + 1) / 10000)
                fast_progress.extend(_event_payloads(fast.get_received(), "fb_upload_progress"))
                _acknowledge_received(socketio, fast)
            if failure:
                raise RuntimeError("synthetic upload failed")

    monkeypatch.setattr(web_server, "FileBrowserClient", FakeFileBrowser)
    app, socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    slow = socketio.test_client(app)
    fast = socketio.test_client(app)
    publisher = app.extensions["ncfd_stream_publisher"]
    slow.get_received()
    fast.get_received()
    try:
        response = app.test_client().post("/api/fb/upload", json={"recording_name": "metrics_session"})
        if failure:
            assert response.status_code == 500
            assert response.json["success"] is False
            assert "synthetic upload failed" in response.json["error"]
        else:
            assert response.status_code == 200
            assert response.json == {"success": True, "uploaded": ["metrics_session.db"], "errors": []}
        assert len(fast_progress) == 10000
        assert fast_progress[-1]["progress"] == 1.0
        first = _event_payloads(slow.get_received(), "fb_upload_progress")
        assert len(first) == 1
        assert first[0]["progress"] == 0.0
        assert len(publisher._pending) == 1
        _acknowledge_received(socketio, slow)
        latest = _event_payloads(slow.get_received(), "fb_upload_progress")
        assert latest == [{"recording": "metrics_session", "file": "metrics_session.db", "progress": 1.0}]
        _acknowledge_received(socketio, slow)
        assert not publisher._pending
    finally:
        slow.disconnect()
        fast.disconnect()
    assert not publisher._pending


@pytest.mark.parametrize("flag", ["recording", "recording_finalizing"])
def test_upload_waits_until_video_finalization_finishes(tmp_path, monkeypatch, flag):
    from types import SimpleNamespace
    from gui import web_server

    monkeypatch.setattr(web_server, "FileBrowserClient", lambda: SimpleNamespace(is_authenticated=lambda: True))
    app, _ = create_app(MetricsBuffer(), PlaybackManager(tmp_path), get_latest_packet=lambda: {flag: True})
    response = app.test_client().post("/api/fb/upload", json={"recording_name": "metrics_session"})
    assert response.status_code == 409
    assert "停止錄製" in response.json["error"]


# ── LAN 模式 shared-token 認證 ──
#
# app.test_client() 預設 REMOTE_ADDR 為 127.0.0.1（本機），因此以
# environ_overrides 覆寫為區網位址，模擬「LAN 綁定 + 非本機來源」的請求。

def test_lan_api_request_without_token_returns_401(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = app.test_client()
    response = client.get(
        "/api/recordings",
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert response.status_code == 401


def test_lan_api_request_with_query_token_returns_200(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = app.test_client()
    response = client.get(
        "/api/recordings?token=secret-lan-token",
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert response.status_code == 200


def test_lan_api_request_with_header_token_returns_200(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = app.test_client()
    response = client.get(
        "/api/recordings",
        headers={"X-Dashboard-Token": "secret-lan-token"},
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert response.status_code == 200


def test_lan_homepage_requires_token(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = app.test_client()
    response = client.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert response.status_code == 401


def test_lan_diagnostics_with_token_returns_json_without_template(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(), PlaybackManager(tmp_path), access_token="secret-lan-token"
    )
    response = app.test_client().get(
        "/?token=secret-lan-token",
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert response.status_code == 200
    assert response.is_json
    assert response.json["metrics_url"] == "/api/metrics"


def test_local_request_bypasses_token_even_when_lan_token_set(tmp_path: Path) -> None:
    """127.0.0.1 來源一律免 token，維持單機模式零改變。"""
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = app.test_client()
    response = client.get("/api/recordings")  # 預設 REMOTE_ADDR=127.0.0.1
    assert response.status_code == 200


def test_no_access_token_leaves_single_machine_mode_unaffected(tmp_path: Path) -> None:
    """未設定 access_token（單機模式）時，即使來源非本機也不需要 token。"""
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    client = app.test_client()
    response = client.get(
        "/api/recordings",
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert response.status_code == 200


def test_socketio_connect_rejected_without_token_when_lan_enabled(tmp_path: Path) -> None:
    app, socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = socketio.test_client(app)
    try:
        assert not client.is_connected()
    finally:
        if client.is_connected():
            client.disconnect()


def test_socketio_connect_accepted_with_correct_auth_token(tmp_path: Path) -> None:
    app, socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        access_token="secret-lan-token",
    )
    client = socketio.test_client(app, auth={"token": "secret-lan-token"})
    try:
        assert client.is_connected()
    finally:
        client.disconnect()


def test_web_server_thread_generates_access_token_for_lan_bind(tmp_path: Path) -> None:
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="0.0.0.0")
    assert server.access_token
    assert len(server.access_token) >= 16


def test_web_server_thread_no_access_token_for_localhost_bind(tmp_path: Path) -> None:
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1")
    assert server.access_token is None


def test_live_web_preview_targets_thirty_fps() -> None:
    assert WEB_PREVIEW_TARGET_FPS == 30.0
    assert camera_stream_worker._PREVIEW_MAX_FPS == 30.0
    assert combined_worker._ANNOTATED_PREVIEW_MAX_FPS == 30.0
    assert fatigue_worker._ANNOTATED_PREVIEW_MAX_FPS == 30.0
    assert rppg_worker._ANNOTATED_PREVIEW_MAX_FPS == 30.0
