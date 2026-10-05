#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{
    Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_dialog::DialogExt;

struct BackendProcess(Mutex<Option<Child>>);
struct DesktopShutdown(AtomicBool);

const DESKTOP_CONTROL_API_VERSION: u64 = 2;
const WINDOWS_LINUX_BACKEND_PORT: u16 = 5000;
const MACOS_BACKEND_PORT: u16 = 5055;

#[derive(Debug, Serialize)]
struct SystemInfo {
    os: String,
    arch: String,
    tauri_version: String,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
struct OverlayGeometry {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

fn validate_overlay_geometry(geometry: OverlayGeometry) -> Result<OverlayGeometry, String> {
    if !(-100_000..=100_000).contains(&geometry.x)
        || !(-100_000..=100_000).contains(&geometry.y)
    {
        return Err("overlay geometry position is outside the supported range".to_owned());
    }
    if !(320..=16_384).contains(&geometry.width)
        || !(180..=16_384).contains(&geometry.height)
    {
        return Err("overlay geometry size is outside the supported range".to_owned());
    }
    Ok(geometry)
}

fn read_overlay_geometry(window: &WebviewWindow) -> Result<OverlayGeometry, String> {
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.inner_size().map_err(|error| error.to_string())?;
    Ok(OverlayGeometry {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    })
}

#[tauri::command]
fn get_system_info() -> SystemInfo {
    SystemInfo {
        os: std::env::consts::OS.to_owned(),
        arch: std::env::consts::ARCH.to_owned(),
        tauri_version: env!("CARGO_PKG_VERSION").to_owned(),
    }
}

#[tauri::command]
fn minimize_window(window: WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(|error| error.to_string())
}

#[tauri::command]
fn toggle_maximize_window(window: WebviewWindow) -> Result<(), String> {
    if window.is_maximized().map_err(|error| error.to_string())? {
        window.unmaximize().map_err(|error| error.to_string())
    } else {
        window.maximize().map_err(|error| error.to_string())
    }
}

#[tauri::command]
fn close_window(app: tauri::AppHandle) -> Result<(), String> {
    shutdown_desktop(&app);
    Ok(())
}

#[tauri::command]
fn start_dragging(window: WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|error| error.to_string())
}

#[tauri::command]
fn toggle_always_on_top(window: WebviewWindow) -> Result<bool, String> {
    let next = !window
        .is_always_on_top()
        .map_err(|error| error.to_string())?;
    window
        .set_always_on_top(next)
        .map_err(|error| error.to_string())?;
    Ok(next)
}

fn validate_external_directory(raw_path: &str) -> Result<PathBuf, String> {
    if raw_path.trim().is_empty() {
        return Err("external path must not be empty".to_owned());
    }
    let path = PathBuf::from(raw_path);
    if !path.is_dir() {
        return Err("external path must be an existing directory".to_owned());
    }
    fs::canonicalize(&path).map_err(|error| format!("cannot resolve external path: {error}"))
}

fn validate_external_url(raw_url: &str) -> Result<&str, String> {
    if raw_url.trim() != raw_url
        || raw_url.is_empty()
        || raw_url.chars().any(char::is_whitespace)
    {
        return Err("external URL must not contain whitespace".to_owned());
    }
    let has_http_scheme = raw_url.starts_with("http://") || raw_url.starts_with("https://");
    if !has_http_scheme {
        return Err("external URL must use http:// or https://".to_owned());
    }
    let authority = raw_url
        .split_once("://")
        .and_then(|(_, rest)| rest.split(['/', '?', '#']).next())
        .unwrap_or_default();
    if authority.is_empty() {
        return Err("external URL must include a host".to_owned());
    }
    Ok(raw_url)
}

fn open_external_target(target: &std::ffi::OsStr) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let mut command = Command::new("explorer.exe");
    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = Command::new("xdg-open");

    command
        .arg(target)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("failed to open external target: {error}"))
}

