# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案定位

無人機駕駛員疲勞狀態監測系統：以一般攝影機做 **非接觸式** 生理與行為監測。結合 MediaPipe 行為疲勞分析與 rPPG（remote photoplethysmography）生理訊號，提供警覺度下降提示。正式桌面主面板與 Overlay 的唯一入口為 Tauri v2 + Flutter Web；Python/MediaPipe/rPPG 為隱藏 engine，PySide6 與 Flask/Socket.IO 僅作隱藏 runtime adapter 與 localhost 診斷／控制 API，不再提供可見主面板或 Qt Overlay。UTA-RLDD replay 為門檻校正與可重現驗證工具，**不是**要把系統改成汽車駕駛分類器。

本檔為代理工作的權威規則來源。跨專案的工作制度（模型調度、派工模板、判斷 rubric、維護協議）在 `~/.claude/rules/`，由全域 CLAUDE.md 自動載入路由，不在此重複。

## 回覆與語言規則

- 所有回覆一律使用繁體中文。
- 程式碼註解、commit message 說明、文件內容以中文為主。
- 技術術語、套件名稱、API 名稱與程式碼本身可保留英文。

## 任務分級與工作流程

依**改動內容**（不是改動行數）分三級。判斷不了就往上取一級。

| 級別 | 判準（碰到任一即屬此級） | 必做 | 可跳過 |
|---|---|---|---|
| **輕量** | 只改文件/註解/README、typo；測試檔內的 typo/註解/訊息文字；scripts 的訊息文字/log/註解（不改變輸出格式與行為） | 改到 `.py` 就跑 `compileall` 該檔；commit+push | 三重審查、完整 pytest、文件同步 |
| **中量** | 單一子系統的程式碼改動且**不碰數值行為**：GUI 佈線、web dashboard、錄影/DB、新增或實質改寫測試邏輯、scripts 行為調整、平台適配且不影響數值（例：相機後端 fallback 順序） | 對應測試檔 pytest + `compileall`；一輪審查（自查 checklist 或 1 個 code-reviewer agent）；commit+push；改到指令/依賴/平台支援則同步 README | 三重審查 |
| **重量** | 碰演算法數值路徑（`rppg/`、`gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、校準、濾波、ROI、分數邏輯）；跨多子系統；啟動流程（`main.py` Qt plugin 順序）；資料 schema；依賴升級 | 完整 `pytest -q`；golden check（見「UTA-RLDD 離線驗證」，本機有資料集才跑，漂移須寫進數值行為影響聲明）；三重審查（見下）；「數值行為影響聲明」（改了什麼、哪些輸出值會變、為什麼可接受）；commit+push；同步 `docs/` 相關報告 | — |

**三重審查**（僅重量級）：3 個並行 subagent 各查一軸——(1) 官方文件/版本相容性、(2) 相關程式碼與部署設定的潛在錯誤、(3) 專案慣例與文件體系。無法用 subagent 時改三輪獨立自查，每輪換一個審查軸、寫下具體發現才算一輪。

**信心門檻**（僅重量級）：沒把握的技術方案先標記風險與替代方案，不直接落地。輕量/中量不需要引用此條。

**Obsidian 同步為選配**：只有使用者在當前 session 明確提供 vault 路徑時才同步，否則只更新 repo 內 `docs/`，不猜路徑、不因此中斷。

## 常用指令

環境優先使用專案內 `.venv`（Windows: `.venv\Scripts\python`；Linux: `.venv/bin/python`）。

```powershell
# 執行正式主程式（Tauri + Flutter；Python engine 由 Tauri 管理）
npm run desktop

# 只啟動隱藏 Python engine（瀏覽器 UI 或測試用）
.venv\Scripts\python main.py --engine

# 測試
.venv\Scripts\python -m pytest -q                                             # 完整（重量級必跑）
.venv\Scripts\python -m pytest tests/test_rppg_signal_processing.py -q       # 單一測試檔
.venv\Scripts\python -m pytest tests/test_rppg_signal_processing.py::test_name

