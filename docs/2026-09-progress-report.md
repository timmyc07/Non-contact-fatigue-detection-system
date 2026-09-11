# NCFD System 2026 年 7 月至今進度報告

**報告期間：** 2026-07-02 – 2026-09-06（截至目前 Git 最新提交）  
**專案：** Non-contact Fatigue Detection System（NCFD System）  
**資料依據：** Git 歷史、程式碼與測試、`docs/` 技術報告、UTA-RLDD 回放結果、心跳帶實錄及桌面 smoke/benchmark 紀錄。

## 一、執行摘要

本期間共完成約 143 筆提交，工作從「能運作的原型」推進到「可量測、可回歸、可封裝、跨平台的桌面系統」。主要成果如下：

1. **疲勞判定由固定門檻改為資料驅動校準，並補上關鍵行為通道。** UTA-RLDD 校準集的 Drowsy-vs-Alert 融合 AUC 由 0.53（近似亂猜且方向反向）提升至 0.75，未參與校準的留出 subject 07–12 為 0.69。
2. **建立個人化與可回退的校準架構。** PERCLOS、gaze、眉距、眨眼時序與哈欠門檻可依個人清醒基線調整；rPPG 心跳帶校準只以原始 BPM 作真值比對，避免自我回饋。
3. **完成 BLE 心跳帶與 rPPG 真值校準管線。** 支援 Bluetooth Heart Rate Service、背景連線、stale/接觸檢查、版本化 offset 校準、belt-truth 錄製及離線 ROI A/B 回放。
4. **建立可重現的回放與回歸驗證。** 通用影片回放與 UTA-RLDD preset 解耦；`utarldd_accuracy` 量「準確度」，`utarldd_golden` 量「是否意外漂移」，兩者職責分離。
5. **完成桌面 UI/架構轉型。** 可見主面板由舊 Qt 轉為 Flutter Web + Tauri v2；Python engine 保留相機、MediaPipe、rPPG、疲勞、錄影、回放、BLE 與校準等領域責任，並逐步移除隱藏 Qt 視覺元件與假控制項。
6. **完成封裝、生命週期與平台支援。** Windows sidecar/NSIS、macOS Apple Silicon/AVFoundation、30 FPS 固定策略、關閉時 graceful shutdown、原生 backend benchmark 與 Overlay 穩定性均已補齊。

## 二、時間線與改動內容

### 2026 年 7 月 2–3 日：基礎穩定性、心跳帶與可驗證性

| 改動 | 使用方式 | 與之前的差別 | 為何較好／證據 |
|---|---|---|---|
| 執行緒競態、每幀 I/O、相機例外與 MSMF timeout 修復 | 鎖定共享狀態、把 I/O 移出逐幀熱路徑、worker fail-safe cleanup | 之前例外可能外洩、執行緒或資源無法收尾 | 降低長時間監測卡死與資料遺失風險；對應審核報告與測試 |
| LAN dashboard shared-token 認證、收斂 CORS、限制 File Browser 為 localhost | shared token 驗證 + origin/來源限制 | 之前 LAN 模式只靠網路位置，控制端點暴露面較大 | 降低未授權讀取/控制風險；維持 localhost 預設 |
| RHYTHM+2.0 BLE 心跳帶整合 | `bleak` 背景 asyncio event loop；訂閱 `0x2A37` notify，解析 BPM/RR；`0x2A38` 身體位置、`0x2A19` 電量 | 之前沒有接觸式真值來源，也沒有 stale/接觸品質判定 | 真值與影像同步、可診斷斷線與停滯；BLE GATT 解析有單元測試與 R+2.0 實機 notification 紀錄 |
| 心跳帶角色重新定義 | 心跳帶只作 rPPG 背景真值，不直接進疲勞融合；移除手錶模式 | 之前存在「行為+rPPG+心跳帶融合」及淘汰手錶轉接層 | 避免把不同量測來源重複計權；保留可解釋的兩種正式配置 |
| 資料驅動疲勞校準與 golden 工具 | `scripts/utarldd_accuracy.py` 計單調性、Spearman、AUC、bootstrap CI；`scripts/utarldd_golden.py` 固定子集與容差 | 之前只看畫面或單一數值，難以知道是「變準」還是「意外漂移」 | 能先量測再改、改後復量並保留數值契約 |
| 通用影片回放 | 將 replay 核心與 UTA-RLDD 標籤邏輯解耦，使用 deterministic timestamp | 之前回放模組名稱與流程綁 UTA-RLDD | 任意影片可重播；UTA-RLDD 仍保留 label/validation preset；即時 worker 不被改動 |

