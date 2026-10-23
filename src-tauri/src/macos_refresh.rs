use objc2::rc::Retained;
use objc2::runtime::{AnyObject, Bool};
use objc2::{msg_send, sel, ClassType, MainThreadMarker};
use objc2_foundation::{NSArray, NSString};
use objc2_web_kit::{WKPreferences, WKWebViewConfiguration};
use tauri::{WebviewWindow, WebviewWindowBuilder};

const FRAME_RATE_FEATURE: &str = "PreferPageRenderingUpdatesNear60FPSEnabled";

fn enable_display_refresh_rate(configuration: &WKWebViewConfiguration) {
    // WebKit 私有 API 可能隨系統變更；先檢查 selector，缺少功能時保留原生預設。
    // 必須在 WKWebView 建構前設定，建構後修改在 macOS 26.6.2 實測仍只有 60fps。
    // SAFETY: 呼叫端持有主執行緒 configuration；Retained 保證物件存活，私有 selector 皆先檢查。
    unsafe {
        let preferences = configuration.preferences();
        let can_list: Bool = msg_send![WKPreferences::class(), respondsToSelector: sel!(_features)];
        let can_set: Bool =
            msg_send![&preferences, respondsToSelector: sel!(_setEnabled:forFeature:)];
        let can_read: Bool =
            msg_send![&preferences, respondsToSelector: sel!(_isEnabledForFeature:)];
        if !can_list.as_bool() || !can_set.as_bool() || !can_read.as_bool() {
            eprintln!("macOS 高刷新率設定不可用，沿用 WebKit 預設。");
            return;
        }
        let features: Option<Retained<NSArray<AnyObject>>> =
            msg_send![WKPreferences::class(), _features];
        if let Some(features) = features {
            for feature in features.iter() {
                let can_key: Bool = msg_send![&feature, respondsToSelector: sel!(key)];
                if !can_key.as_bool() {
                    continue;
                }
                let key: Option<Retained<NSString>> = msg_send![&feature, key];
                if key
                    .as_deref()
                    .is_some_and(|key| key.to_string() == FRAME_RATE_FEATURE)
                {
                    let _: () =
                        msg_send![&preferences, _setEnabled: Bool::NO, forFeature: &*feature];
                    let enabled: Bool = msg_send![&preferences, _isEnabledForFeature: &*feature];
                    if enabled.as_bool() {
                        eprintln!("macOS 高刷新率設定讀回失敗，WebKit 仍偏好 60fps。");
                    } else {
                        eprintln!("macOS 主面板已解除 WebKit 偏好 60fps 設定。");
                    }
                    return;
                }
            }
        }
        eprintln!("WebKit 缺少高刷新率選項，沿用原生預設。");
    }
}

pub fn create_main_window(app: &tauri::App) -> tauri::Result<WebviewWindow> {
    let mtm = MainThreadMarker::new().expect("Tauri setup must run on the main thread");
    let configuration = unsafe { WKWebViewConfiguration::new(mtm) };
    enable_display_refresh_rate(&configuration);
    let window = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .expect("main window configuration must exist");
    WebviewWindowBuilder::from_config(app, window)?
        .with_webview_configuration(configuration)
        .build()
}
