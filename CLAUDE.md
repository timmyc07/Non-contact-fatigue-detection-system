# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案定位

無人機駕駛員疲勞狀態監測系統：以一般攝影機做 **非接觸式** 生理與行為監測。結合 MediaPipe 行為疲勞分析與 rPPG（remote photoplethysmography）生理訊號，提供警覺度下降提示。桌面 GUI（PySide6）+ Web dashboard（Flask/Socket.IO）。UTA-RLDD replay 為門檻校正與可重現驗證工具，**不是**要把系統改成汽車駕駛分類器。

`AGENTS.md` 為本專案更完整的工作規則參考；本檔為代理工作的權威規則來源，並補充架構與指令速查。

## 回覆與語言規則

- 所有回覆一律使用繁體中文。
- 程式碼註解、commit message 說明、文件內容以中文為主。
- 技術術語、套件名稱、API 名稱與程式碼本身可保留英文。

## 最高優先級工作流程

- 任何變更前，先閱讀相關程式碼、現有文件與部署設定。
- 任何變更前，先查詢最新官方技術文件，確認方案可行後再實作。
- 只採用信心值超過 90% 的技術與操作；低於門檻時先標記風險。
- 任何變更前，先完成三重審查。
- 任務完成後，必須執行必要驗證（至少 `pytest`，見「常用指令」）。
- 任務完成後，必須自動 commit 並 push 到 GitHub。
- 任務完成後，必須同步更新 repo 內文件與 Obsidian 筆記。
- 若專案需要編譯成 `.exe`，每次完成改動後都必須自動編譯一次。

## 三重審查要求

- 審查 1：查詢最新官方或主要技術文件，確認方案與版本相容性。
- 審查 2：檢查相關程式碼、部署設定與潛在錯誤。
- 審查 3：檢查是否符合專案慣例、文件體系與維運需求。
- 若可用 subagent，預設使用 3 個 agent 並行審查。
- 若因工具或上層規則無法使用 subagent，改以三輪獨立審查流程替代，仍需先完成審查再修改。

## 信心門檻

- 僅套用信心值超過 90% 的技術、修正與部署操作。
- 若無法達到此門檻，先提出阻塞點與替代方案，不直接落地。

## 常用指令

環境優先使用專案內 `.venv`（Windows: `.venv\Scripts\python`；Linux: `.venv/bin/python`）。

```powershell
# 執行主程式（桌面 GUI）
python main.py

# 測試（變更 Python 後至少執行）
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests/test_rppg_signal_processing.py -q       # 單一測試檔
.venv\Scripts\python -m pytest tests/test_rppg_signal_processing.py::test_name # 單一測試

# 匯入 / 語法 / 依賴健檢
.venv\Scripts\python -m compileall -q main.py gui rppg tests
.venv\Scripts\python -m pip check

# rPPG 獨立 demo（不啟動完整 GUI）
python -m rppg.demo_rppg_live
```

Ubuntu 環境安裝與 Qt xcb runtime 補齊：`bash scripts/setup_ubuntu.sh`。相機黑屏診斷：`scripts/diagnose_camera.py`（詳見 README「rPPG BPM 校準」與診斷段落）。

## 架構總覽

執行緒模型（每個 worker 跑在自己的 `QThread`，以 Qt Signal/Slot 溝通，`MainWindow` 為協調者）：

```
CameraStreamWorker  →  BGR frame queue  →  分析 worker  →  Qt Signals  →  MainWindow
                                                          ├→ Overlay（標註預覽）
                                                          ├→ MetricsRecorder（SQLite .db）
                                                          ├→ VideoRecorderWorker（.mp4）
                                                          └→ web_server（Socket.IO 推播）
```

**關鍵：worker 選擇邏輯**（`gui/main_window.py` `_start_*` 方法）：
- rPPG + 疲勞 **同時啟用** → `CombinedWorker`（**單一** MediaPipe FaceLandmarker 實例同時餵給兩個引擎）。
- 只啟用 rPPG → `RppgWorker`；只啟用疲勞 → `FatigueWorker`。
- **絕不**同時跑 `RppgWorker` + `FatigueWorker`：兩個 FaceLandmarker 會搶同一批 frame，導致標註閃爍。修改任一分析路徑時，務必確認三種模式行為一致。