### 2026 年 7 月 3–5 日：疲勞演算法校準與誤判修復

#### 1. PERCLOS 與融合權重資料驅動重校準

分析 subject 01–06 × label 0/5/10、每片 1,200 幀後發現：原始 PERCLOS AUC 0.79，但計分門檻 `0.10/0.25` 高於實際 `0.005–0.067` 範圍，導致有效訊號被壓成 0；微睡與 blink-temporal 在該資料集反而是反訊號。實作上將 PERCLOS 門檻調至工作範圍、提高 PERCLOS 權重、降低資料集反訊號權重，並把 composite 飽和常數與狀態門檻分離。

| 指標 | 改前 | 改後 |
|---|---:|---:|
| 校準集 `avg_fused_score` AUC | 0.53 | **0.75** |
| 校準集 label 0→5→10 | 反向 | **單調上升** |
| 留出集 subject 07–12 AUC | — | **0.69** |
| 校準集分數塌陷率（<0.20） | 100% | 50% |

這是「把已存在的訊號送進輸出」而不是盲目增加模型複雜度；但 n=6/label，bootstrap CI 很寬，不能宣稱統計顯著或直接代表真實無人機場景。

#### 2. 個人清醒基線（P0–P5）

新增 Qt-free `PersonalProfile`、`PersonalBaselineCollector` 與 `resolve_active_baseline`。系統可在啟動時建立不落檔的暫定基線，也可由使用者按「記錄清醒基線」擷取約 60 秒並跨 session 儲存。門檻優先序為 **manual > auto > fallback**；無有效 profile 時逐位元回退原值，因此 replay/golden 不注入 profile 時輸出不變。

個人化項目包括：

- PERCLOS low/tired/composite 門檻。
- gaze 固定與低掃視門檻。
- 眉距、blink-temporal baseline seed，免每次重新暖機。
- 哈欠嘴開門檻（相對靜息 MAR，保留 duration 條件）。
- worker 安全熱換與跨執行緒狀態管理。

相比全域固定值，這能降低眼型、自然半閉、個人眨眼習慣造成的誤報；目前仍需真人資料證明跨個體提升幅度。

#### 3. 持續閉眼強通道

針對「頭端正閉眼 10 秒仍只有輕度」的即時痛點，新增 `eye_closure_sec` 與共用 `compute_closure_s`，在 engine 與 scorer 以 additive 方式提高分數：1 秒後開始、8 秒飽和；眨眼與無閉眼時 `closure_s=0`，因此逐位元回退。實測推導為閉眼 3 秒進中度、10 秒進高度。UTA-RLDD 沒有同類純閉眼片段，所以 golden/AUC 不變；價值需靠實機驗證。

#### 4. 下視偵測器

持續閉眼通道上線後，發現「視線下看、眼皮被帶動下垂」會誤觸發。新增以 `gaze_y`、校準 EAR 範圍、iris 存在與 blendshape gate 組成的 AND 條件，搭配 0.3 秒進入/退出去抖；下視期間暫停 closure/PERCLOS/squint/blink 累積，但深閉眼 EAR 低於 floor 時仍恢復疲勞通道。

測試涵蓋 latch、掉臉、pitch gate 共存、真閉眼反例，完整測試曾達 438 passed，golden 零漂移。限制是半閉眼時 `gaze_y` 可能放大雜訊、目前沒有長時間 latch 上限，仍須實機掃描五個常數。