#[tauri::command]
fn open_camera_privacy_settings() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return Command::new("open")
            .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera")
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("failed to open macOS camera privacy settings: {error}"));
    }

    #[cfg(target_os = "windows")]
    {
        return Command::new("cmd")
            .args(["/C", "start", "", "ms-settings:privacy-webcam"])
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("failed to open Windows camera privacy settings: {error}"));
    }

    #[cfg(target_os = "linux")]
    {
        return Command::new("xdg-open")
            .arg("settings://privacy")
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("failed to open Linux privacy settings: {error}"));
    }

    #[allow(unreachable_code)]
    Err("camera privacy settings are not supported on this platform".to_owned())
}

#[tauri::command]
fn open_external_path(path: String) -> Result<(), String> {
    let directory = validate_external_directory(&path)?;
    open_external_target(directory.as_os_str())
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let validated = validate_external_url(&url)?;
    open_external_target(std::ffi::OsStr::new(validated))
}

fn path_to_frontend_string(path: &Path) -> Result<String, String> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| "selected folder path is not valid UTF-8".to_owned())
}

#[tauri::command]
async fn pick_replay_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let selected = tauri::async_runtime::spawn_blocking(move || {
        app.dialog().file().blocking_pick_folder()
    })
    .await
    .map_err(|error| error.to_string())?;
    let Some(file_path) = selected else {
        return Ok(None);
    };
    let path = file_path.into_path().map_err(|error| error.to_string())?;
    path_to_frontend_string(&path).map(Some)
}

fn overlay_url() -> WebviewUrl {
    if cfg!(debug_assertions) {
        WebviewUrl::External(
            "http://localhost:1420/?overlay=1"
                .parse()
                .expect("overlay dev URL must be valid"),
        )
    } else {
        WebviewUrl::App("index.html?overlay=1".into())
    }
}

