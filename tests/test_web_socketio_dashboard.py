from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui.main_window import MainWindow
from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread, create_app


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
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path))
    client = server.socketio.test_client(server.app)

    try:
        client.get_received()
        server.broadcast_frame("jpeg-base64")
        events = client.get_received()
        frames = _event_payloads(events, "frame_update")
        assert frames == [{"frame": "jpeg-base64"}]
    finally:
        client.disconnect()