核心運算模組皆為 **pure computation（無 Qt / 無 UI / 無 thread）**，worker 只負責包裝執行緒與訊號：
- `gui/fatigue_engine.py` — 行為疲勞引擎。Frame interleaving 設計：HIGH_FREQ（每幀 EAR/眨眼/凝視/瞳孔/瞇眼）、LOW_FREQ（每 N 幀 head pose solvePnP / 眉間 / PERCLOS）、LATE_STAGE（低權重哈欠 MAR）。MediaPipe 478 點 landmark 索引常數定義於檔案上方。
- `gui/fatigue_scorer.py` — `FatigueFuser` 融合分數。預設 rPPG 15% + 行為 85%；watch 模式為行為 70% + 手錶 30%（rPPG 停用）。SQI/quality/ROI 數不足時該 pillar 權重降為 0，由另一 pillar 承擔 100%。輸出 5 段狀態（清醒 / 輕度 / 中度 / 高度 / 極度危險）。
- `rppg/rppg_worker.py` — `RppgEngine`：ROI 抽取（forehead / L_cheek / R_cheek / glabella，索引與 base weight 定義於檔案上方）→ POS 演算法 → Butterworth band-pass → Welch PSD → BPM/HRV。BPM 以第一版基準為準（有效 ROI 等權平均、Welch peak，峰值插值 + 輕量平滑）。
- `rppg/rppg_hrv_engine.py` — HRV 計算與信心值。

手錶（watch）路徑為選配的 HR 參考來源：`rppg/watch_*.py` + `gui/watch_runtime.py`，僅在 watch 模式或 rPPG 校準時使用。

心跳帶（belt）為 rPPG 的**背景真值校準來源**（非疲勞融合權重）：`rppg/hr_belt_ble.py`（BLE Heart Rate Service `0x180D` / `0x2A37` 協定解析 + `HrBeltBleClient` 背景執行緒，bleak 為 `start()` 時才匯入的選配依賴）。GUI 控制列「心跳帶真值校準（背景）」勾選框啟停：勾選且 rPPG 運行（非手錶模式）時，`rppg/adaptive_calibration.py` 的 `OnlineBpmCalibrator`（純運算）以心跳帶 BPM 為真值、比對 rPPG **原始** BPM 的中位殘差，低增益 EMA 慢速微調 offset，透過 `_load_rppg_calibration_version` 回傳的即時版本疊加進既有 rPPG `calibration_loader` 鏈路（bias 模型 `scale*bpm+offset`，只動 offset）。**心跳帶數值絕不進疲勞融合分數**；比對用原始 BPM 故無自我回饋。收斂到足夠信心後（停止時）存成新的 `CalibrationVersionStore` 版本並設為使用中，跨 session 持續改善。心跳帶校準與手錶模式互斥（皆用 `WatchHrHub`，進手錶模式前 `_ensure_watch_source` 會先 `_stop_belt_calibration`）。裝置設定走 `config/hr_belt.json`（機器特定、不入版控，`load_hr_belt_config()` 容錯載入）；連線中超過 `HR_STALE_AFTER_SEC` 無有效心率由 `hr_is_stale()` 判定並在 GUI/dashboard 顯示警告；免 GUI 診斷用 `python -m scripts.hr_belt_monitor`。實機 GATT 對照見 `docs/heart_rate_belt_bluetooth_gatt_profile.md`。

## 設定與校準檔（config/）

- `config/mediapipe_tuning.json`（**納入版控**）— 集中所有可調參數：`face_landmarker`（confidence）、`rppg_roi`（ROI 權重/姿態懲罰/遮擋門檻/EMA 平滑/jitter 門檻）、`quality`（品質分數組合權重）、`blendshape`（baseline 校準）、`active_profile` + `profiles`（`default` / `stable_indoor`（預設）/ `low_light` / `high_motion`）。切換 profile 需重啟 worker，FaceLandmarker options **不做熱更新**。`canonical_roi_warp_enabled` 為實驗開關，預設關閉（正式比較前保持關閉）。
- `config/mediapipe_calibration.json`、`config/rppg_calibration/` — 個人化/環境 baseline 與 rPPG BPM 校準版本，**不納入版控**（機器/使用者特定）。

修改演算法時的最高原則（見 `AGENTS.md`）：**優先維持 rPPG、疲勞判定、濾波、ROI 與分數邏輯的數值行為**，不做無關重構；任何會影響數值結果的平台適配須先明確說明。

## UTA-RLDD 離線驗證

`scripts/utarldd_replay.py`（= `python -m scripts.utarldd_replay`）把 UTA-RLDD 影片當「離線鏡頭」批次回放，**不動即時攝影機 worker**。使用影片 FPS 產生 deterministic timestamp，前約 5 秒為 `CALIBRATING`。官方 label：`0=Alert`、`5=Low Vigilant`、`10=Drowsy`。GUI 也有對應「UTA-RLDD 影片測試」區塊（`gui/utarldd_replay.py`）。