#[tauri::command]
async fn set_overlay_window(
    app: tauri::AppHandle,
    visible: bool,
    locked: bool,
    geometry: Option<OverlayGeometry>,
    reset_geometry: bool,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        if reset_geometry && geometry.is_some() {
            return Err("overlay geometry and reset_geometry are mutually exclusive".to_owned());
        }
        let geometry = geometry.map(validate_overlay_geometry).transpose()?;
        let existing = app.get_webview_window("overlay");
        let (window, created) = if let Some(window) = existing {
            (window, false)
        } else if visible {
            let window = WebviewWindowBuilder::new(&app, "overlay", overlay_url())
                .title("疲勞監測 Overlay")
                .inner_size(720.0, 480.0)
                .min_inner_size(320.0, 180.0)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .visible(false)
                .build()
                .map_err(|error| error.to_string())?;
            (window, true)
        } else {
            return Ok(());
        };

        let configure_result = (|| {
            if reset_geometry {
                window
                    .set_size(PhysicalSize::new(720, 480))
                    .map_err(|error| error.to_string())?;
                window.center().map_err(|error| error.to_string())?;
            } else if let Some(geometry) = geometry {
                let current = read_overlay_geometry(&window)?;
                if current.width != geometry.width || current.height != geometry.height {
                    window
                        .set_size(PhysicalSize::new(geometry.width, geometry.height))
                        .map_err(|error| error.to_string())?;
                }
                if current.x != geometry.x || current.y != geometry.y {
                    window
                        .set_position(PhysicalPosition::new(geometry.x, geometry.y))
                        .map_err(|error| error.to_string())?;
                }
            }
            window
                .set_ignore_cursor_events(locked)
                .map_err(|error| error.to_string())?;
            if visible {
                window.show().map_err(|error| error.to_string())?;
            } else {
                window.hide().map_err(|error| error.to_string())?;
            }
            Ok(())
        })();
        if configure_result.is_err() && created {
            let _ = window.destroy();
        }
        configure_result
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn get_overlay_geometry(
    app: tauri::AppHandle,
) -> Result<Option<OverlayGeometry>, String> {
    let Some(window) = app.get_webview_window("overlay") else {
        return Ok(None);
    };
    tauri::async_runtime::spawn_blocking(move || read_overlay_geometry(&window))
        .await
        .map_err(|error| error.to_string())?
        .map(Some)
}

fn backend_address() -> SocketAddr {
    let port = std::env::var("NCFD_BACKEND_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| *value != 0)
        .unwrap_or(if cfg!(target_os = "macos") {
            MACOS_BACKEND_PORT
        } else {
            WINDOWS_LINUX_BACKEND_PORT
        });
    SocketAddr::from(([127, 0, 0, 1], port))
}

fn backend_available() -> bool {
    TcpStream::connect_timeout(&backend_address(), Duration::from_millis(250)).is_ok()
}

fn backend_api_version_from_response(response: &str) -> Option<u64> {
    let (headers, body) = response.split_once("\r\n\r\n")?;
    if !headers.lines().next()?.contains(" 200 ") {
        return None;
    }
    let payload: serde_json::Value = serde_json::from_str(body).ok()?;
    payload
        .get("data")?
        .get("desktop_api_version")?
        .as_u64()
}

fn backend_api_compatible() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&backend_address(), Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
    let request = format!(
        "GET /api/control/state HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        backend_address()
    );
    if stream.write_all(request.as_bytes()).is_err() || stream.flush().is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    backend_api_version_from_response(&response) == Some(DESKTOP_CONTROL_API_VERSION)
}

fn project_root() -> PathBuf {
    if let Ok(configured) = std::env::var("NCFD_ENGINE_ROOT") {
        let path = PathBuf::from(configured);
        if path.join("main.py").exists() {
            return path;
        }
    }
    let manifest_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must live under the project root")
        .to_path_buf();
    if manifest_root.join("main.py").exists() {
        return manifest_root;
    }
    if let Ok(executable) = std::env::current_exe() {
        let mut candidate = executable.parent().map(Path::to_path_buf);
        for _ in 0..3 {
            if let Some(path) = candidate {
                if path.join("main.py").exists() {
                    return path;
                }
                candidate = path.parent().map(Path::to_path_buf);
            }
        }
    }
    manifest_root
}

fn python_executable(root: &Path) -> PathBuf {
    if let Ok(configured) = std::env::var("NCFD_ENGINE_PYTHON") {
        let path = PathBuf::from(configured);
        if path.exists() {
            return path;
        }
    }
    let virtual_env_python = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    if virtual_env_python.exists() {
        virtual_env_python
    } else {
        PathBuf::from(if cfg!(windows) { "python.exe" } else { "python3" })
    }
}

fn bundled_engine_path(resource_dir: &Path) -> Option<PathBuf> {
    let executable = if cfg!(windows) {
        "ncfd-engine.exe"
    } else {
        "ncfd-engine"
    };
    let candidate = resource_dir.join("engine").join(executable);
    candidate.is_file().then_some(candidate)
}

fn engine_path_for_mode(resource_dir: &Path, use_bundled: bool) -> Result<Option<PathBuf>, String> {
    if !use_bundled {
        return Ok(None);
    }
    bundled_engine_path(resource_dir).map(Some).ok_or_else(|| {
        format!(
            "bundled Python engine is missing under {}",
            resource_dir.join("engine").display()
        )
    })
}

fn bundled_resource_root(engine_path: &Path) -> PathBuf {
    let engine_dir = engine_path.parent().unwrap_or(engine_path);
    let internal = engine_dir.join("_internal");
    if internal.is_dir() {
        internal
    } else {
        engine_dir.to_path_buf()
    }
}

#[cfg(windows)]
fn hide_backend_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x0800_0000);
}

#[cfg(not(windows))]
fn hide_backend_console(_command: &mut Command) {}

#[cfg(unix)]
fn isolate_backend_process_tree(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}

