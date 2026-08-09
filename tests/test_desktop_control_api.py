from __future__ import annotations

import threading
import time
from pathlib import Path

from gui.desktop_control import DesktopCommandBroker
from gui.web_server import MetricsBuffer, PlaybackManager, create_app


def test_control_state_uses_registered_handler(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    def handler(command: str, args: dict) -> dict:
        calls.append((command, args))
        return {"pipeline_running": True, "recording": False}

    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=handler,
    )

    response = app.test_client().get("/api/control/state")

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "data": {"pipeline_running": True, "recording": False},
    }
    assert calls == [("state.get", {})]


def test_control_command_forwards_name_and_args(tmp_path: Path) -> None:
    def handler(command: str, args: dict) -> dict:
        assert command == "pipeline.set"
        assert args == {"enabled": True}
        return {"pipeline_running": True}

    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=handler,
    )

    response = app.test_client().post(
        "/api/control/command",
        json={"command": "pipeline.set", "args": {"enabled": True}},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "data": {"pipeline_running": True},
    }


def test_control_command_rejects_remote_clients_even_with_dashboard_token(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=lambda command, args: {},
        access_token="dashboard-token",
    )

    response = app.test_client().post(
        "/api/control/command?token=dashboard-token",
        json={"command": "pipeline.set", "args": {"enabled": True}},
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )

    assert response.status_code == 403


def test_tauri_origin_receives_restricted_cors_headers(tmp_path: Path) -> None:
    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=lambda command, args: {},
    )

    response = app.test_client().options(
        "/api/control/command",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "http://tauri.localhost"
    assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"


def test_command_broker_executes_request_on_draining_thread() -> None:
    broker = DesktopCommandBroker(timeout_seconds=1.0)
    result: dict = {}

    def submit() -> None:
        result.update(broker.submit("pipeline.set", {"enabled": True}))

    worker = threading.Thread(target=submit)
    worker.start()
    deadline = time.monotonic() + 1.0
    while broker.pending_count == 0 and time.monotonic() < deadline:
        time.sleep(0.005)

    draining_thread = threading.get_ident()
    processed = broker.process_pending(
        lambda command, args: {
            "command": command,
            "enabled": args["enabled"],
            "thread": threading.get_ident(),
        }
    )
    worker.join(timeout=1.0)

    assert processed == 1
    assert result == {
        "command": "pipeline.set",
        "enabled": True,
        "thread": draining_thread,
    }


def test_command_broker_skips_request_that_timed_out_before_drain() -> None:
    broker = DesktopCommandBroker(timeout_seconds=0.01)
    result: dict[str, object] = {}

    def submit() -> None:
        try:
            broker.submit("pipeline.set", {"enabled": True})
        except TimeoutError as exc:
            result["error"] = str(exc)

    worker = threading.Thread(target=submit)
    worker.start()
    worker.join(timeout=1)

    calls: list[str] = []
    processed = broker.process_pending(lambda command, args: calls.append(command) or {})

    assert processed == 1
    assert calls == []
    assert "timed out" in str(result["error"])