#### 5. Blendshape 命名 A/B 否決

曾以 camelCase/snake_case 正規化修復 MediaPipe blendshape lookup，但真實 A/B 顯示融合 AUC 0.750→0.722、清醒影片 active fraction 0.286→0.839，golden 也大幅漂移，因此已 revert，不把「修正 bug」等同於「變準」。這次保留量化否決紀錄，並提醒下游門檻是在 blendshape 長期為 0 的條件下校準，未來若重做必須先重新校準所有 gate。

### 2026 年 7 月 4 日：rPPG 有護欄自適應與真值離線驗證

建立 P6a/P6b 分階段架構：

1. `CalibrationParams.rppg_params` 向後相容持久化模型。
2. `RppgParamAbEvaluator`：同一段訊號比較 current/candidate 與心跳帶真值的中位殘差，候選需「明確更好且連續 N 次」才 adopt，變差 rollback。
3. per-ROI RGB 均值緩衝、ROI 加權混合與 `recompute_raw_bpm_from_roi_windows()`，讓候選可公平重算。
4. `RppgParamCoordinator` 狀態機與約 1 Hz candidate BPM 事件；正式開關預設 OFF，未經驗證不熱切換。
5. `BeltTruthCaptureWriter` 與 `scripts/rppg_param_replay.py`，把每幀 ROI 均值和 belt BPM 對齊成 JSONL，無需再次連線硬體即可離線 A/B。

首次真實心跳帶錄製約 8 分鐘、14,067 幀，155 個可比較視窗：現行權重 MAE 10.09 BPM、medAE 2.53；等權 MAE 9.75，改善僅 0.34 BPM、勝率 51%。34/155（22%）離群視窗貢獻 MAE 的 79%，主要是半頻 41–60 BPM 或諧波約 144 BPM 鎖定；排除離群後穩態 MAE 2.73 BPM、有號偏差中位 +0.09。結論是 ROI 權重不是此段資料的主要槓桿，因此參數自適應維持 OFF；下一個 rPPG 槓桿應先處理峰選與低 SNR 拒絕，而非硬套權重。

### 2026 年 7 月 6–29 日：GUI、效能與模組整理

- 完成側邊導航四頁 dashboard、雙欄即時監測卡片、疲勞大卡、裝置狀態、回放佇列與心跳帶專頁。
- Overlay 改以 Pillow 渲染中文、放大字級、黑邊與半透明底板；修正 compact window overflow、監測數值溢出與位置錯位。
- 新增「自動採集」：一次啟動 pipeline/recording/belt capture，倒數結束自動停止；補回滾與誤停防護。
- QSS token 化、深淺主題與 NCFD System 品牌統一；這些 UI 改動不改疲勞/rPPG 數值路徑。
- 記錄寫入移出 GUI 執行緒、playback 分段載入、清單 metadata sidecar，降低 UI 卡頓與大量紀錄載入成本。
- 移除淘汰的手錶/Watch 實體轉接層、未使用 Socket.IO handler、matplotlib runtime 依賴；以測試與 README 同步清理介面。

### 2026 年 8 月 9–18 日：Flutter/Tauri 桌面化與 headless engine

#### 架構改變

可見層改為 **Flutter Web → Tauri v2 WebView → Python engine**：

- Flutter 負責 dashboard、設定、回放、Overlay 顯示與互動。
- Tauri 負責原生視窗、檔案/URL shell action、process shutdown 與平台能力。
- Python engine 保留相機、MediaPipe、rPPG、疲勞融合、錄影、BLE、校準與 Web metrics。
- `EngineRuntime` 收斂 live worker、recording/replay、alarm、timer、shutdown ownership；移除隱藏 `QMainWindow`、QAction/label/button 假控件與舊 Qt visual modules。
- Overlay geometry、capture/replay/settings/web preferences 進入 Qt-free state/command contract，避免 presentation state 反向控制數值核心。

#### 相比之前的差別與好處

