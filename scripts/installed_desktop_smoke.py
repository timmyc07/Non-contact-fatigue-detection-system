"""Exercise an isolated NSIS install, engine shutdown, and shell close."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from scripts.desktop_engine_client import control_state, port_in_use, request_json


CREATE_NO_WINDOW = 0x08000000
WM_CLOSE = 0x0010


def _wait_for_state(
    *, port: int, process: subprocess.Popen[bytes], timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"shell exited before API readiness: {process.returncode}")
        try:
            return control_state(host="127.0.0.1", port=port, timeout=0.5)
        except Exception:
            time.sleep(0.1)
    raise TimeoutError(f"desktop API did not become ready within {timeout:.1f}s")


def _windows_for_pid(pid: int) -> list[dict[str, Any]]:
    user32 = ctypes.windll.user32
    entries: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid:
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        entries.append(
            {
                "hwnd": int(hwnd),
                "title": title.value,
                "class_name": class_name.value,
                "visible": bool(user32.IsWindowVisible(hwnd)),
            }
        )
        return True

    callback = callback_type(collect)
    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError()
    return entries


def _select_main_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    main_windows = [
        entry
        for entry in windows
        if entry["visible"] and entry["class_name"] == "Tauri Window"
    ]
    if len(main_windows) != 1:
        raise RuntimeError(f"shell must have one visible Tauri window: {windows}")
    return main_windows


def _close_shell_windows(pid: int) -> list[dict[str, Any]]:
    windows = _windows_for_pid(pid)
    main_windows = _select_main_windows(windows)
    user32 = ctypes.windll.user32
    for entry in main_windows:
        if not user32.PostMessageW(entry["hwnd"], WM_CLOSE, 0, 0):
            raise ctypes.WinError()
    return main_windows


def _resolve_installer(root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        installer = explicit.resolve()
        if not installer.is_file():
            raise FileNotFoundError(installer)
        return installer
    nsis_dir = root / "src-tauri" / "target" / "release" / "bundle" / "nsis"
    installers = list(nsis_dir.glob("*_x64-setup.exe"))
    if len(installers) != 1:
        raise RuntimeError(
            f"expected one NSIS installer under {nsis_dir}, found {installers}"
        )
    return installers[0]


def run_smoke(
    *,
    installer: Path,
    port: int,
    timeout: float,
    install_timeout: float,
) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("installed desktop smoke is Windows-only")
    with tempfile.TemporaryDirectory(prefix="ncfd-installed-smoke-") as temp_root:
        install_dir = Path(temp_root) / "app"
        install_dir.mkdir()
        install_result = subprocess.run(
            [str(installer), "/S", f"/D={install_dir}"],
            check=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=install_timeout,
        )
        if install_result.returncode != 0:
            raise RuntimeError(f"installer failed with code {install_result.returncode}")

        shell_candidates = [
            path
            for path in install_dir.glob("*.exe")
            if "uninstall" not in path.name.lower()
        ]
        if len(shell_candidates) != 1:
            raise RuntimeError(f"expected one installed shell, found {shell_candidates}")

        environment = os.environ.copy()
        environment["NCFD_BACKEND_PORT"] = str(port)
        shell = subprocess.Popen(
            [str(shell_candidates[0])],
            cwd=install_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        try:
            state = _wait_for_state(port=port, process=shell, timeout=timeout)
            time.sleep(2.0)
            shutdown = request_json(
                "POST",
                "/api/control/command",
                host="127.0.0.1",
                port=port,
                body={"command": "app.shutdown", "args": {}},
                timeout=2.0,
            )
            if not shutdown.get("success"):
                raise RuntimeError(f"engine rejected app.shutdown: {shutdown}")
            visible_windows = _close_shell_windows(shell.pid)
            try:
                shell.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                remaining_windows = _windows_for_pid(shell.pid)
                raise TimeoutError(
                    f"shell did not exit within {timeout:.1f}s; "
                    f"before={visible_windows}, after={remaining_windows}"
                ) from exc
            deadline = time.monotonic() + timeout
            while (
                port_in_use(host="127.0.0.1", port=port)
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            if port_in_use(host="127.0.0.1", port=port):
                raise TimeoutError("engine port remained open after shell exit")
        finally:
            if shell.poll() is None:
                shell.terminate()
                try:
                    shell.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    shell.kill()
                    shell.wait(timeout=5.0)

        uninstallers = list(install_dir.glob("*uninstall*.exe"))
        if len(uninstallers) != 1:
            raise RuntimeError(f"expected one uninstaller, found {uninstallers}")
        uninstall_result = subprocess.run(
            [str(uninstallers[0]), "/S"],
            check=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=install_timeout,
        )
        if uninstall_result.returncode != 0:
            raise RuntimeError(f"uninstaller failed with code {uninstall_result.returncode}")
        deadline = time.monotonic() + timeout
        while install_dir.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if install_dir.exists():
            raise TimeoutError("installer directory remained after silent uninstall")
        return {
            "install_exit_code": install_result.returncode,
            "desktop_api_version": state["desktop_api_version"],
            "visible_tauri_window_count": len(visible_windows),
            "main_window_title": visible_windows[0]["title"],
            "main_window_class": visible_windows[0]["class_name"],
            "shutdown_success": bool(shutdown.get("success")),
            "engine_exited": True,
            "shell_exit_code": shell.returncode,
            "uninstall_exit_code": uninstall_result.returncode,
            "install_dir_removed": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--port", type=int, default=5011)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--install-timeout", type=float, default=120.0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = run_smoke(
        installer=_resolve_installer(root, args.installer),
        port=args.port,
        timeout=args.timeout,
        install_timeout=args.install_timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
