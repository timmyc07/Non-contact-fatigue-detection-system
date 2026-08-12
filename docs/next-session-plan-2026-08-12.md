# 下一階段續作計畫

日期：2026-08-12

收尾提交基準：`6ec82b0 refactor(engine): 移除最後的假控件`

目前狀態：`main` 與 `origin/main` 同步，工作樹乾淨；本階段停止新增實作。

## 本階段完成狀態

- 正式產品的唯一可見入口已是 Tauri v2 + Flutter Web；一般執行由 Tauri 啟動
  `main.py --engine`，`--legacy-ui` 會明確拒絕。
- engine mode 不顯示 Qt 主視窗或 Qt Overlay，也不建立 menu、dashboard、status bar、
  monitor、心跳帶、camera、recording、profile 等 Qt 假控件。
- `EngineController` 與 Qt-free runtime state 已承接 camera、analysis topology、pipeline、
  recording、replay、shutdown、BLE、overlay、capture 及 Web preference 的正式狀態。
- Python/Qt 目前只保留 `QApplication`、`QMainWindow`、`QThread`、`QTimer`、signal/slot、
  multimedia alarm 與 Windows native hotkey 所需的隱藏 runtime adapter。
- 已建立 desktop engine 與 packaged smoke 基準；細節見
  `docs/tauri-flutter-migration.md` 與 `docs/benchmarks/`。
- 最近一次完整驗證：Python `701 passed, 2 skipped`、desktop settings `118 passed`、
  Flutter `28 passed`、Flutter analyze 無問題、Flutter Web release 通過、Rust `8 passed`、
  Tauri release/NSIS、`compileall` 與 `pip check` 均通過。
- 最近一次重複 benchmark：RSS `254.711 MiB`、API ready `1833.801 ms`、
  IPC p50/p95 `20.350/41.103 ms`、preview p50/p95 `1.193/1.485 ms`。

以上變更未修改 camera frame routing、worker topology、錄影、警報、BLE 樣本、回放、
rPPG、疲勞分數、ROI、校準或任何數值閾值。

## 已知剩餘缺口

1. Flutter 正式面板仍包含「DL 基準測試（120s）」；其 Python command 只切換文字狀態，
   並明確記錄「示範，無實際採樣」。正式產品不應保留這個假功能。
2. Python engine 仍以隱藏的 `QApplication + MainWindow` 作 runtime 容器。這不是可見舊面板，
   但仍有 Qt widget shell 成本；直接改成 `QCoreApplication + QObject` 會涉及 native hotkey、
   shutdown、parent ownership 與 multimedia，相當於重量級啟動流程改造。
3. 原 Flask dashboard 仍作 localhost 診斷 fallback；它不是正式可見主面板。

## 下一階段執行順序

1. **移除正式面板的假 benchmark（優先，中量）**
   - 從 Flutter 移除按鈕與 `benchmark.set` command。
   - 從 desktop API state/command 移除 `benchmark_active` 與 `benchmark.set`。
   - 移除 `_benchmark_active`、`_toggle_benchmark` 及 legacy benchmark widgets。
   - 保留真正的 `scripts/desktop_engine_benchmark.py` 與其測試、文件和基準資料。
   - 增加 contract/UI 測試，防止示範功能再次進入正式面板。

2. **設計 Qt runtime adapter 抽離（重量）**
   - 先盤點 `closeEvent`、`nativeEvent`、`QApplication.instance().quit()`、QThread/QTimer parent、
     alarm backend 與所有 widget-only API。
   - 以獨立 `EngineRuntime(QObject)` 垂直切片抽離，不直接翻轉 `MainWindow` inheritance。
   - 為 Windows global hotkey 與正常 shutdown 建立無可見視窗的等價方案。
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