之前 Qt 同時承擔可見 UI 與 engine runtime，導致 headless 啟動仍要建立視覺元件、生命週期相互依賴；現在領域邏輯與畫面解耦，能獨立測試、封裝與替換 UI，且 shutdown 可重入、失敗可重試。這是可維護性與部署可靠性改善，不是疲勞準確度改善；所有數值路徑明確保持不變。

#### 驗證與效能證據

- 2026-08-18 clean follow-up：Python **757 passed, 2 skipped**；`compileall`、`pip check`、Flutter 28 tests/analyze/release Web build、Rust 8 tests、PyInstaller、Tauri release/NSIS、installed smoke 全部通過。
- packaged smoke 成功顯示 Flutter dashboard、導覽心跳帶/回放/設定、啟停 pipeline、建立 Overlay、`app.shutdown` 正常退出並移除安裝目錄。
- WebCamera 在 raw/fatigue/rPPG/combined 四種模式通過 1280×720、30 FPS 的 lifecycle/routing smoke；這不等於 rPPG 或疲勞數值精準度驗證。
- 同 Windows benchmark slice 的 process-tree RSS 約 270.0 MiB（舊 hidden Qt dashboard）降至 256.3 MiB（headless shell，約 5.1%）；後續 ownership 變更多落在 253–257 MiB 範圍，startup 約 1.84–2.46 秒，`state.get` p50 約 20 ms。這些是環境敏感微基準，不應當成產品 SLA。

### 2026 年 9 月 2–6 日：macOS、相機與關閉流程

- 固定正式桌面取樣 **30 FPS**；診斷同時顯示 driver/reported FPS 與按時間量測的 measured FPS。macOS 內建相機在 30/60 要求下皆實收約 29.9 FPS，證明 60 FPS 不是此硬體可用格式。
- backend policy 分層：Windows 維持 DSHOW→MSMF→ANY，macOS 使用 AVFoundation→ANY；`ffmpeg` 僅保留為相容設定名稱。加入 backend benchmark、讀取成功率、丟幀、interval p95、CPU 與每秒畫素量指標。
- macOS MediaPipe 崩潰修復：Windows/macOS 固定 `mediapipe 0.10.35`，以 preflight 子程序實際建立/關閉 Face Landmarker；native abort 不會拖垮主 engine。平台 policy 集中於 `gui/platforms/`，模型、ROI、濾波、門檻與融合仍共用。
- Tauri `close_window`/`CloseRequested` 統一呼叫 `app.shutdown`，背景最多等 6 秒正常釋放，逾時才 process-tree kill；修正「視窗關了但 engine/Flutter 仍存活」。

## 三、精準度現況與尚缺資料

### 已有證據能支持的結論

- UTA-RLDD 上，PERCLOS 是目前最穩定的行為訊號（AUC 約 0.79）；資料驅動重配後融合 AUC 0.75，留出集 0.69，方向一致但 CI 寬。
- 純閉眼強通道與下視 gate 解決的是實機情境誤判/漏報，不會在沒有相同片段的 UTA-RLDD 上自動反映。
- 心跳帶 offset 校準能修正穩定的全域偏移；實錄顯示 rPPG 主要誤差來自半頻/諧波錯峰，而非可由 offset 或 ROI 權重消除的偏移。
- smoke、pytest、golden 保證的是程式、生命週期與回歸契約，不是臨床級 BPM 或疲勞分類準確率。

### 目前仍缺少的精準度要件

