# 下一階段續作計畫

更新日期：2026-08-15

本切片起始基準：`c52ed9e docs(plan): 更新下一階段續作邊界`

目前狀態：Windows 全域快捷鍵已不再依賴隱藏 `QMainWindow` 的 HWND 或 `nativeEvent()`；
本階段完成後停止新增實作。

## 本階段完成狀態

- 正式產品的唯一可見入口已是 Tauri v2 + Flutter Web；一般執行由 Tauri 啟動
  `main.py --engine`，`--legacy-ui` 會明確拒絕。
- engine mode 不顯示 Qt 主視窗或 Qt Overlay，也不建立 menu、dashboard、status bar、
  monitor、心跳帶、camera、recording、profile 等 Qt 假控件。
- `EngineController` 與 Qt-free runtime state 已承接 camera、analysis topology、pipeline、
  recording、replay、shutdown、BLE、overlay、capture 及 Web preference 的正式狀態。
- Python/Qt 目前只保留 `QApplication`、`QMainWindow`、`QThread`、`QTimer`、signal/slot、
  multimedia alarm 與其餘尚未抽離的隱藏 runtime adapter。Windows native hotkey 已由
  application-level `GlobalHotkeyRuntime` 承接，不再需要原生主視窗。
- 已建立 desktop engine 與 packaged smoke 基準；細節見
  `docs/tauri-flutter-migration.md` 與 `docs/benchmarks/`。
- 最近一次完整驗證：Python `710 passed, 2 skipped`、desktop settings `119 passed`、
  Flutter `28 passed`、Flutter analyze 無問題、Flutter Web release 通過、Rust `8 passed`、
  Tauri release/NSIS、`compileall` 與 `pip check` 均通過。
- 最近兩次重複 benchmark：RSS `257.824/257.379 MiB`、API ready
  `1850.292/1841.883 ms`、IPC p50/p95 `20.529/40.322` 與 `20.155/40.196 ms`、
  preview p50/p95 `1.200/1.481` 與 `1.195/1.489 ms`。

以上變更未修改 camera frame routing、worker topology、錄影、警報、BLE 樣本、回放、
rPPG、疲勞分數、ROI、校準或任何數值閾值。

## 已知剩餘缺口

1. Python engine 仍以隱藏的 `QApplication + MainWindow` 作 runtime 容器。這不是可見舊面板，
   但仍有 Qt widget shell 成本；全域快捷鍵的視窗依賴已移除，下一個主要阻塞是
   `MainWindow.closeEvent()` 擁有 shutdown cleanup，其後仍須處理 parent ownership 與 multimedia。
2. 原 Flask dashboard 仍作 localhost 診斷 fallback；它不是正式可見主面板。

## 下一階段執行順序

1. **已完成：移除正式面板的假 benchmark（中量）**
   - Flutter、desktop API state/command 與 legacy Qt code 不再包含示範 benchmark。
   - `scripts/desktop_engine_benchmark.py`、其測試、文件與基準資料維持不變。
   - contract/UI 測試防止示範功能再次進入正式面板。

2. **進行 Qt runtime adapter 抽離（重量）**
   - **已完成：** Windows global hotkey 改由 application-level native event filter 處理，使用
     `RegisterHotKey(HWND=NULL, ...)`，不再依賴 `MainWindow.winId()`／`nativeEvent()`。
   - **下一步：** 抽出可重入的 runtime shutdown cleanup，讓 engine `app.shutdown` 能直接清理並
     結束 application；保留 replay shutdown deferral 語意，`closeEvent()` 暫作 legacy adapter。
   - 後續盤點 `QApplication.instance().quit()`、QThread/QTimer parent、alarm backend 與其餘
     widget-only API。
   - 以獨立 `EngineRuntime(QObject)` 垂直切片抽離，不直接翻轉 `MainWindow` inheritance。
   - 每個切片維持 desktop API v2、worker topology 與數值輸出不變。

3. **完成 parity 與效能驗收**
   - 驗證主 WebView、engine child、overlay、視窗控制、設定、camera、recording、replay、BLE、
     notification、alarm 與正常 shutdown。
   - 使用固定 benchmark 參數比較 API ready、process-tree RSS、IPC 與 preview latency。
   - 有 UTA-RLDD 資料集時執行 golden/replay 零漂移檢查。

## 驗收命令

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m compileall -q main.py gui rppg tests
.venv\Scripts\python -m pip check
C:\tools\flutter\bin\flutter.bat test
C:\tools\flutter\bin\flutter.bat analyze
C:\tools\flutter\bin\flutter.bat build web --release
cargo test --manifest-path src-tauri/Cargo.toml
$env:Path = 'C:\tools\flutter\bin;' + $env:Path
npm run desktop:build
.venv\Scripts\python -m scripts.desktop_engine_benchmark --port 5001 --samples 10
git diff --check
```

完成前必須 read-back，明確聲明數值行為影響，並只提交代理造成的變更。測試、build、
upstream、認證或 push 失敗時，保留本地狀態並回報確切阻礙，不得宣稱完成。
