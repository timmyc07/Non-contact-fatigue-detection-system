# 下一階段續作計畫

更新日期：2026-08-18

本切片起始基準：`9a921c8 refactor(desktop): 抽離 runtime timer ownership`

目前狀態：live camera、analysis、錄影與 Replay QThread／worker、production runtime QTimer，以及
alarm/Qt multimedia ownership 已由 application-owned `EngineRuntime` 保存；production adapter 已改為
`EngineApplication(QObject)`，不再建立 `QMainWindow`／QWidget。本次已移除舊 QSS/theme token、主頁面 builders、
dashboard/monitor/belt/replay/settings renderer、widget imports 與 presentation compatibility methods；
個人基線顯示狀態改由 desktop state 的 `profile_status` 提供。

## 本階段完成狀態

- 正式產品的唯一可見入口已是 Tauri v2 + Flutter Web；一般執行由 Tauri 啟動
  `main.py --engine`，`--legacy-ui` 會明確拒絕。
- engine mode 不顯示 Qt 主視窗或 Qt Overlay，也不建立 menu、dashboard、status bar、
  monitor、心跳帶、camera、recording、profile 等 Qt 假控件。
- `EngineController` 與 Qt-free runtime state 已承接 camera、analysis topology、pipeline、
  recording、replay、shutdown、BLE、overlay、capture 及 Web preference 的正式狀態。
- Python/Qt production 路徑只保留 `QApplication`、`QThread`、`QTimer`、signal/slot、image transport 與
  `EngineApplication(QObject)` runtime adapter；`gui/main_window.py` 已無 widget imports 或 widget 欄位存取。
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
  僅保留 worker-specific callback、queue／routing 與 headless state side effect。
- 錄影與 Replay QThread／worker ownership 也已移入 `EngineRuntime`。錄影維持原 request-stop、2000ms wait
  timeout 與 late-finish cleanup；Replay 維持非同步 cooperative stop、deterministic timestamp、報表輸出與
  shutdown deferral，完成後由 adapter release callback 重入 controller／shutdown。
- desktop command drain、心跳帶 1 秒 tick、自動採集 one-shot 與 shutdown defer/retry 的 QTimer ownership
  已移入 `EngineRuntime`。`EngineApplication` 只保留既有 callback；REC presentation timer 已移除，Web restart 與
  Overlay 自有排程維持各自既有 owner。
- `EngineRuntime` 已承接 `FatigueAlarmController` 與 `QtAlarmPlaybackBackend`／`QMediaPlayer`／`QAudioOutput`；
  `EngineApplication` 只路由 configure、preview 與 metrics。shutdown 在 camera／analysis producer 停止後冪等 close alarm。
- 已建立 desktop engine 與 packaged smoke 基準；細節見
  `docs/tauri-flutter-migration.md` 與 `docs/benchmarks/`。
- 最近一次完整驗證（含 Flutter-to-engine 命令契約檢查）：Python `757 passed, 2 skipped`、
  Flutter `28 passed`、Rust `8 passed`；Flutter analyze、Web release build、
  `compileall` 與 `pip check` 均通過；PyInstaller、Tauri release/NSIS 與
  source/bundled engine shutdown 也已通過。
- 2026-08-18 已移除 legacy Qt `PreviewOverlayWindow` 與其 offscreen 測試；正式 Overlay 僅由 Tauri/Flutter 建立。
- 移除 legacy Qt 視覺模組後的兩次 headless benchmark：RSS
  `253.297/252.980 MiB`、API ready `2464.125/2438.245 ms`、`state.get` p50
  `20.355/20.255 ms`、synthetic JPEG p50 `1.305/1.314 ms`；此為 noisy local
  baseline，不宣稱效能改善。證據位於
  `docs/benchmarks/desktop-engine-headless-qt-visual-removal-2026-08-18-run1.json`
  與 `run2.json`。
  前一切片原始結果見
  `docs/benchmarks/desktop-engine-qmainwindow-removal-2026-08-17-run1.json` 與 `run2.json`。
- 完整 PyInstaller、Tauri release/NSIS 與 isolated installed smoke 已通過：install exit `0`、
  desktop API v2、單一可見 `Tauri Window`、標題 `疲勞監測操作台`、`app.shutdown` 成功、engine 與 shell exit `0`、uninstall exit `0`，安裝目錄已移除；另已直接擷取 release WebView 畫面並點擊驗證主面板、心跳帶、歷史回放與系統設定導覽。主面板開始／停止已透過 packaged sidecar 驗證 1280×720／30 FPS 的 fatigue pipeline 與 Overlay 建立；仍待 BLE／資料集下的完整互動驗收，並應持續監控 PyInstaller sidecar 的冷啟動時序。
- 2026-08-18 已新增可重跑的 `scripts.desktop_hardware_smoke`。本機 `WebCamera` 的 raw、
  fatigue、rPPG、combined 四種 mode 均實測通過：desktop API v2、camera select、
  1280×720／30 FPS、對應 `frame_source`、pipeline start/stop 與 engine shutdown。
  證據分別為 `docs/benchmarks/desktop-hardware-smoke-2026-08-18-raw.json`、
  `...-fatigue.json`、`...-rppg.json` 與 `desktop-hardware-smoke-2026-08-18.json`。
  本機 BLE monitor 可進入掃描，
  但 4 秒內未收到心跳帶 notification，尚不能宣稱真實 BLE 資料流已驗證。