1. **目標場景資料不足。** UTA-RLDD 是坐姿汽車情境、整段影片單一 label，不是無人機駕駛員逐幀真值；需要多受試者、不同任務與人工標註的真人資料。
2. **跨個體/跨硬體泛化尚未量化。** 需在不同臉型、眼型、膚色、相機、解析度、光線、姿態與 FPS 分層報告 sensitivity、specificity、AUROC、F1、誤報率與有效 frame rate。
3. **PERCLOS 仍是固定 EAR 二元門檻。** 文獻中的 P80 幅度式定義尚未完整導入；半垂眼可能漏抓。個人 profile 已建立，但尚未用真人疲勞/清醒配對資料量化增益與安全護欄。
4. **rPPG 尚無臨床對照。** 需要同步 ECG/醫療級胸帶，報告 MAE、median AE、95th percentile error、Bland–Altman bias/limits of agreement；目前只有單一受試者、80–110 BPM、單段 8 分鐘 belt-truth。
5. **半頻/諧波與低 SNR 錯峰仍是主要 rPPG 缺口。** 應先離線比較生理合理性/時序連續性峰選與低 SQI 拒絕策略，再決定是否進 live；不可直接修改即時 `rppg/` 路徑。
6. **blendshape 尚未重新校準。** camelCase 修復雖技術上可行，但 A/B 顯示整體惡化；若重啟，必須以真實模型輸出重建所有 gate/權重並通過 golden、留出集與真人測試。
7. **統計檢定與資料切分仍需擴大。** 目前 AUC 每組 n=6，CI 下界可低至約 0.36–0.39；應擴充 UTA-RLDD 全量或真人資料，採 subject-disjoint split、bootstrap CI，必要時做 mixed-effects/跨 session 分析。

## 四、後續可延伸工作（建議順序）

### 短期：先補證據，不先改數值

- 收集清醒、自然疲勞、刻意下視、持續閉眼、不同光照/姿態的真人資料；每段同步保存影像、逐幀 metrics、事件標註與硬體資訊。
- 把 `utarldd_accuracy` 擴充為 profile 注入與 subject-disjoint 評估；固定輸出 ROC、PR、混淆矩陣、校準曲線、CI 與有效 frame/丟幀率。
- 以 belt/ECG 建立多場景 rPPG truth capture，先量錯峰比例與 SQI 分布，再比較候選峰選策略。
- 建立每次模型、tuning、backend、光線、FPS 與 profile 的 manifest，讓結果可以 replay。

### 中期：經離線 A/B 後再考慮上線

- 優先原型化「生理合理性 + 時序連續性 + 半頻/諧波候選比較」峰選；以錯峰視窗數（目前 34/155）為主要 KPI，並監控穩態 MAE 不退化。
- 對低 SQI 片段採拒絕輸出或降權，避免錯 BPM 進入融合；明確定義輸出覆蓋率與告警延遲的 trade-off。
- 在個人基線上加入安全鎖：只在使用者明確清醒時段學習、以 blink/gaze/任務狀態交叉 gate，避免把真疲勞學成 baseline。
- 若 blendshape 重新校準後證明有益，再逐通道重估門檻，不能直接恢復先前被 revert 的 patch。

### 長期：產品與研究化

- 以可解釋特徵作 baseline，待資料量足夠再比較 logistic regression/gradient boosting/時序模型；保留規則式 fallback 與可稽核輸出。
- 做跨平台效能/耗電/熱限制測試，將 30 FPS、Face-present rate、rPPG SQI 與告警延遲納入品質門檻。
- 建立資料治理、受試者同意、匿名化與版本化標註流程，才能進行統計顯著性與長期泛化研究。

## 五、參考文獻、規範與查證方式

本期間的實作先查閱 repo 內的技術報告與原始連結，再以單元測試、離線回放、A/B、golden 或實機 smoke 驗證；文獻提供方法與定義，門檻、權重與線上校準增益則明確標記為本專案工程決定，不宣稱由論文直接保證。

