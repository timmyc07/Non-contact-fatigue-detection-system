from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_repository_hygiene import main


def test_hygiene_rejects_force_added_local_files(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".gitignore").write_text("*.png\nAGENTS.md\n.env\n", encoding="utf-8")
    for name in ("capture.png", "AGENTS.md", ".env"):
        (tmp_path / name).write_text("private contents", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "capture.png", "AGENTS.md", ".env"], check=True)

    assert main() == 1
    output = capsys.readouterr().out
    assert all(name in output for name in ("capture.png", "AGENTS.md", ".env"))
    assert "private contents" not in output


def test_hygiene_accepts_source_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], check=True)

    assert main() == 0


def test_project_ignore_rules_cover_local_assets() -> None:
    paths = [
        "photos/capture.PNG", "photos/capture.Jpeg", "diagrams/architecture.svg",
        "src-tauri/icons/icon.icns", "AGENTS.md", "nested/CLAUDE.md",
        ".env.production", "tools/canva-flowchart/.env", "Saved/Logs/events.jsonl",
        "docs/exports/report.pdf", "models/face_landmarker.task",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths) + "\n", text=True, stdout=subprocess.PIPE, check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.stdout.splitlines() == paths
