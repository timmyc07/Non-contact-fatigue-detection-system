# 下一階段續作計畫

更新日期：2026-08-17

本切片起始基準：`9a921c8 refactor(desktop): 抽離 runtime timer ownership`

目前狀態：live camera、analysis、錄影與 Replay QThread／worker、production runtime QTimer，以及
alarm/Qt multimedia ownership 已由 application-owned `EngineRuntime` 保存；production adapter 已改為
`EngineApplication(QObject)`，不再建立 `QMainWindow`／QWidget。下一切片移除不可達的 widget-only source。

## 本階段完成狀態

- 正式產品的唯一可見入口已是 Tauri v2 + Flutter Web；一般執行由 Tauri 啟動
  `main.py --engine`，`--legacy-ui` 會明確拒絕。
- engine mode 不顯示 Qt 主視窗或 Qt Overlay，也不建立 menu、dashboard、status bar、
  monitor、心跳帶、camera、recording、profile 等 Qt 假控件。
- `EngineController` 與 Qt-free runtime state 已承接 camera、analysis topology、pipeline、
  recording、replay、shutdown、BLE、overlay、capture 及 Web preference 的正式狀態。
- Python/Qt 目前只保留 `QApplication`、`QThread`、`QTimer`、signal/slot 與
  `EngineApplication(QObject)` runtime adapter；同檔仍留有尚未抽離的不可達 QtWidgets source。
  Windows native hotkey 已由
  application-level `GlobalHotkeyRuntime` 承接，不再需要原生主視窗。
- engine `app.shutdown` 已先保留 active replay 的停止／延後結束 gate；其餘 engine 路徑直接以可重入
  `_cleanup_runtime()` 依序清理快捷鍵、待處理採集、校準／timer／BLE、Web、錄影、相機／analysis producer、alarm 與 Overlay，然後呼叫
  `QApplication.quit()`。production adapter 沒有 `closeEvent()`；`close_runtime()` 是明確 teardown 入口。
- cleanup 現為逐步 best-effort：非 thread step 例外只記錄並繼續，主事件迴圈 100ms 後自動重試一次；第二次仍失敗則記錄並 best-effort quit。若 video、camera、analysis
  adapter thread wait timeout 且 ownership 尚存，engine 不 quit，待 `EngineRuntime.adapter_released` callback
  排程重入 shutdown。
  Tauri 只在等待 6 秒後仍未結束時才作最後的 child-process kill fallback。
- live camera 與 combined／rPPG／fatigue adapter 已改由 application-owned `EngineRuntime(QObject)` 建立並
  保存 QThread／worker；共同 signal wiring、原 timeout、join-before-release 與 stale-finish 保護集中於 runtime。`EngineApplication`
  僅保留 worker-specific callback、queue／routing 與 legacy presentation side effect。
- 錄影與 Replay QThread／worker ownership 也已移入 `EngineRuntime`。錄影維持原 request-stop、2000ms wait
  timeout 與 late-finish cleanup；Replay 維持非同步 cooperative stop、deterministic timestamp、報表輸出與
  shutdown deferral，完成後由 adapter release callback 重入 controller／shutdown。
- desktop command drain、心跳帶 1 秒 tick、自動採集 one-shot 與 shutdown defer/retry 的 QTimer ownership
  已移入 `EngineRuntime`。`EngineApplication` 只保留既有 callback；legacy REC presentation timer、Web restart 與
  Overlay 自有排程維持各自既有 owner。
- `EngineRuntime` 已承接 `FatigueAlarmController` 與 `QtAlarmPlaybackBackend`／`QMediaPlayer`／`QAudioOutput`；
  `EngineApplication` 只路由 configure、preview 與 metrics。shutdown 在 camera／analysis producer 停止後冪等 close alarm。
- 已建立 desktop engine 與 packaged smoke 基準；細節見
  `docs/tauri-flutter-migration.md` 與 `docs/benchmarks/`。
- 最近一次完整驗證：Python `739 passed, 2 skipped`、
  alarm controller + engine runtime + desktop settings focused slice 通過、
  Flutter `28 passed`、Flutter analyze 無問題、Flutter Web release 通過、Rust `8 passed`、
  PyInstaller、Tauri release/NSIS、source/bundled engine shutdown、`compileall` 與 `pip check` 均通過。
