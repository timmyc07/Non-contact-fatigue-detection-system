#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, WebviewWindow};

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

#[cfg(windows)]
fn hide_backend_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x0800_0000);
}

#[cfg(not(windows))]
fn hide_backend_console(_command: &mut Command) {}

fn spawn_backend() -> Result<Option<Child>, String> {
    if backend_available() {
        if backend_api_compatible() {
            return Ok(None);
        }
        request_backend_shutdown();
        let deadline = Instant::now() + Duration::from_secs(3);
        while backend_available() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        if backend_available() {
            return Err(
                "An outdated Python engine is already using port 5000. Close it and restart the application."
                    .to_owned(),
            );
        }
    }
    let root = project_root();
    let mut command = Command::new(python_executable(&root));
    command
        .arg(root.join("main.py"))
        .arg("--engine")
        .current_dir(&root)
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
    Err("Python engine did not open port 5000 within 20 seconds".to_owned())
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
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app: &mut tauri::App| {
            let child = spawn_backend().map_err(std::io::Error::other)?;
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
            toggle_always_on_top
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
    use super::backend_api_version_from_response;

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
}