```powershell
.venv\Scripts\python -m scripts.utarldd_replay "<資料夾>" --max-videos 1 --max-frames 300
.venv\Scripts\python -m scripts.utarldd_replay "<資料夾>" --subject 01,02 --label 0,5,10 --jobs 4
```

輸出至 `recordings/utarldd_runs/<timestamp>/`：每片一個 `.db`，整批含 summary CSV、validation CSV、full CSV、HTML 報表與 manifest。`--jobs N`（GUI 上限 4）走多進程並停用預覽與標註影片輸出。既有 summary CSV 可用 `scripts/utarldd_csv_report.py` 直接轉 HTML。**注意**：UTA-RLDD label 是整段影片類別、非逐幀 ground truth，不能取代真人測試。

## 平台差異

- 相機後端：Windows 自動優先 `DSHOW` → fallback `MSMF`；Linux 用 `V4L2`（Linux 優先要求 MJPG 以取得 30 FPS）。相機名稱在 Windows 用 `pygrabber`（Windows-only 選配，Linux 不執行其 import）。**勿把平台專用後端邏輯混在一起改**。
- `main.py` 在建立 `QApplication` **之前** 會把 Qt platform plugin 路徑固定回 PySide6（`_prefer_pyside6_qt_plugins`），避免 OpenCV wheel 的 `cv2/qt/plugins` 蓋掉 PySide6 的 xcb plugin；Linux 缺 xcb runtime 套件時回傳 exit code 78 並印安裝指引。修改啟動流程時勿破壞此順序。

## 測試慣例

`tests/` 使用 `pytest`，每個測試檔對應一個子系統（rPPG 訊號處理、MediaPipe 增強、校準、UTA-RLDD replay、watch adapter、web playback / socketio dashboard、alarm、Ubuntu 相機支援）。新增分析邏輯時，優先在對應測試檔擴充純運算層測試（engine / scorer / calibration），避免依賴實體相機或 Qt event loop。

## 文件

技術報告集中在 `docs/`（多份 `.md` 皆有對應 `.pdf`）。PDF 由 `scripts/build_technical_report_pdfs.py`、`scripts/build_practical_project_report_pdf.py`、`scripts/build_rppg_pdf.py` 產生（需 `reportlab`，見 `requirements-dev.txt`）。變更安裝方式、平台支援、執行命令或必要依賴時，須同步更新 `README.md`。

## 編碼與設計規範

- 使用 4 個空白縮排，保持既有風格，避免無關重構。
- **優先維持演算法行為與精準度**，不任意更動 rPPG、疲勞判定、濾波、ROI 與分數邏輯；若平台適配會影響數值結果，必須先明確說明。
- 新增或調整函式時，若屬關鍵流程或錯誤處理，應使用既有 logger（`logging.getLogger(__name__)`）記錄。
- 前端介面必須使用 responsive 寫法，不寫死尺寸。
- 新增檔案時，名稱與責任保持單一明確。

## Git 規範

- 工作樹可能不是乾淨的，禁止覆蓋或回退非本次任務造成的變更；只修改與當前需求直接相關的檔案。
- 任務完成後自動執行 `git add`、`git commit`、`git push`。
- commit 格式遵循 Conventional Commits，例如 `fix(deploy): ...`、`docs(agents): ...`。
- commit 主旨與說明以中文為主，可保留必要英文技術名詞。

## 安全與設定

- 秘密資訊以 `.env`、systemd `EnvironmentFile` 或主機環境變數管理，不寫入版本控制。
- 不得提交資料庫密碼、Discord token、SmilePay key 或任何第三方服務密鑰；不得硬編碼個人機器的絕對路徑。
- `config/mediapipe_calibration.json` 與 `config/rppg_calibration/` 為機器/使用者特定校準，不納入版控；`models/` 下模型檔視為執行必要資產，調整載入方式時須保持相對路徑可攜性。
- 遠端操作若遇到明確可判定的權限/擁有者錯誤、既有目錄不存在、build 產物權限錯誤、systemd 舊設定殘留等常見阻塞，應優先嘗試安全修復後再繼續；僅在高風險操作、資料不可逆變更或需求不明確時才中止回問。
- migration 回滾需特別標記風險；若 schema 變更無法自動回滾，需提出手動還原方案。

## 例外與衝突處理

- 若使用者有明確新指示，優先以使用者當前指示為準。
- 若規則因工具、權限或環境限制無法完整執行，需明確回報阻塞點，再採用最接近規則的方案。

## Mindset

- 以企業級工程師標準工作，重視正確性、可維護性、可部署性與可驗證性。