# 匯入 / 語法 / 依賴健檢
.venv\Scripts\python -m compileall -q main.py gui rppg tests
.venv\Scripts\python -m pip check

# rPPG 獨立 demo（不啟動完整 GUI）
python -m rppg.demo_rppg_live
```

Tauri debug build 必須使用 checkout source engine（忽略 `src-tauri/target/debug/engine` 內可能
過期的 sidecar）；release build 才使用 resource directory 的 bundled engine。修改
`spawn_backend` 時須維持此邊界，避免 dev UI 驗到舊版 Python API。

Ubuntu 環境安裝與 Qt xcb runtime 補齊：`bash scripts/setup_ubuntu.sh`。相機黑屏診斷：`scripts/diagnose_camera.py`。

## 環境已知坑（遇錯先查這裡，再決定要不要重試）

- PowerShell 5.1 **沒有** `&&` / `||`：出現 parser error 不是指令壞掉，改 `A; if ($?) { B }` 或用 Bash tool。
- PowerShell `Out-File`/`Set-Content` 預設 UTF-16 LE：寫給其他工具讀的檔案必加 `-Encoding utf8`；寫檔優先用 Write/Edit tool。
- `git push` 可能因 gh credential helper hang 住：解法見 memory `git-push-credential-hang-workaround.md`（GIT_ASKPASS shim + `gh auth token`）。
- 同一子任務最多重試 2 輪，第 2 輪失敗必須換假設或升級模型，不准第 3 輪原樣重試（詳見 `~/.claude/rules/judgment-rubrics.md`）。

## 架構總覽

執行緒模型（每個 worker 跑在自己的 `QThread`，以 Qt Signal/Slot 溝通；Qt-free
`EngineController` 管理 camera config、pipeline/analysis topology、recording/replay/shutdown
state 與 BLE runtime ownership；analysis desired state 在 pipeline 停止時仍由 controller
保存，engine mode 不建立 analysis checkbox 假元件，legacy Qt checkbox 僅為非 production presentation mirror；camera scan/settings/desktop
commands 在 engine mode 直接使用 controller，不建立 camera combo/checkbox 假元件；`MainWindow` 僅作
QThread/signal/Qt multimedia adapter；Overlay 偏好由 Qt-free `OverlayRuntimeState` 保存，
engine mode 不建立 Qt Overlay 或其 checkbox/slider/no-op adapter；replay 的資料夾、jobs、
annotated 與進度投影由 Qt-free `ReplayRuntimeState` 保存，engine mode 不建立 replay
spinbox/checkbox/label 假元件；自動記錄、心跳帶校準與自動採集偏好由 Qt-free
`CapturePreferencesState` 保存，engine mode 不建立其 checkbox/spinbox/button 假元件）：

```
CameraStreamWorker  →  BGR frame queue  →  分析 worker  →  Qt Signals  →  MainWindow adapter
             ↑                  EngineController lifecycle ports                  ↑
                                                          ├→ Overlay（標註預覽）
                                                          ├→ MetricsRecorder（SQLite .db）
                                                          ├→ VideoRecorderWorker（.mp4）
                                                          └→ web_server（Socket.IO 推播）