| 來源 | 實作採用內容 |
|---|---|
| MediaPipe Face Landmarker 官方指南（[Python](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python)、[Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)）；Lugaresi et al., 2019, [arXiv:1906.08172](https://arxiv.org/abs/1906.08172) | 478 landmarks、blendshape、facial transformation matrix、VIDEO/LIVE_STREAM 時序模式與 perception pipeline。 |
| Soukupová & Čech, 2016, [Real-Time Eye Blink Detection](https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf) | 六點 EAR 幾何與 blink 判定基礎。 |
| Dinges & Grace, 1998；Wierwille et al., 1994；[PERCLOS evidence review 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/)；NHTSA [DOT HS 808 247](https://rosap.ntl.bts.gov/view/dot/1644) | PERCLOS 作為時間累積警覺度指標、長閉眼與駕駛疲勞觀察概念；本專案實際門檻仍由資料校準。 |
| Ghoddoosian, Galib & Athitsos, 2019, [UTA-RLDD/CVPRW](https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html) | Alert/Low Vigilant/Drowsy 序位概念與時序回放驗證背景；label 非逐幀真值。 |
| Lepetit et al., 2009 EPnP；OpenCV [`solvePnP`](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html) 與 calib3d 文件 | 由臉部 2D/3D 點估算 pitch/yaw/roll。 |
| Wang et al., 2017, [Algorithmic Principles of Remote PPG](https://doi.org/10.1109/TBME.2016.2609282)；de Haan & Jeanne, 2013 CHROM | RGB 投影與色度式 rPPG 訊號處理；本專案 `pos_pulse` 命名與實際 CHROM/POS 混合需以程式為準。 |
| Welch, 1967；SciPy [`find_peaks`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)；Butterworth 濾波理論 | Welch PSD 峰值、IBI peak detection 與帶通濾波。半頻/諧波抑制仍屬待驗證工程延伸。 |
| ESC/NASPE Task Force, 1996, [HRV standards](https://pubmed.ncbi.nlm.nih.gov/8598068/) | RMSSD、SDNN、LF/HF 定義與 RR-Interval 比對框架。 |
| Bluetooth SIG Heart Rate Service 1.0、GATT Supplement（見 [`heart_rate_belt_bluetooth_gatt_profile.md`](heart_rate_belt_bluetooth_gatt_profile.md)） | `0x180D/0x2A37/0x2A38/0x2A19` 服務、flags、BPM/RR、身體位置與電量解析。 |
| FFmpeg [devices](https://ffmpeg.org/ffmpeg-devices.html)、OpenCV [Video I/O](https://docs.opencv.org/4.x/d0/da7/videoio_overview.html)、Apple [AVFoundation](https://developer.apple.com/documentation/avfoundation)、Microsoft [Media Foundation](https://learn.microsoft.com/en-us/windows/win32/medfound/media-foundation-architecture) | 平台相機 backend 選擇、FPS 量測與 Windows/macOS fallback 順序。 |
| Hanley & McNeil, 1982；Efron, 1979 | AUC/Mann–Whitney 意義與 bootstrap CI；用於 `utarldd_accuracy`，不把小樣本點估計說成顯著結果。 |

完整方法與行號索引另見：[`2026-07-03-fatigue-methodology-and-references.md`](2026-07-03-fatigue-methodology-and-references.md)、[`2026-07-03-hr-belt-module-technical-report.md`](2026-07-03-hr-belt-module-technical-report.md)、[`2026-07-04-personal-baseline-personalization.md`](2026-07-04-personal-baseline-personalization.md)、[`2026-07-04-p6b4-first-belt-truth-validation.md`](2026-07-04-p6b4-first-belt-truth-validation.md)、[`tauri-flutter-migration.md`](tauri-flutter-migration.md) 與 [`2026-09-05-camera-backend-research.md`](2026-09-05-camera-backend-research.md)。

## 六、結論與目前風險

目前系統已具備可運行的跨平台桌面產品骨架、可追溯的演算法校準流程、可重播的驗證工具與足夠的回歸防護。最明確的數值改善來自 PERCLOS 資料驅動重校準；最明確的工程改善來自 Flutter/Tauri 與 headless engine 解耦；最主要的精準度風險仍是資料代表性不足、個人基線尚未以真人疲勞資料量化，以及 rPPG 在低 SNR 下的錯峰。

因此下一階段的成功標準不應是再堆疊門檻或模型，而是先取得跨個體、跨場景、同步生理真值與人工標註，並以離線 A/B、subject-disjoint 評估及完整不確定度報告證明每一項數值改動確實改善，而不是只在單一資料集或單一裝置上看起來變好。

