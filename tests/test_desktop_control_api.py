from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from gui.desktop_control import (
    BusyError,
    DesktopCommandBroker,
    SettingsWriteError,
    desktop_dialog_parent,
)
from gui.web_server import MetricsBuffer, PlaybackManager, create_app


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_api_version_matches_all_consumers() -> None:
    rust_source = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    client_source = (ROOT / "scripts" / "desktop_engine_client.py").read_text(
        encoding="utf-8"
    )

    assert "const DESKTOP_CONTROL_API_VERSION: u64 = 2;" in rust_source
    assert "DESKTOP_API_VERSION = 2" in client_source


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


def test_control_command_reports_settings_write_error(tmp_path: Path) -> None:
    def handler(command: str, args: dict) -> dict:
        raise SettingsWriteError(
            "Unable to write settings file C:/app/settings.json: access denied",
            path="C:/app/settings.json",
        )

    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=handler,
    )

    response = app.test_client().post(
        "/api/control/command",
        json={"command": "settings.save", "args": {}},
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "error": {
            "code": "settings_write_failed",
            "message": "Unable to write settings file C:/app/settings.json: access denied",
            "path": "C:/app/settings.json",
        },
    }


def test_control_command_returns_structured_validation_error(tmp_path: Path) -> None:
    def handler(command: str, args: dict) -> dict:
        raise ValueError("volume must be between 0 and 100")

    app, _socketio = create_app(
        MetricsBuffer(),
        PlaybackManager(tmp_path),
        control_handler=handler,
    )

    response = app.test_client().post(
        "/api/control/command",
        json={"command": "alarm.configure", "args": {}},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": {
            "code": "validation_error",
            "message": "volume must be between 0 and 100",
        },
    }


def test_control_command_returns_structured_busy_error(tmp_path: Path) -> None:
    def handler(command: str, args: dict) -> dict:
        raise BusyError("Stop the pipeline before changing camera settings")

    app, _socketio = create_app(
        MetricsBuffer(), PlaybackManager(tmp_path), control_handler=handler
    )

    response = app.test_client().post(
        "/api/control/command",
        json={"command": "camera.configure", "args": {}},
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "error": {
            "code": "busy",
            "message": "Stop the pipeline before changing camera settings",
        },
    }


def test_control_request_shape_and_missing_handler_errors_are_structured(
    tmp_path: Path,
) -> None:
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))
    client = app.test_client()

    invalid = client.post("/api/control/command", data="[]", content_type="application/json")
    missing = client.get("/api/control/state")

    assert invalid.status_code == 400
    assert invalid.get_json()["error"]["code"] == "validation_error"
    assert missing.status_code == 503
    assert missing.get_json()["error"] == {
        "code": "handler_missing",
        "message": "desktop control unavailable",
    }


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (OSError("disk failed"), 409, "io_error"),
        (RuntimeError("boom"), 500, "unexpected"),
    ],
)
def test_control_handler_failures_use_structured_envelope(
    tmp_path: Path, error: Exception, status: int, code: str
) -> None:
    def handler(command: str, args: dict) -> dict:
        raise error

    app, _socketio = create_app(
        MetricsBuffer(), PlaybackManager(tmp_path), control_handler=handler
    )

    response = app.test_client().post(
        "/api/control/command", json={"command": "state.fail", "args": {}}
    )

    assert response.status_code == status
    assert response.get_json()["error"] == {"code": code, "message": str(error)}


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


def test_engine_dialogs_do_not_use_hidden_legacy_window_as_parent() -> None:
    class Window:
        def __init__(self, visible: bool) -> None:
            self.visible = visible

        def isVisible(self) -> bool:  # noqa: N802 - Mirrors Qt API.
            return self.visible

    visible = Window(True)
    hidden = Window(False)

    assert desktop_dialog_parent(visible, engine_mode=True) is None
    assert desktop_dialog_parent(hidden, engine_mode=False) is None
    assert desktop_dialog_parent(visible, engine_mode=False) is visible
