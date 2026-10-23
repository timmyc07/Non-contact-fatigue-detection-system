# ProMotion 捲動審查與修正

## 結論與範圍

使用者感覺捲動無法配合 ProMotion。審查確認兩個問題：macOS WKWebView 的頁面更新停留在約 60fps，以及 Flutter 捲動時重新記錄整頁靜態內容的繪製指令。這是介面排程與繪製問題，未修改相機採樣、分析演算法、疲勞／rPPG／HRV／ROI／校準、記錄、BLE 或 API 契約。

修改限於主 WebView 建立前的刷新偏好、共用頁面內容的單一 RepaintBoundary，以及相關回歸測試。不新增後台循環、不強制螢幕固定 120Hz，不改透明 Overlay 的刷新策略，也不降低資料更新頻率。跨 Flutter／Tauri 的改動依專案規則按重量級驗證。

## 本機證據

本機為 macOS 26.6.2、Apple Silicon、內建 ProMotion 螢幕。公開 NSScreen API 回報最高 120fps，CoreGraphics 目前模式為 120Hz；AC／電池低耗電模式皆未啟用。

獨立原生 WKWebView 對照測試使用同一台機器、同一可見視窗、Canvas 動畫及相同取樣方式。下列有效區段取樣時的 document.hasFocus 均為 true；結尾的原生 active、visible、occlusion-visible 檢查也均為 true。先暖機，再記錄約 3.5 秒 rAF 間隔；WebKit 計時精度使個別間隔呈整數毫秒。

| 策略 | 樣本數 | 中位間隔 | p95 間隔 | 平均 callback fps |
| --- | ---: | ---: | ---: | ---: |
| 建立後將偏好設為 false，讀回已為 false | 211 | 17ms | 18ms | 59.98 |
| 上述策略另加公開原生 120fps DisplayLink | 211 | 17ms | 17ms | 60.01 |
| **建立前**在 configuration.preferences 設 false | 421 | 8ms | 9ms | 119.98 |

建立前策略最大間隔為 10ms，沒有 >12.5ms 的樣本。實驗只證明本機必須在建構前設定；不將 configuration getter 是否複製或 WebKit 內部鎖定機制當成已證明原因。原生 DisplayLink 自己達到 120fps，也無法改變既有 WebView 的 JS 排程。

實際 Tauri release 在刷新策略修正前（已含繪製邊界）的被動 rAF 取樣為 361 個間隔，中位 17ms、p95 18ms、平均 16.6482ms。該區段 document.hasFocus 為 false，故只能作輔助觀察，不當作嚴格前景對照。rAF callback 頻率代表排程機會，並不等同每一幀都已呈現在螢幕上。

Flutter 的真實 Dashboard 回歸測試以 8.333ms 步長捲動 10 次，每次 8px。修正前同一靜態標題重新繪製 10 次；加入單一內容邊界後為 0 次，最終捲動位置仍為 80px。影像預覽原有獨立邊界保持不變。這證明繪製指令重用，不能單獨證明 GPU 成本或實機 FPS。

套用修正後的實際 Tauri release，在可見主面板取樣 720 個間隔：中位 **8ms**、p95 **9ms**、平均 **8.3347ms（119.98fps）**、最大 **10ms**，沒有 >12.5ms 的樣本。該輪 document.hasFocus 仍為 false，故不宣稱是嚴格前景測試；相較相同條件下的修正前取樣，已確認實際程式能獲得 120Hz 排程。另以原生操作確認監測頁可捲動至底部、內容完整。原始間隔與對照資料保存於 [量測紀錄](../benchmarks/promotion-scroll-2026-10-23.json)。

## 實作與平台邊界

沿用原有 main window 設定，僅 macOS 改由 setup 明確建立主 WebView，於建構前將 `PreferPageRenderingUpdatesNear60FPSEnabled` 設為 false。Windows／Linux 保留原有自動建窗流程。私有 selector 或 feature 不存在時安全回退至 WebKit 預設行為並輸出診斷，不讓應用程式無法啟動。這個私有 API 不適用 Mac App Store，未來系統更新後需重新量測。

## 版本與來源

Flutter 3.47.2／Dart 3.13.2、Tauri 2.11.5、tauri-runtime-wry 2.11.4、wry 0.55.1、tao 0.35.3、Apple WebKit 21624.5.1.11.3。macOS 直接引用既有 lockfile 的 objc2 0.6.4、objc2-foundation／objc2-web-kit 0.3.2，不升級其版本。Context7 只有 Flutter main／Tauri dev 索引，另核對本機安裝版本來源，未以 dev 文件取代版本核驗。

開始前搜尋 GitHub 相關開源實作與上游問題；未引入新 FPS 插件。

- [WebKit 官方刷新率說明](https://webkit.github.io/explainers/animation-frame-rate/)：rAF 排程與原生加速動畫的差異。
- [WebKit 官方私有偏好 API](https://github.com/WebKit/WebKit/blob/37aa2b5bd94dc9ce8ebac88cd9c4f6ce652db9ef/Source/WebKit/UIProcess/API/Cocoa/WKPreferencesPrivate.h)：列舉 feature 與設定值。
- [Tauri 上游限制](https://github.com/tauri-apps/tauri/issues/13978)：WKWebView 未提供公開刷新策略設定。
- [開源調查](https://github.com/userFRM/tauri-plugin-macos-fps)、[Wails 實測](https://github.com/wailsapp/wails/issues/6056)：macOS 26 的外部報告不一致，因此採本機前後測。
- [Flutter 重繪效能文件](https://docs.flutter.dev/perf/best-practices)：減少不必要繪製，留意 layer／快取成本。

## 驗證界限

- 完整 `flutter test`：78 項通過；`flutter analyze` 無問題。
- 完整 `pytest -q -rs`：858 項通過、2 項因 Windows 路徑語意而在 macOS 略過。
- `cargo check --offline`、`cargo test --offline`：原生 13 項測試通過。
- `compileall`、`pip check`、`git diff --check` 通過。
- 三軸審查涵蓋官方 API／精確版本／主執行緒與擁有權，建窗／IPC／CSP／single-instance／backend 生命週期，以及文件／量測與私有 API 邊界。修正直接依賴的 NSEnumerator feature 宣告及報告統計一致性。
- 數值行為影響：未修改 Python 分析路徑、閾值、schema 或資料更新頻率。完整 Python 回歸通過；未另執行需要實際資料集的 UTA-RLDD golden replay。
- 正式 macOS `.app` release 建置成功；建置產物與安裝版的 `codesign --verify --deep --strict` 均通過。既有 socket_io_common 的 Wasm dry-run 與 CupertinoIcons 字型提示仍存在，現行 dart2js 目標正常建置。

已備份並更新 `/Applications/疲勞監測操作台.app`，正式二進位已確認不含臨時探針字串；開啟後主面板、引擎連線與控制區正常，保持開啟供使用。未清除使用者資料或更改分析偏好。

原生量測使用暫時加入的被動 rAF 探針，結果僅送至本機 loopback；正式版本已移除探針、臨時檔案讀取與報告端點。未將測試功能、啟動參數或診斷面板加入產品。

未以顯示器高速攝影量測每幀實際呈現，未做攝影機／BLE 同時開啟時的長時間 GPU／電池壓測。高刷新排程可能增加動畫期間的耗電；靜態畫面不新增持續更新工作。全頁保留繪製 layer 有記憶體取捨，沒有宣稱零成本。
