from __future__ import annotations

import json
from pathlib import Path

from scripts.prepare_local_assets import prepare_icons


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_shell_uses_opaque_main_webview_surface() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    window = config["app"]["windows"][0]

    assert window["decorations"] is False
    assert window["transparent"] is False
    assert window["devtools"] is False


def test_flutter_bootstrap_page_has_opaque_fallback_background() -> None:
    html = (ROOT / "flutter_app" / "web" / "index.html").read_text(encoding="utf-8")

    assert "background:transparent" not in html.replace(" ", "").lower()


def test_desktop_release_builds_use_bundled_web_resources() -> None:
    for config_name in ("tauri.conf.json", "tauri.macos.conf.json"):
        config = json.loads((ROOT / "src-tauri" / config_name).read_text(encoding="utf-8"))
        command = config["build"]["beforeBuildCommand"]["script"]

        assert "--no-web-resources-cdn" in command.split()


def test_tauri_csp_allows_flutter_canvaskit_and_fonts() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"]

    assert "https://www.gstatic.com" in csp
    assert "https://fonts.gstatic.com" in csp


def test_tauri_csp_allows_configured_loopback_backend_ports_only() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"]

    assert "http://127.0.0.1:*" in csp
    assert "http://localhost:*" in csp
    assert "ws://127.0.0.1:*" in csp
    assert "ws://localhost:*" in csp
    assert "http://*:" not in csp


def test_windows_installer_bundles_offline_webview_runtime() -> None:
    config = json.loads(
        (ROOT / "src-tauri" / "tauri.windows.conf.json").read_text(encoding="utf-8")
    )
    install_mode = config["bundle"]["windows"]["webviewInstallMode"]

    assert install_mode == {"type": "offlineInstaller", "silent": True}
    assert config["bundle"]["targets"] == ["nsis"]


def test_macos_bundle_enables_overlay_and_native_artifacts() -> None:
    config = json.loads(
        (ROOT / "src-tauri" / "tauri.macos.conf.json").read_text(encoding="utf-8")
    )

    assert config["app"]["macOSPrivateApi"] is True
    assert config["bundle"]["targets"] == ["app", "dmg"]
    assert config["bundle"]["macOS"]["minimumSystemVersion"] == "15.0"
    assert config["bundle"]["macOS"]["infoPlist"] == "Info.plist"
    assert config["bundle"]["macOS"]["signingIdentity"] == "-"
    assert "127.0.0.1:5055" in config["build"]["beforeDevCommand"]["script"]
    assert "127.0.0.1:5055" in config["build"]["beforeBuildCommand"]["script"]


def test_desktop_icons_cover_windows_and_macos(tmp_path: Path) -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    icons = set(config["bundle"]["icon"])

    assert "icons/icon.png" in icons
    assert "icons/icon.icns" in icons
    assert "icons/icon-windows.ico" in icons
    prepare_icons(tmp_path)
    for relative_path in icons:
        assert (tmp_path / "src-tauri" / relative_path).is_file()


def test_macos_privacy_manifest_declares_camera_and_bluetooth() -> None:
    plist = (ROOT / "src-tauri" / "Info.plist").read_text(encoding="utf-8")

    assert "NSCameraUsageDescription" in plist
    assert "NSBluetoothAlwaysUsageDescription" in plist


def test_tauri_bundles_engine_under_the_runtime_resource_root() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert config["bundle"]["resources"] == {"../dist/ncfd-engine/": "engine/"}


def test_tauri_shell_enforces_single_instance() -> None:
    cargo = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    source = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    assert 'tauri-plugin-single-instance = "2"' in cargo
    assert "tauri_plugin_single_instance::init" in source


def test_tauri_shell_exposes_camera_privacy_settings_command() -> None:
    source = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "fn open_camera_privacy_settings()" in source
    assert "Privacy_Camera" in source
    assert "open_camera_privacy_settings" in source


def test_desktop_build_propagates_tauri_failure() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert "npm run desktop:build" in script
    assert 'if ($LASTEXITCODE -ne 0)' in script
    assert "Tauri desktop build failed" in script


def test_macos_build_and_smoke_scripts_use_native_bundle_contract() -> None:
    build_script = (ROOT / "scripts" / "build_desktop_macos.sh").read_text(
        encoding="utf-8"
    )
    smoke_script = (ROOT / "scripts" / "installed_desktop_smoke_macos.py").read_text(
        encoding="utf-8"
    )

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "scripts/prepare_engine_sidecar.mjs" in package["scripts"]["desktop:build"]
    assert "npm run desktop:build" in build_script
    assert "疲勞監測操作台.app" in smoke_script
    assert 'default=5055' in smoke_script


def test_linux_bundle_declares_native_appimage_and_deb_artifacts(tmp_path: Path) -> None:
    config = json.loads(
        (ROOT / "src-tauri" / "tauri.linux.conf.json").read_text(encoding="utf-8")
    )

    assert config["bundle"]["targets"] == ["appimage", "deb"]
    assert config["bundle"]["linux"]["appimage"]["bundleMediaFramework"] is False
    assert "libglib2.0-0" in config["bundle"]["linux"]["deb"]["depends"]
    prepare_icons(tmp_path)
    for icon in config["bundle"]["icon"]:
        assert (tmp_path / "src-tauri" / icon).is_file()


def test_linux_build_and_start_scripts_use_linux_runtime_contract() -> None:
    build_script = (ROOT / "scripts" / "build_desktop_linux.sh").read_text(
        encoding="utf-8"
    )
    start_script = (ROOT / "scripts" / "start_desktop_linux.sh").read_text(
        encoding="utf-8"
    )
    setup_script = (ROOT / "scripts" / "setup_ubuntu.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts.runtime_preflight" in build_script
    assert "scripts/prepare_engine_sidecar.mjs" in build_script
    assert "tauri build --config src-tauri/tauri.linux.conf.json" in build_script
    assert "scripts.runtime_preflight" in start_script
    assert "flutter pub get" in start_script
    assert "npm run desktop" in start_script
    assert "NCFD_BACKEND_PORT" in start_script
    assert "dpkg --compare-versions" in setup_script
    assert "libwebkit2gtk-4.1-dev" in setup_script


def test_linux_installed_smoke_uses_appimage_and_configurable_port() -> None:
    smoke_script = (ROOT / "scripts" / "installed_desktop_smoke_linux.py").read_text(
        encoding="utf-8"
    )

    assert "APPIMAGE_EXTRACT_AND_RUN" in smoke_script
    assert "NCFD_BACKEND_PORT" in smoke_script
    assert 'default=5000' in smoke_script
    assert 'app.shutdown' in smoke_script