#[cfg(not(unix))]
fn isolate_backend_process_tree(_command: &mut Command) {}

#[cfg(windows)]
fn kill_backend_process_tree(child: &mut Child) {
    let mut command = Command::new("taskkill");
    command.args(["/PID", &child.id().to_string(), "/T", "/F"]);
    hide_backend_console(&mut command);
    let _ = command.status();
    let _ = child.kill();
}

#[cfg(unix)]
fn kill_backend_process_tree(child: &mut Child) {
    // engine 使用獨立 process group，最後收尾時可一併結束 replay pool 與 ffmpeg，
    // 且不會誤傷其他桌面程序。
    unsafe {
        let _ = libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.kill();
}

#[cfg(not(any(unix, windows)))]
fn kill_backend_process_tree(child: &mut Child) {
    let _ = child.kill();
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<Option<Child>, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve resource directory: {error}"))?;
    let packaged_engine = engine_path_for_mode(&resource_dir, !cfg!(debug_assertions))?;
    if backend_available() {
        if backend_api_compatible() && packaged_engine.is_none() {
            return Ok(None);
        }
        request_backend_shutdown();
        let deadline = Instant::now() + Duration::from_secs(3);
        while backend_available() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        if backend_available() {
            return Err(format!(
                "A Python engine is already using port {} and could not be stopped. Close it and restart the application.",
                backend_address().port()
            ));
        }
    }
    let mut command = if let Some(engine_path) = packaged_engine {
        let engine_dir = engine_path
            .parent()
            .ok_or_else(|| "bundled engine has no parent directory".to_owned())?;
        let data_root = app
            .path()
            .app_local_data_dir()
            .map_err(|error| format!("failed to resolve app data directory: {error}"))?;
        fs::create_dir_all(&data_root)
            .map_err(|error| format!("failed to create app data directory: {error}"))?;
        let resource_root = bundled_resource_root(&engine_path);
        let mut command = Command::new(&engine_path);
        command.arg("--engine").current_dir(engine_dir);
        command
            .env("NCFD_RESOURCE_ROOT", resource_root)
            .env("NCFD_DATA_ROOT", data_root);
        command
    } else {
        let root = project_root();
        let mut command = Command::new(python_executable(&root));
        command
            .arg(root.join("main.py"))
            .arg("--engine")
            .current_dir(&root);
        command
    };
    command
        .env("NCFD_BACKEND_PORT", backend_address().port().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_backend_console(&mut command);
    isolate_backend_process_tree(&mut command);
    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start Python engine: {error}"))?;

    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if backend_api_compatible() {
            return Ok(Some(child));
        }
        if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
            return Err(format!("Python engine exited before startup: {status}"));
        }
        thread::sleep(Duration::from_millis(150));
    }
    kill_backend_process_tree(&mut child);
    let _ = child.wait();
    Err(format!(
        "Python engine did not open port {} within 20 seconds",
        backend_address().port()
    ))
}

fn request_backend_shutdown() {
    let body = r#"{"command":"app.shutdown","args":{}}"#;
    if let Ok(mut stream) = TcpStream::connect_timeout(&backend_address(), Duration::from_millis(500)) {
        let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
        let request = format!(
            "POST /api/control/command HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            backend_address(),
            body.len(),
            body
        );
        let _ = stream.write_all(request.as_bytes());
        let _ = stream.flush();
    }
}

fn stop_owned_backend(state: &BackendProcess) {
    let mut guard = match state.0.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    request_backend_shutdown();
    let Some(child) = guard.as_mut() else {
        // Debug 模式可能重用相容的 source engine，因此沒有可用的 Child handle。
        drop(guard);
        let deadline = Instant::now() + Duration::from_secs(6);
        while backend_available() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        return;
    };
    let deadline = Instant::now() + Duration::from_secs(6);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => {
                *guard = None;
                return;
            }
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(_) => break,
        }
    }
    kill_backend_process_tree(child);
    let _ = child.wait();
    *guard = None;
}

