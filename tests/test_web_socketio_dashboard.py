from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui import camera_stream_worker, combined_worker, fatigue_worker
from gui.main_window import MainWindow, WEB_PREVIEW_TARGET_FPS
from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread, create_app
from rppg import rppg_worker


def _event_payloads(events: Sequence[Mapping[str, Any]], name: str) -> list[Any]:
    return [event["args"][0] for event in events if event.get("name") == name]


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

    encoded = MainWindow._encode_frame_jpeg(image, max_width=160, quality=70)

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


def test_shutdown_endpoint_rejects_invalid_token(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        shutdown_token="secret-token",
    )
    client = app.test_client()
    response = client.post("/__server/shutdown", json={"token": "wrong"})
    assert response.status_code == 403


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