以上變更未修改 camera frame routing、worker topology、錄影、警報條件／音量／fallback／strict validation／
錯誤映射／metrics 順序、BLE 樣本、回放、rPPG、疲勞分數、ROI、校準或任何數值閾值。

## 已知剩餘缺口

1. Python engine 已使用 `QApplication + EngineApplication(QObject)` 作 runtime 容器，正式路徑沒有 QWidget。
   舊主頁面 builders、QSS、QtWidgets imports、presentation compatibility methods 與
   `MainWindow = EngineApplication` alias 已移除；測試與 benchmark 已改用正式類名。
2. 原 Flask dashboard 仍作 localhost 診斷 fallback；它不是正式可見主面板。
3. 本機沒有 UTA-RLDD 資料集，因此本切片無法執行 golden/replay；演算法與數值路徑未修改。
4. 需要實際配戴並可送出 notification 的 BLE 心跳帶，才能完成 end-to-end 心率、接觸狀態與
   rPPG 真值校準的實機驗收；先以 `scripts.hr_belt_monitor --duration 60 --use-config` 確認硬體。

## 下一階段執行順序

1. **已完成：移除正式面板的假 benchmark（中量）**
   - Flutter、desktop API state/command 與 legacy Qt code 不再包含示範 benchmark。
   - `scripts/desktop_engine_benchmark.py` 已改用正式 `EngineApplication` 類名，仍是唯一效能量測入口。
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
   - **已完成：** 清理 renderer helper/import 與 widget callsites，個人基線狀態改由 headless state 提供。
   - **已完成：** 移除 `MainWindow` compatibility alias，測試與 benchmark 改用 `EngineApplication`。
   - **已完成：** cleanup 後全量跨端測試、packaged smoke 與兩次效能 benchmark。
   - 每個切片維持 desktop API v2、worker topology 與數值輸出不變。

3. **繼續 parity 與效能驗收**
   - **已完成（source engine）：** 使用 `scripts.desktop_hardware_smoke` 驗證 WebCamera 的 raw/
     combined camera lifecycle 與 metrics routing；腳本不持久化設定、不改演算法數值。
   - **下一步：** 使用已配戴 BLE 心跳帶驗證 notification、接觸狀態與 rPPG 真值校準；再以
     packaged Tauri 主 WebView 驗證 camera、overlay、視窗控制、設定、recording、replay、
     notification、alarm 與正常 shutdown。
   - **已完成：** 使用固定 benchmark 參數比較 API ready、process-tree RSS、IPC 與 synthetic preview latency。
   - **待資料集：** 有 UTA-RLDD 資料集時執行 golden/replay 零漂移檢查。
   - isolated NSIS smoke 已固化為 `scripts.installed_desktop_smoke`：只向 class=`Tauri Window`
     的主視窗送 WM_CLOSE，不得關閉 `Tao Thread Event Target` 等事件泵 helper HWND。

## 2026-08-18 最新驗證

- 以目前 commit `532fb3e` 重新建置 Flutter Web release 與 Tauri NSIS；Rust release build 與 8 項 Rust tests 全部通過。Flutter 僅出現既有 `socket_io_common` WebAssembly dry-run warning，JavaScript Web build 成功。
- 使用新產出的 NSIS bundle 做隔離安裝：API v2、唯一可見 `Tauri Window`（標題「疲勞監測操作台」）、`app.shutdown`、engine/shell 正常結束、卸載與安裝目錄移除全部通過。
- 重新執行 `scripts.desktop_hardware_smoke` 的 `raw`、`fatigue`、`rppg`、`combined` 四種模式；每種皆為 1280x720、30 FPS、正確 `frame_source`，並完成 pipeline start/stop 與 source engine shutdown。
- 以上驗證涵蓋生命週期與 routing，不等同於 rPPG／疲勞數值精準度、BLE notification 或 UTA-RLDD golden 證據；本次沒有修改任何數值演算法或校準路徑。
- 目前版本 headless benchmark（10 samples、3 warmup）已保存至 `docs/benchmarks/desktop-engine-current-2026-08-18-run3.json`：API ready 1853.905 ms、engine RSS 254.25 MiB、`state.get` p50 20.221 ms、synthetic JPEG encode p50 1.194 ms。結果與既有 run1/run2 同量級，僅作本機 noisy baseline，不宣稱跨機器效能改善。
- README 的現行操作說明已同步為 Tauri/Flutter 唯一可見面板與 headless engine：相機設定、回放、心跳帶、LAN Web fallback、Linux 診斷與效能說明不再把已移除的 Qt GUI 當正式入口。
- `tests/test_flutter_command_contract.py` 已改為驗證 Flutter 可見控制項的完整 21-command 集合，並確認每個 command 都存在於 engine desktop handler，避免 migration 遺漏非核心設定或回放控制。

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
.venv\Scripts\python -m scripts.desktop_hardware_smoke --camera-index 0 --analysis-mode combined --port 5012
git diff --check
```

完成前必須 read-back，明確聲明數值行為影響，並只提交代理造成的變更。測試、build、
upstream、認證或 push 失敗時，保留本地狀態並回報確切阻礙，不得宣稱完成。