fn begin_desktop_shutdown(state: &DesktopShutdown) -> bool {
    !state.0.swap(true, Ordering::AcqRel)
}

fn shutdown_desktop(app_handle: &tauri::AppHandle) {
    if !begin_desktop_shutdown(&app_handle.state::<DesktopShutdown>()) {
        return;
    }
    for label in ["main", "overlay"] {
        if let Some(window) = app_handle.get_webview_window(label) {
            let _ = window.hide();
        }
    }
    let app_handle = app_handle.clone();
    thread::spawn(move || {
        stop_owned_backend(&app_handle.state::<BackendProcess>());
        app_handle.exit(0);
    });
}

fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendProcess(Mutex::new(None)))
        .manage(DesktopShutdown(AtomicBool::new(false)))
        .setup(|app: &mut tauri::App| {
            let child = spawn_backend(app.handle()).map_err(std::io::Error::other)?;
            *app.state::<BackendProcess>()
                .0
                .lock()
                .map_err(|_| std::io::Error::other("backend process lock poisoned"))? = child;
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_system_info,
            minimize_window,
            toggle_maximize_window,
            close_window,
            start_dragging,
            toggle_always_on_top,
            open_external_path,
            open_external_url,
            open_camera_privacy_settings,
            pick_replay_folder,
            set_overlay_window,
            get_overlay_geometry
        ])
        .build(tauri::generate_context!())
        .expect("error while building Tauri application");
    app.run(|app_handle, event| {
        match event {
            tauri::RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::CloseRequested { api, .. },
                ..
            } if label == "main" => {
                // macOS 關閉最後一個視窗後仍會保留應用程式，因此原生關閉事件也必須走
                // 與 Flutter 標題列關閉按鈕相同的完整 shutdown 路徑。Windows 共用此流程。
                api.prevent_close();
                shutdown_desktop(app_handle);
            }
            tauri::RunEvent::Exit => {
                // OS/session shutdown 與未來其他退出路徑的冪等 fallback。
                if !app_handle
                    .state::<DesktopShutdown>()
                    .0
                    .load(Ordering::Acquire)
                {
                    stop_owned_backend(&app_handle.state::<BackendProcess>());
                }
            }
            _ => {}
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run_app() {
    run();
}

fn main() {
    run_app();
}

#[cfg(test)]
mod tests {
    use super::{
        backend_api_version_from_response, begin_desktop_shutdown, bundled_engine_path,
        bundled_resource_root, engine_path_for_mode, path_to_frontend_string,
        validate_external_directory, validate_external_url, validate_overlay_geometry,
        DesktopShutdown, OverlayGeometry,
    };
    use std::fs;
    use std::path::Path;
    use std::sync::atomic::AtomicBool;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_resource_dir() -> std::path::PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("ncfd-tauri-test-{stamp}"));
        fs::create_dir_all(&path).expect("temporary resource directory");
        path
    }

    #[test]
    fn desktop_shutdown_guard_allows_only_one_cleanup_worker() {
        let state = DesktopShutdown(AtomicBool::new(false));
        assert!(begin_desktop_shutdown(&state));
        assert!(!begin_desktop_shutdown(&state));
    }

    #[test]
    fn parses_desktop_api_version_from_control_state() {
        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"success\":true,\"data\":{\"desktop_api_version\":2}}";

        assert_eq!(backend_api_version_from_response(response), Some(2));
    }

    #[test]
    fn rejects_control_state_without_desktop_api_version() {
        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"success\":true,\"data\":{\"pipeline_running\":false}}";

        assert_eq!(backend_api_version_from_response(response), None);
    }

    #[test]
    fn converts_native_replay_folder_path_for_flutter() {
        let path = Path::new(r"C:\datasets\UTA-RLDD");

        assert_eq!(
            path_to_frontend_string(path),
            Ok(r"C:\datasets\UTA-RLDD".to_owned())
        );
    }

    #[test]
    fn validates_overlay_geometry_with_negative_monitor_coordinates() {
        let geometry = OverlayGeometry {
            x: -1280,
            y: 24,
            width: 720,
            height: 480,
        };

        assert_eq!(validate_overlay_geometry(geometry), Ok(geometry));
    }

    #[test]
    fn rejects_overlay_geometry_outside_size_contract() {
        let geometry = OverlayGeometry {
            x: 0,
            y: 0,
            width: 319,
            height: 480,
        };

        assert!(validate_overlay_geometry(geometry)
            .expect_err("small overlay width must be rejected")
            .contains("size"));
    }

    #[test]
    fn validates_external_directory_and_resolves_it() {
        let directory = temp_resource_dir();
        let resolved = validate_external_directory(directory.to_str().expect("utf8 path"))
            .expect("temporary directory must be accepted");
        assert!(resolved.is_dir());
        fs::remove_dir_all(directory).expect("temporary resource cleanup");
    }

    #[test]
    fn rejects_missing_external_directory() {
        let directory = temp_resource_dir().join("missing");
        assert!(validate_external_directory(directory.to_str().expect("utf8 path"))
            .expect_err("missing directory must be rejected")
            .contains("existing directory"));
    }

    #[test]
    fn accepts_only_http_external_urls() {
        assert_eq!(
            validate_external_url("http://127.0.0.1:5000/?token=test"),
            Ok("http://127.0.0.1:5000/?token=test")
        );
        assert_eq!(validate_external_url("https://example.test"), Ok("https://example.test"));
        assert!(validate_external_url("file:///tmp/report").is_err());
        assert!(validate_external_url("https://").is_err());
        assert!(validate_external_url("https://example.test bad").is_err());
    }

    #[test]
    fn finds_bundled_engine_under_resource_directory() {
        let directory = temp_resource_dir();
        let engine_dir = directory.join("engine");
        fs::create_dir_all(&engine_dir).expect("engine directory");
        let name = if cfg!(windows) { "ncfd-engine.exe" } else { "ncfd-engine" };
        let engine = engine_dir.join(name);
        fs::write(&engine, b"test").expect("engine marker");

        assert_eq!(bundled_engine_path(&directory), Some(engine));
        fs::remove_dir_all(directory).expect("temporary resource cleanup");
    }

    #[test]
    fn debug_mode_ignores_stale_bundled_engine() {
        let directory = temp_resource_dir();
        let engine_dir = directory.join("engine");
        fs::create_dir_all(&engine_dir).expect("engine directory");
        let name = if cfg!(windows) {
            "ncfd-engine.exe"
        } else {
            "ncfd-engine"
        };
        fs::write(engine_dir.join(name), b"stale").expect("stale engine marker");

        assert_eq!(engine_path_for_mode(&directory, false), Ok(None));
        assert!(engine_path_for_mode(&directory, true)
            .expect("release engine")
            .is_some());
        fs::remove_dir_all(directory).expect("temporary resource cleanup");
    }

    #[test]
    fn release_mode_rejects_missing_bundled_engine() {
        let directory = temp_resource_dir();

        assert!(engine_path_for_mode(&directory, true)
            .expect_err("release must not fall back to the checkout")
            .contains("bundled Python engine is missing"));
        fs::remove_dir_all(directory).expect("temporary resource cleanup");
    }

    #[test]
    fn uses_pyinstaller_internal_directory_for_resources() {
        let directory = temp_resource_dir();
        let engine_dir = directory.join("engine");
        let internal = engine_dir.join("_internal");
        fs::create_dir_all(&internal).expect("internal directory");
        let engine = engine_dir.join(if cfg!(windows) {
            "ncfd-engine.exe"
        } else {
            "ncfd-engine"
        });

        assert_eq!(bundled_resource_root(&engine), internal);
        fs::remove_dir_all(directory).expect("temporary resource cleanup");
    }
}
