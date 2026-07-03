# 個人清醒基線個人化 + rPPG 有護欄自適應基礎層（2026-07-04）

## 動機

前一份《2026-07-03 疲勞準確度校準》把「加一段清醒基線 PERCLOS 校準、讓分數相對個人清醒基線」列為
**下一步最高槓桿**。多項行為/表情指標（注視、哈欠、瞇眼、皺眉、blendshape）的門檻多為寫死絕對常數，
未對齊每位駕駛員的個人正常範圍，導致「數值不準」。同時，心跳帶配合 rPPG 的校正現況**只在輸出 BPM
疊加線性 offset**（scale 鎖 1.0、低增益 EMA），**完全不動 rPPG 解析參數**，因此 rPPG 解析能力不會
因心跳帶而變好、達不到「最終不需心跳帶也能準確辨識」的目標。

本次全面把行為門檻改為**相對個人清醒基線**（P0–P5），並為心跳帶驅動 rPPG 解析參數建立**有護欄的
自適應基礎層**（P6a）。

## 設計鐵律：向後相容 / 保護 golden

所有「絕對門檻 → 相對基線」一律走 `value = profile.X(fallback)`，無有效基線時**逐位元回傳 fallback、
走原程式路徑**。`FatigueEngine(personal_profile=None)` 即現況；replay / `utarldd_golden` /
`utarldd_accuracy` 一律不注入 profile，故所有離線路徑輸出**逐位元不變**，golden baseline 不需重建。
個人 profile 存 `config/personal_profile/active.json`（不入版控），與 blendshape baseline
（`mediapipe_calibration.json`）分離、互不覆寫。

## 分階段內容

| 階段 | 內容 | 影響的輸出（僅 live+profile） |
|---|---|---|
| **P0** | `gui/personal_profile.py` 純運算層：`PersonalProfile` / `PersonalProfileStore` / `PersonalBaselineCollector` / `resolve_active_baseline` + 門檻解析純函式 | 無（未接線） |
| **P1** | PERCLOS 狀態門檻（low/tired）、composite 飽和點、scorer 分數映射門檻相對化 | 狀態分佈、composite `fatigue_level`、`behavior_sub` |
| **P2** | Gaze `gaze_fixed_std_th`、低掃視門檻相對化（saccade_velocity/alert_sec 保留） | `gaze_stability_index`、`gaze_mental_fatigue` |
| **P3** | 眉距 / blink-temporal 基線跨 session 免暖機（由 profile seed） | frown / blink_temporal 提早生效 |
| **P4** | 哈欠 `mouth_open_yawn_th` 相對靜息嘴開度（MAR/duration 保留） | 哈欠判定 |
| **P5** | GUI「記錄清醒基線」按鈕 + 啟動自動暫定基線 + 跨 session 載入 + 執行緒安全熱換 | 使 P1–P4 在桌面 GUI 生效 |
| **P6a** | rPPG 有護欄自適應**基礎層**：`CalibrationParams.rppg_params`（向後相容）+ `RppgParamAbEvaluator` 純運算 A/B 決策 | 無（預設 off，見下） |

### 門檻推導（對「典型清醒者」還原成現行預設）

門檻映射刻意讓典型清醒者還原成現行常數，只對離群基線調整，並夾在 `[預設×0.5, 預設×3]` 防呆：
- PERCLOS low ≈ `awake_p90 + 0.01`（典型 → 0.02）、tired ≈ `awake_p90 + 0.04`（→ 0.05）。
- scorer mild ≈ `awake_p90 + 0.005`（→ 0.015）、high ≈ `awake_p90 + 0.06`（→ 0.07）。
- gaze 固定門檻 ≈ `清醒 gaze std × 1.5`（→ 0.015）；低掃視 ≈ `清醒掃視率 × 0.6`（→ 1.0/min）。
- 哈欠嘴開 ≈ `靜息嘴開度 + 0.19`（→ 0.24）。

### 清醒基線擷取（自動 + 手動並存，使用者定調）

- **啟動自動**：偵測開始即蒐集前約 75s 當暫定基線；無 manual profile 才套用、**不落檔**。
- **手動按鈕**「記錄清醒基線」：精神好時按下 → 擷取約 60s → 存 `active.json` → 即時熱換 → 下次開機自動載入。
- **優先序** manual > auto > 無。熱換走「主執行緒設 pending 旗標、worker run 迴圈輪詢套用」（仿
  `request_stop`，GIL 保證原子性，無 Qt queued signal），套進 worker 內 `FatigueEngine.set_personal_profile`。

## P6a：rPPG 有護欄自適應——只做基礎層，live 迴圈未開

使用者目標是「心跳帶當老師、讓 rPPG 一直調解析參數直到不需心跳帶」。這需要動 `rppg/` 最紅的數值路徑，
且**本機無心跳帶硬體、無資料集**，無法驗證任何 rPPG 數值變化是否真的更準。依專案護欄，本次只交付
**安全可測基礎層**：

- **資料模型**：`CalibrationParams.rppg_params`（ROI 權重/頻帶等），預設 None、序列化條件式（既有版本檔
  bit-identical）、舊檔載入回 None。
- **A/B 護欄決策**（`RppgParamAbEvaluator`，純運算）：對**同段訊號**的現行 vs 候選參數 BPM 各對心跳帶
  真值算中位殘差；候選明確更好且連續 N 次才 `adopt`、明確更差則 `rollback`、否則 `pending`。這是
  「只採用被真值證明更好、變差回退」的護欄核心。

**尚未做（需心跳帶硬體 + 離線驗證後才可開 live）**：per-ROI 均值緩衝 seam（讓同段訊號能以不同 ROI
權重重算 BPM）、候選參數產生策略、把採用的 `rppg_params` 套進 rPPG worker、線上學習協調層、
belt-truth 同步錄製回放離線驗證腳本。頻帶 / PSD 峰選收窄易鎖諧波，風險更高，規劃為僅離線。

## 驗證

- **本機無 UTA-RLDD 資料集**，golden check 與 utarldd_accuracy 無法在此機器執行。改以：
  (1) bit-identical fallback 設計；(2) 顯式「無 profile = 逐位元相同」單元測試；(3) 完整 `pytest` 全綠
  （266 passed）鎖定「未破壞現有數值行為」。
- **準確度真的變好**的最終證明需在**有資料集的機器**上跑：擴充 `scripts/utarldd_accuracy.py` 支援
  per-subject profile 注入（每人用 label-0 片段建清醒基線 → 套到 label-5/10 → 比 AUC/Spearman），
  以及真人、你的無人機場景測試。UTA-RLDD label 是整段影片類別，不能取代真人測試。
- P6a rPPG 自適應的離線驗證需 belt-truth 同步錄製，屬 P6b 前置阻塞項。

## 檔案

- 新增：`gui/personal_profile.py`、`config/personal_profile/active.json`（不入版控）、
  `tests/test_personal_profile.py`、`tests/test_personal_baseline_worker.py`。
- 改：`gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、`gui/main_window.py`、`gui/combined_worker.py`、
  `gui/fatigue_worker.py`、`rppg/calibration.py`、`rppg/adaptive_calibration.py` 及對應測試。
