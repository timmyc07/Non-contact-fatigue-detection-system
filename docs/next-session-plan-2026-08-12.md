# 明日續作計畫

日期：2026-08-11
目前狀態：本日停止實作；保留工作樹中的既有變更，明日從跨棧整合與架構收斂繼續。

## 已確認狀態

- 正式 UI 入口已是 Tauri v2 + Flutter Web；`--legacy-ui` 會拒絕，`--engine` 才啟動隱藏的 Python/Qt engine runtime。
- Flutter：`flutter test`、`flutter analyze`、`flutter build web --release` 已通過。
- Rust/Tauri：`cargo test --manifest-path src-tauri/Cargo.toml`（5 passed）與 `cargo build --manifest-path src-tauri/Cargo.toml` 已通過。
- `src-tauri/tauri.conf.json` 已完成 JSON 解析檢查。
- 尚未完成真正的 Tauri runtime smoke；目前直接執行 `flutter` 不在 PATH，啟動腳本只會嘗試 `C:\tools\flutter\bin`。

## 明日執行順序

1. **完成 runtime smoke**
   - 確認 Flutter SDK 路徑，必要時設定明確的 `PATH` 或啟動參數。
   - 執行 `powershell -ExecutionPolicy Bypass -File .\scripts\start_desktop.ps1` 或 `npm run desktop`。
   - 驗證主 WebView、Python engine child、overlay、視窗拖曳/最小化/最大化/關閉，以及正常 shutdown。
   - 若失敗，記錄確切錯誤並修正啟動文件或腳本的環境假設。

2. **收斂 controller 單一狀態來源**（Major）
   - 審查 `gui/main_window.py` 的 `_pipeline_running`、`_recording`、`_replay_thread`、`_replay_stopping` 與 `EngineController` 的重複狀態。
   - 讓 desktop state/commands 讀取 controller 的正式 lifecycle state，或明確將目前 API 標記為 transitional adapter。
   - 保持既有 engine 行為、rPPG/疲勞數值、錄影與 replay 行為不變。

3. **補 command-level integration tests**
   - 測試 desktop command -> controller -> engine adapter 的實際 wiring。
   - 移除測試中手動同步 MainWindow 私有旗標才能通過的假陽性情境。
   - 覆蓋 settings save、pipeline start/stop、recording、replay、shutdown 與錯誤回報。

4. **整理 BLE ownership 契約**（Moderate）
   - 檢查 `BeltRuntimePort` 是否應縮窄為 controller 實際需要的 start/stop API，或完整移轉 `hub/status/writer` 責任。
   - 確保心跳帶資料、校準與 rPPG 校正流程仍由既有 runtime 管理，不能改變數值結果。

5. **同步架構文件與測試命名**
   - 更新 `docs/system_architecture_algorithm_map.md`，明確描述 Flutter/Tauri 主 UI 與 hidden Qt engine runtime 的邊界。
   - 檢查 `docs/tauri-flutter-migration.md`、`CLAUDE.md` 的 controller-backed state 描述是否與實作一致。
   - 視範圍將 `tests/test_engine_controller_camera.py` 改為能反映 lifecycle/runtime coverage 的名稱，避免不必要的大型重構。

## 驗收命令

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m compileall -q main.py gui rppg tests
.venv\Scripts\python -m pip check
C:\tools\flutter\bin\flutter.bat test
C:\tools\flutter\bin\flutter.bat analyze
C:\tools\flutter\bin\flutter.bat build web --release
cargo test --manifest-path src-tauri/Cargo.toml
cargo build --manifest-path src-tauri/Cargo.toml
git diff --check
```

完成前必須重新讀取修改區段，確認未改動演算法、校準、ROI、分數閾值或 replay golden 行為；若 runtime smoke、測試、上游遠端或認證失敗，保留本地狀態並在回報中列出確切阻礙，不得宣稱完成。

## 工作樹注意事項

本日開始時已存在下列未提交/未追蹤變更：`CLAUDE.md`、`docs/tauri-flutter-migration.md`、`docs/system_architecture_algorithm_map.md`、`gui/engine_controller.py`、`gui/main_window.py`、`tests/test_desktop_settings_api.py`、`tests/test_engine_controller_camera.py`、`tests/test_engine_controller_lifecycle.py`、`docs/benchmarks/desktop-engine-lifecycle-2026-08-11.json`。明日處理前先重新執行 `git status --short`，不要覆蓋或誤提交非本次代理產生的變更。
