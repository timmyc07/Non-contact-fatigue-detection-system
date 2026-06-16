from __future__ import annotations

import sqlite3
from pathlib import Path

from gui.web_server import MetricsBuffer, PlaybackManager, create_app, format_web_dashboard_urls


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


def test_playback_manager_lists_nested_utarldd_recordings(tmp_path: Path) -> None:
    db_path = tmp_path / "utarldd_runs" / "run1" / "metrics_utarldd_01_0_20260606_010203.db"
    _write_minimal_metrics_db(db_path)

    manager = PlaybackManager(tmp_path)
    recordings = manager.list_recordings()

    assert len(recordings) == 1
    assert recordings[0]["filename"] == "utarldd_runs/run1/metrics_utarldd_01_0_20260606_010203.db"
    assert recordings[0]["path"] == str(db_path)
    assert recordings[0]["record_count"] == 2


def test_playback_api_reads_nested_utarldd_db(tmp_path: Path) -> None:
    db_path = tmp_path / "utarldd_runs" / "run1" / "metrics_utarldd_01_10_20260606_010203.db"
    _write_minimal_metrics_db(db_path)
    app, _socketio = create_app(MetricsBuffer(), PlaybackManager(tmp_path))

    client = app.test_client()
    recordings_resp = client.get("/api/recordings")
    playback_resp = client.get("/api/playback/full", query_string={"db_path": str(db_path)})

    recordings_json = recordings_resp.get_json()
    playback_json = playback_resp.get_json()
    assert recordings_json["success"] is True
    assert recordings_json["data"][0]["filename"].startswith("utarldd_runs/")
    assert playback_json["success"] is True
    assert playback_json["total"] == 2
    assert playback_json["data"][1]["status"] == "DROWSY"


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