- 本切片最近兩次重複 benchmark：RSS `256.172/256.113 MiB`、API ready
  `1839.081/2453.306 ms`、`state.get` p50 `20.302/20.048 ms`、synthetic JPEG p50
  `1.173/1.163 ms`；第二次 readiness 視為環境噪聲，不宣稱改善。原始結果見
  `docs/benchmarks/desktop-engine-qmainwindow-removal-2026-08-17-run1.json` 與 `run2.json`。
  前一切片 benchmark：RSS `256.434/256.199 MiB`、API ready
  `1845.500/1850.936 ms`、`state.get` p50 `20.121/20.207 ms`、synthetic JPEG p50
  `1.157/1.146 ms`；原始結果見
  `docs/benchmarks/desktop-engine-runtime-alarm-ownership-2026-08-17-run1.json` 與 `run2.json`。
  本切片 packaged smoke 見
  `docs/benchmarks/packaged-engine-qmainwindow-removal-2026-08-17.json`；installed shell 正常關閉已通過。

以上變更未修改 camera frame routing、worker topology、錄影、警報條件／音量／fallback／strict validation／
錯誤映射／metrics 順序、BLE 樣本、回放、rPPG、疲勞分數、ROI、校準或任何數值閾值。

## 已知剩餘缺口

1. Python engine 已使用 `QApplication + EngineApplication(QObject)` 作 runtime 容器，正式路徑沒有 QWidget。
   `gui/main_window.py` 仍含約 5k 行不可達 legacy widget builders/imports，且 `MainWindow` 相容 alias 尚在；
   下一切片應分離／刪除這些 source，並保持 engine adapter API 與數值契約。
2. 原 Flask dashboard 仍作 localhost 診斷 fallback；它不是正式可見主面板。

## 下一階段執行順序

1. **已完成：移除正式面板的假 benchmark（中量）**
   - Flutter、desktop API state/command 與 legacy Qt code 不再包含示範 benchmark。
   - `scripts/desktop_engine_benchmark.py`、其測試、文件與基準資料維持不變。
   - contract/UI 測試防止示範功能再次進入正式面板。

2. **進行 Qt runtime adapter 抽離（重量）**
   - **已完成：** Windows global hotkey 改由 application-level native event filter 處理，使用
     `RegisterHotKey(HWND=NULL, ...)`，不再依賴 `MainWindow.winId()`／`nativeEvent()`。
   - **已完成：** 可重入 runtime shutdown cleanup 讓 engine `app.shutdown` 直接清理後呼叫
     `QApplication.quit()`；replay shutdown deferral 保留，production 不再有 `closeEvent()`。
   - **已完成：** application-owned `EngineRuntime(QObject)` 承接 live camera 與三種 analysis adapter
     的 QThread／worker ownership、共同 wiring、停止 timeout、join-before-release 與 stale-finish release。
   - **已完成：** `EngineRuntime` 承接錄影與 Replay QThread／worker ownership，並分別保留同步 timeout stop
     與非同步 shutdown deferral 契約。
   - **已完成：** `EngineRuntime` 承接 desktop command、belt tick、auto-capture 與 shutdown defer/retry
     timer ownership；legacy REC、Web restart、Overlay timer 留在其既有 presentation／subsystem owner。
   - **已完成：** `EngineRuntime` 承接 alarm controller 與 Qt multimedia ownership，`EngineApplication` 僅路由
     configure／preview／metrics，cleanup 在 producer 停止後冪等 close。
   - **已完成：** 移除 production `QMainWindow` inheritance，改為 `EngineApplication(QObject)`，加入
     `close_runtime()` 與 legacy window payload round-trip。
   - **下一步：** 分離不可達 widget-only builders/imports，最後移除 `MainWindow` compatibility alias。
   - 每個切片維持 desktop API v2、worker topology 與數值輸出不變。

3. **完成 parity 與效能驗收**
   - 驗證主 WebView、engine child、overlay、視窗控制、設定、camera、recording、replay、BLE、
     notification、alarm 與正常 shutdown。
   - 使用固定 benchmark 參數比較 API ready、process-tree RSS、IPC 與 preview latency。
   - 有 UTA-RLDD 資料集時執行 golden/replay 零漂移檢查。
   - isolated NSIS smoke 已固化為 `scripts.installed_desktop_smoke`：只向 class=`Tauri Window`
     的主視窗送 WM_CLOSE，不得關閉 `Tao Thread Event Target` 等事件泵 helper HWND。

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
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
.venv\Scripts\python -m scripts.installed_desktop_smoke
.venv\Scripts\python -m scripts.desktop_engine_benchmark --port 5001 --samples 10
git diff --check
```

完成前必須 read-back，明確聲明數值行為影響，並只提交代理造成的變更。測試、build、
upstream、認證或 push 失敗時，保留本地狀態並回報確切阻礙，不得宣稱完成。