```

Desktop control 使用 localhost-only API v2（Python、Tauri readiness 與 benchmark 版本必須同步）：
`state.get` 提供 camera/hotkeys/user/alarm/replay 與 `settings_dirty`；設定更新先改 runtime，
`settings.save` 才以同目錄 temporary file + `fsync` + atomic replace 持久化。錯誤統一為
`{success:false,error:{code,message,field?,path?}}`（限 localhost control handler 與 request
validation）。設定引發的 Web server restart 必須在
背景 thread 停服，再以 Qt queued signal 回主執行緒重啟，禁止在 command handler 阻塞 UI。
User/alarm/reset 的 strict JSON validation 位於 Qt-free `gui/desktop_settings_contract.py`；
hotkey 與 camera validation 分別保留在 Qt adapter 與 `gui/engine_controller.py`。
Overlay 的 preview/metrics/locked/all/opacity 與 Tauri 視窗 geometry 以
`OverlayRuntimeState` 為 runtime 與持久化來源；legacy Qt widgets 只在非 engine 路徑作
presentation mirror。`overlay.geometry` 使用平台中立 physical pixel
`{x,y,width,height}`（支援多螢幕負座標）；Tauri 在建立 Overlay 或 Python 權威值明確
變更時套用 geometry，一般輪詢只回報實際位置與尺寸，由 Flutter 在原生值改變時更新
Python runtime，`settings.save` 才持久化。
Replay lifecycle 仍由 `EngineController` 管理；Flutter/Tauri 所需的 replay configuration 與
progress payload 由 `ReplayRuntimeState` 提供，legacy Qt widgets 僅為 mirror，實際 QThread 與
`VideoReplayWorker` 建立仍留在 `MainWindow` adapter。此狀態目前不寫入 settings JSON，維持既有
當次執行設定契約。
採集偏好由 `CapturePreferencesState` 提供 desktop state：`auto_record` 與
`belt_calibration` 仍沿用 settings JSON `toggles` 持久化；自動採集秒數與是否包含心跳帶仍為
session-only，不新增 schema。BLE 啟停、錄影與 `QTimer` side effect 仍由 `MainWindow` adapter
執行；狀態層只保存意圖，adapter 失敗時回滾狀態。此抽取不修改 BLE 樣本、校準器、錄影
worker、相機／分析 worker topology 或任何 rPPG／疲勞數值路徑。

**關鍵：worker 選擇邏輯**（`gui/main_window.py` `_start_*` 方法）：
- rPPG + 疲勞 **同時啟用** → `CombinedWorker`（**單一** MediaPipe FaceLandmarker 實例同時餵給兩個引擎）。
- 只啟用 rPPG → `RppgWorker`；只啟用疲勞 → `FatigueWorker`。
- **絕不**同時跑 `RppgWorker` + `FatigueWorker`：兩個 FaceLandmarker 會搶同一批 frame，導致標註閃爍。修改任一分析路徑時，務必確認三種模式行為一致。

核心運算模組皆為 **pure computation（無 Qt / 無 UI / 無 thread）**，worker 只負責包裝執行緒與訊號：
- `gui/fatigue_engine.py` — 行為疲勞引擎。Frame interleaving 設計：HIGH_FREQ（每幀 EAR/眨眼/凝視/瞳孔/瞇眼）、LOW_FREQ（每 N 幀 head pose solvePnP / 眉間 / PERCLOS）、LATE_STAGE（低權重哈欠 MAR）。MediaPipe 478 點 landmark 索引常數定義於檔案上方。**下視偵測器（2026-07-05）**：視線往下看/頭微低（<10°，pitch gate 管不到）帶動眼皮下垂會使 EAR 假性跌破閉眼門檻、幾秒內誤判中度疲勞（實機發現）；`downgaze_*` 常數驅動的 down-gaze detector（gaze_y+EAR 帶+雙向去抖 0.3s）成立時以 pitch gate 相同語意暫停 EAR 衍生累積（closure/PERCLOS/squint/blink/early_warning lid_balance 條款），真閉眼（EAR<0.45×base）自動解除不漏報；未觸發逐位元回退現況（golden 零漂移已驗證）。詳見 `docs/2026-07-05-downgaze-detector.md`。
- `gui/fatigue_scorer.py` — `FatigueFuser` 融合分數。rPPG 15% + 行為 85%（唯一融合模式；手錶模式已移除）。SQI/quality/ROI 數不足時該 pillar 權重降為 0，由另一 pillar 承擔 100%。輸出 5 段狀態（清醒 / 輕度 / 中度 / 高度 / 極度危險）。**持續閉眼強通道（2026-07-04）**：`compute_closure_s` 純函式（engine 與 scorer 共用）由當前持續閉眼秒數（`FatigueMetrics.eye_closure_sec`）驅動 additive 強化項，加進 engine `fatigue_level`（`w_engine_closure`）與 behavior pillar（`beh_w_eye_closure`），讓頭端正持續閉眼 ~10s 進高度、3s 進中度；`closure_s=0`（無長閉眼，含眨眼/正常短閉眼 <`CLOSURE_ONSET_SEC`）時 additive=+0 逐位元回退現況（golden 零漂移已驗證）。UTA drowsy 無此純閉眼場景故 UTA/golden 指標零變化，價值需實機驗證。詳見 `docs/2026-07-04-eye-closure-channel.md`。
- `gui/personal_profile.py` — **個人清醒基線個人化**（純運算，無 Qt）。`PersonalProfile` / `PersonalProfileStore` / `PersonalBaselineCollector`。把 PERCLOS 狀態/映射門檻、gaze 固定/低掃視門檻、frown/blink-temporal 基線、哈欠嘴開門檻從寫死絕對常數改為相對每位駕駛員的清醒基線。**向後相容鐵律**：`FatigueEngine(personal_profile=None)`（含所有 replay/golden/utarldd_accuracy 路徑）逐位元回退到原常數、原程式路徑，輸出與現況完全一致——改動這些門檻時務必維持此不變量。存 `config/personal_profile/active.json`（不入版控）。GUI「記錄清醒基線」按鈕（自動暫定 + 手動存檔，manual > auto）於 `gui/main_window.py`，經 worker 的 `set_personal_profile` 執行緒安全熱換。詳見 `docs/2026-07-04-personal-baseline-personalization.md`。
- `rppg/rppg_worker.py` — `RppgEngine`：ROI 抽取（forehead / L_cheek / R_cheek / glabella，索引與 base weight 定義於檔案上方）→ POS 演算法 → Butterworth band-pass → Welch PSD → BPM/HRV。BPM 以第一版基準為準（有效 ROI 等權平均、Welch peak，峰值插值 + 輕量平滑）。
- `rppg/rppg_hrv_engine.py` — HRV 計算與信心值。

心率參考的純運算層：`rppg/calibration_watch.py`（`WatchHrHub` / `WatchSample`）+ `rppg/watch_physio.py`（由 hub 樣本計算 HRV/指標，`compute_watch_physio`；`gui/main_window.py` 唯讀顯示用）。這些是心跳帶樣本與「未來 HRV 比對」的共用資料結構（HRV 接口），非疲勞融合輸入。手錶相關已全數移除：HTTP 模式（`WatchHrHttpServer`、`gui/watch_runtime.py`、手動校準對話框）早先移除；接觸式手錶轉接層（`rppg/watch_adapter.py`、`rppg/watch_hrv.py`）於 2026-07-29 移除（已由更精準的 BLE 心跳帶取代）。檔名保留 `Watch*` 前綴僅為 hub 資料結構的歷史命名，與手錶裝置無關。

心跳帶（belt）為 rPPG 的**背景真值校準來源**（非疲勞融合權重）：`rppg/hr_belt_ble.py`（BLE Heart Rate Service `0x180D` / `0x2A37` 協定解析 + `HrBeltBleClient` 背景執行緒，bleak 為 `start()` 時才匯入的選配依賴）。GUI 控制列「心跳帶真值校準（背景）」勾選框啟停（`gui/belt_runtime.py` `BeltRuntime` 管理 hub + belt client）：勾選且 rPPG 運行時，`rppg/adaptive_calibration.py` 的 `OnlineBpmCalibrator`（純運算）以心跳帶 BPM 為真值、比對 rPPG **原始** BPM 的中位殘差，低增益 EMA 慢速微調 offset，透過 `_load_rppg_calibration_version` 回傳的即時版本疊加進既有 rPPG `calibration_loader` 鏈路（bias 模型 `scale*bpm+offset`，只動 offset）。**心跳帶數值絕不進疲勞融合分數**；比對用原始 BPM 故無自我回饋。收斂到足夠信心後（停止時）存成新的 `CalibrationVersionStore` 版本並設為使用中，跨 session 持續改善。系統只有兩種配置：行為+rPPG 判斷疲勞、行為+rPPG+心跳帶校正優化 rPPG（無手錶模式）。**P6a 基礎層（2026-07-04）**：現況校正只動 BPM offset、不碰解析參數；已建立「有護欄自適應」基礎層——`CalibrationParams.rppg_params`（向後相容，預設 None → rPPG 逐位元不變）可持久化學到的 ROI 權重/頻帶，`RppgParamAbEvaluator`（`rppg/adaptive_calibration.py`，純運算）以心跳帶真值對現行 vs 候選參數 BPM 做中位殘差 A/B、「明確更好且連續 N 次才採用、變差回退」。**live 自適應迴圈尚未開啟**：P6b-1 per-ROI 緩衝 seam 已完成（2026-07-04，`collect_rppg_roi_sample_with_means` + `RppgEngine.push_roi_means`/`get_roi_window` 旁路緩衝，additive、既有輸出逐位元不變）；P6b-2 套用層已完成（2026-07-04，`rppg/rppg_worker.py` 的 `resolve_roi_weights_override`/`apply_roi_weights_override`/`resolve_effective_rppg_tuning`：`RppgWorker`/`CombinedWorker` 在 `run()` 啟動時一次性解析 active 校準版本的 `rppg_params.roi_weights`，驗證通過就覆寫 ROI base_weights，`rppg_params=None` 或驗證失敗一律逐位元回退；不做執行中熱切換）；P6b-3a 數值層已完成（2026-07-04）：`collect_rppg_roi_sample_with_means(..., weighted_mix=True)` 新增「有效權重加權混合」分支（override 存在時才由呼叫端傳 True，讓候選 ROI 權重真正影響混合 RGB→BPM；等權語意下候選權重對混合訊號無槓桿），`weighted_mix=False`（預設，所有既有呼叫端含 live worker run() 迴圈）逐位元回退等權平均、`rppg/adaptive_calibration.py` 新增 `recompute_raw_bpm_from_roi_windows()`（純函式，靜態權重、取 ROI 共同時間戳交集不插值、重用 `pos_pulse`/`butter_bandpass`/`welch_peak_hz`，作為 current vs candidate 的公平 A/B 比較器）；**P6b-3b 線上協調層已完成（2026-07-04，預設 OFF）**：`config/hr_belt.json` 新增
`rppg_param_tuning_enabled`（bool，缺項/非 bool 回退 False）開關；`rppg/adaptive_calibration.py`
新增 `RppgParamCoordinator`（純運算狀態機 idle→gated→evaluating→adopt/rollback→cooldown）
與純函式 `propose_roi_weight_candidate()`（單 ROI 殘差提示排序 + 固定步長 + protect
護欄）；`RppgWorker`/`CombinedWorker` 皆新增 `set_candidate_roi_weights()` pending-flag 與
低頻（~1Hz）`_maybe_emit_candidate_bpm()`（`candidate_bpm_ready(t_now, cur_raw_bpm,
cand_raw_bpm)` 訊號；無候選時 early-return，逐幀路徑逐位元不變；`weighted_mix` 由
`roi_override_active = rppg_tuning is not self._tuning` 推導，即「本次 run 是否實際套用了
ROI 權重覆寫」，涵蓋 production 走 `calibration_loader → rppg_params` 的覆寫路徑）；
`gui/main_window.py` 的 `_tick_belt_calibration` 開關為 False（預設）時整條協調層不動作，
開啟時驅動協調層、adopt 時 `save_new_version(offset_bpm=..., rppg_params={"roi_weights":
...})`（與 offset 同版本存檔、設 active，下次啟動生效）。**觸發 gate（使用者裁決 1，
2026-07-04）**：進入 evaluating 只看 offset 是否已穩定——`OnlineBpmCalibrator.state()
.confidence != CONF_LOW`，**殘差大小不再是觸發前置**；候選好壞交由 `RppgParamAbEvaluator`
「明確更好且連續 N 次才 adopt、變差回退」護欄裁決（唯一安全篩子），配合冷卻期（預設
120s）與 evaluating 期間不重複產候選防抖。用 `confidence` 而非 `converged`，是因
`converged` 定義要求殘差 ≤3.0、會排除「offset 穩定但仍有系統性殘差」這個最該調 ROI
權重的情境；`trigger_residual_bpm` 常數已移除。**停止存檔 carry-forward（使用者裁決 2）**：
`_persist_belt_calibration()` 存 offset-only 版本時帶入現行 active 版本既有的 `rppg_params`
（若有），避免同 session 先 adopt ROI 權重、後停止校準時被 offset-only 版本覆蓋遺失；
active 無 `rppg_params`（OFF 路徑常態）時 carried=None、行為與現況一致。**仍存的已知限制**：
尚無逐 ROI 對心跳帶真值的即時殘差來源，live 呼叫端固定傳空 `per_roi_residual_hint`，
候選方向退化為「挑目前權重最小者探索」的啟發式（adopt/rollback 仍由心跳帶真值 A/B
決定，護欄未繞過）；live 迴圈端到端（需心跳帶硬體）仍屬 P6b 待辦。**P6b-4 離線驗證
基礎設施已完成（2026-07-04）**：`config/hr_belt.json` 新增 `capture_enabled`（bool，
缺項/非 bool 回退 False）開關；開啟時 `gui/main_window.py` 的 `_start_belt_calibration`
透過 `gui/belt_runtime.py` 的 `BeltRuntime.create_truth_capture_writer()` 建立
`rppg/belt_truth_capture.py` 的 `BeltTruthCaptureWriter`（純 I/O 模組，唯讀觀察既有
資料流，不動任何數值路徑），把每幀 per-ROI RGB 均值與當下心跳帶 BPM（可能 None）
對齊寫入 `recordings/belt_truth_capture/*.jsonl`；`RppgWorker`/`CombinedWorker` 皆新增
`set_belt_truth_capture()` pending-flag 與 `_maybe_capture_belt_truth()`（writer=None
時 early-return，逐幀路徑逐位元不變，同 `_maybe_emit_candidate_bpm` 的 OFF 早退模式）。
`scripts/rppg_param_replay.py`（`python -m scripts.rppg_param_replay <capture 檔>
--candidate-weights '{"forehead":0.5,...}'`）讀 capture 檔，用
`rppg/adaptive_calibration.py` 的 `recompute_raw_bpm_from_roi_windows()` 對整段錄製做
滑動視窗，分別以現行/候選 ROI 權重重算 BPM、對心跳帶真值算 MAE，回報哪組權重更接近
真值——不需心跳帶硬體連線即可離線驗證候選權重，是開 live 自適應迴圈前的驗證工具。
裝置設定走 `config/hr_belt.json`（機器特定、不入版控，`load_hr_belt_config()`
容錯載入）；連線中超過 `HR_STALE_AFTER_SEC` 無有效心率由 `hr_is_stale()` 判定並在
GUI/dashboard 顯示警告；免 GUI 診斷用 `python -m scripts.hr_belt_monitor`。實機 GATT
對照見 `docs/heart_rate_belt_bluetooth_gatt_profile.md`。

## 設定與校準檔（config/）

- `config/mediapipe_tuning.json`（**納入版控**）— 集中所有可調參數：`face_landmarker`（confidence）、`rppg_roi`（ROI 權重/姿態懲罰/遮擋門檻/EMA 平滑/jitter 門檻）、`quality`（品質分數組合權重）、`blendshape`（baseline 校準）、`active_profile` + `profiles`（`default` / `stable_indoor`（預設）/ `low_light` / `high_motion`）。切換 profile 需重啟 worker，FaceLandmarker options **不做熱更新**。`canonical_roi_warp_enabled` 為實驗開關，預設關閉（正式比較前保持關閉）。
- `config/mediapipe_calibration.json`、`config/rppg_calibration/`、`config/personal_profile/` — 個人化/環境 baseline、rPPG BPM 校準版本、個人清醒基線 profile，**不納入版控**（機器/使用者特定）。

修改演算法時的最高原則：**優先維持 rPPG、疲勞判定、濾波、ROI 與分數邏輯的數值行為**，不做無關重構；任何會影響數值結果的平台適配須先明確說明（即重量級任務的「數值行為影響聲明」）。

## 影片回測（含 UTA-RLDD 離線驗證）

回測模組本質是**通用影片回測**：把任何影片當「離線鏡頭」餵進與即時路徑相同的疲勞引擎，**不動即時攝影機 worker**。核心在 `gui/video_replay.py`（`run_replay_batch(..., labeled=bool)`；QThread 包裝為 `VideoReplayWorker`），使用影片 FPS 產生 deterministic timestamp，前約 5 秒為 `CALIBRATING`。UTA-RLDD 只是其中一個驗證資料集，非模組目的。純運算類別為 `ReplayVideo` / `ReplayVideoSummary` / `ReplayBatchResult`；UTA-RLDD 專屬邏輯（`discover_utarldd_videos`、`parse_utarldd_label`、`UTARLDD_LABELS`、validation 報表）為保留的 preset 命名。兩條入口：

- **通用**（單一影片檔或任意資料夾、無需 label）：`scripts/video_replay.py`（= `python -m scripts.video_replay`），`labeled=False`，輸出 `recordings/replay_runs/`，略過驗證報表；接受 `.mp4/.mov/.avi/.mkv/.m4v/.webm`；路徑不含影片會 raise 可行動錯誤（不再靜默產空報表）。
- **UTA-RLDD 情境**：`scripts/utarldd_replay.py`，`labeled=True`（預設），依 subject/label 資料夾結構解析、官方 label `0=Alert`/`5=Low Vigilant`/`10=Drowsy`、輸出 `recordings/utarldd_runs/` 並產把 `0/5/10` 當序位真值的 validation CSV。GUI 對應區塊為「影片回測」（`gui/main_window.py`，`_replay_*` 屬性）。

修改 replay 路徑時：`labeled=True` 分支須維持既有 UTA-RLDD 行為（輸出路徑、檔名前綴、validation 產生），紅線仍為不改 `rppg/`/`fatigue_engine`/`fatigue_scorer` 數值行為。
回放資料夾、平行數、標註開關與 desktop progress state 位於 Qt-free
`gui/replay_runtime_state.py`；這只移動 presentation ownership，不改 deterministic timestamp、
worker 參數、標註輸出、報表或分析數值。

```powershell
.venv\Scripts\python -m scripts.video_replay "<影片檔或資料夾>" --max-frames 300 --jobs 4
.venv\Scripts\python -m scripts.utarldd_replay "<資料夾>" --subject 01,02 --label 0,5,10 --jobs 4
```

輸出至 `recordings/utarldd_runs/<timestamp>/`：每片一個 `.db`，整批含 summary CSV、validation CSV、full CSV、HTML 報表與 manifest。`--jobs N`（GUI 上限 4）走多進程並停用預覽與標註影片輸出。既有 summary CSV 可用 `scripts/utarldd_csv_report.py` 直接轉 HTML。**注意**：UTA-RLDD label 是整段影片類別、非逐幀 ground truth，不能取代真人測試。

**Golden-output 回歸基準**（`scripts/utarldd_golden.py`）：重量級改動後跑 `check`，機械偵測數值漂移；比對子集/欄位/容差在 `tests/golden/utarldd_golden_config.json`，baseline 在 `tests/golden/utarldd_golden_baseline.json`（皆入版控）。漂移若屬預期，寫進數值行為影響聲明後以 `create --force` 重建 baseline。

```powershell
.venv\Scripts\python -m scripts.utarldd_golden check "<UTA-RLDD 資料夾>"    # 0=過, 1=漂移, 2=執行失敗
.venv\Scripts\python -m scripts.utarldd_golden create "<UTA-RLDD 資料夾>" --force
```

## 平台差異

- 相機後端：Windows 自動優先 `DSHOW` → fallback `MSMF`；Linux 用 `V4L2`（Linux 優先要求 MJPG 以取得 30 FPS）。相機名稱在 Windows 用 `pygrabber`（Windows-only 選配，Linux 不執行其 import）。**勿把平台專用後端邏輯混在一起改**。
- `main.py` 在建立 `QApplication` **之前** 會把 Qt platform plugin 路徑固定回 PySide6（`_prefer_pyside6_qt_plugins`），避免 OpenCV wheel 的 `cv2/qt/plugins` 蓋掉 PySide6 的 xcb plugin；Linux 缺 xcb runtime 套件時回傳 exit code 78 並印安裝指引。修改啟動流程時勿破壞此順序。

## 測試慣例

`tests/` 使用 `pytest`，每個測試檔對應一個子系統（rPPG 訊號處理、MediaPipe 增強、校準、UTA-RLDD replay、watch adapter、web playback / socketio dashboard、alarm、Ubuntu 相機支援）。新增分析邏輯時，優先在對應測試檔擴充純運算層測試（engine / scorer / calibration），避免依賴實體相機或 Qt event loop。

## 文件

技術報告集中在 `docs/`（多份 `.md` 皆有對應 `.pdf`）。PDF 由 `scripts/build_technical_report_pdfs.py`、`scripts/build_practical_project_report_pdf.py`、`scripts/build_rppg_pdf.py` 產生（需 `reportlab`，見 `requirements-dev.txt`）。變更安裝方式、平台支援、執行命令或必要依賴時，須同步更新 `README.md`。編譯 `.exe` 僅在使用者明確要求該次任務產出 exe 時執行。

## 編碼與設計規範

- 使用 4 個空白縮排，保持既有風格，避免無關重構。
- 新增或調整函式時，若屬關鍵流程或錯誤處理，應使用既有 logger（`logging.getLogger(__name__)`）記錄。
- 前端介面必須使用 responsive 寫法，不寫死尺寸。
- 新增檔案時，名稱與責任保持單一明確。

## Git 規範

- 工作樹可能不是乾淨的，禁止覆蓋或回退非本次任務造成的變更；只修改與當前需求直接相關的檔案。
- 任務完成後自動執行 `git add`（只加本次任務的檔案）、`git commit`、`git push`（各級皆適用）。
- commit 格式遵循 Conventional Commits，例如 `fix(deploy): ...`、`docs(agents): ...`；主旨與說明以中文為主，可保留必要英文技術名詞。

## 安全與設定

- 秘密資訊以 `.env`、systemd `EnvironmentFile` 或主機環境變數管理，不寫入版本控制。
- 不得提交資料庫密碼、Discord token、SmilePay key 或任何第三方服務密鑰；不得硬編碼個人機器的絕對路徑。
- `config/mediapipe_calibration.json` 與 `config/rppg_calibration/` 為機器/使用者特定校準，不納入版控；`models/` 下模型檔視為執行必要資產，調整載入方式時須保持相對路徑可攜性。
- 遠端操作若遇到明確可判定的權限/擁有者錯誤、既有目錄不存在、build 產物權限錯誤、systemd 舊設定殘留等常見阻塞，應優先嘗試安全修復後再繼續；僅在高風險操作、資料不可逆變更或需求不明確時才中止回問。
- migration 回滾需特別標記風險；若 schema 變更無法自動回滾，需提出手動還原方案。

## 例外與衝突處理

- 若使用者有明確新指示，優先以使用者當前指示為準。
- 若規則因工具、權限或環境限制無法完整執行，需明確回報阻塞點，再採用最接近規則的方案。
