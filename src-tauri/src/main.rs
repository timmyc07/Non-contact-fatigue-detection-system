#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::fs;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::DialogExt;

struct BackendProcess(Mutex<Option<Child>>);

const DESKTOP_CONTROL_API_VERSION: u64 = 2;

#[derive(Debug, Serialize)]
struct SystemInfo {
    os: String,
    arch: String,
    tauri_version: String,
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
fn close_window(window: WebviewWindow) -> Result<(), String> {
    window.close().map_err(|error| error.to_string())
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
fn set_overlay_window(
    app: tauri::AppHandle,
    visible: bool,
    locked: bool,
) -> Result<(), String> {
    let window = if let Some(window) = app.get_webview_window("overlay") {
        window
    } else if visible {
        WebviewWindowBuilder::new(&app, "overlay", overlay_url())
            .title("疲勞監測 Overlay")
            .inner_size(720.0, 480.0)
            .min_inner_size(320.0, 180.0)
            .decorations(false)
            .transparent(true)
            .always_on_top(true)
            .skip_taskbar(true)
            .visible(false)
            .build()
            .map_err(|error| error.to_string())?
    } else {
        return Ok(());
    };

    window
        .set_ignore_cursor_events(locked)
        .map_err(|error| error.to_string())?;
    if visible {
        window.show().map_err(|error| error.to_string())?;
    } else {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn backend_address() -> SocketAddr {
    let port = std::env::var("NCFD_BACKEND_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| *value != 0)
        .unwrap_or(5000);
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

fn spawn_backend(app: &tauri::AppHandle) -> Result<Option<Child>, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve resource directory: {error}"))?;
    let packaged_engine = bundled_engine_path(&resource_dir);
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
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_backend_console(&mut command);
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
    let _ = child.kill();
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
    let Ok(mut guard) = state.0.lock() else {
        return;
    };
    let Some(child) = guard.as_mut() else {
        return;
    };
    request_backend_shutdown();
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
    let _ = child.kill();
    let _ = child.wait();
    *guard = None;
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
            pick_replay_folder,
            set_overlay_window
        ])
        .build(tauri::generate_context!())
        .expect("error while building Tauri application");
    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_owned_backend(&app_handle.state::<BackendProcess>());
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
        backend_api_version_from_response, bundled_engine_path, bundled_resource_root,
        path_to_frontend_string,
    };
    use std::fs;
    use std::path::Path;
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
