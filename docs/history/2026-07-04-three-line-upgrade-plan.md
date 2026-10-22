# 三線升級計畫：GUI 重設計 / 行為特徵資料集校準 / rPPG 改善

> 決策已定案（2026-07-04 使用者裁決）：
> GUI **深色監控風**、**GUI 先行** ｜ 心跳帶區塊**含 HRV** ｜ 行為**先出 UTA 基準報告再調門檻** ｜ rPPG **只留計畫文件**
> UTA-RLDD 資料集已在本機：`C:\Users\USER\Downloads\UTA_test`（182 影片 / 111.86GB / `Fold{N}_part{M}/subject/label.ext`）

---

## Context（為什麼做）

三個獨立需求：
1. **GUI/overlay 觀感差**：使用者不滿意現有 PySide6 桌面 GUI 與影像 overlay，字與區塊不易一眼看清，且沒有心跳帶專屬資訊區塊。要**純視覺重設計**，鐵律：不破壞任何既有功能與數值行為，只改觀感。
2. **rPPG 疑問**：「戴著心跳帶一直測就會自己調好嗎？」——2026-07-04 首次實錄驗證已有資料面答案，需轉成使用者能懂的結論＋可斷點續接的計畫。
3. **行為特徵革命性升級**：使用者收集大量疲勞資料集，疑問「是不是一定要練新 AI 才有用」。答案已確認：**不必**——現系統是純門檻式融合（無任何 ML 依賴），資料集第一價值是大規模校準門檻與量化準確度，不需訓練。

## 關鍵事實基礎（探索已確認，不需重查）

**GUI 現況**
- 樣式集中在 `gui/main_window.py:74` `application_stylesheet()`（全域 QSS，深色 `#16181d`/`#1c2028`），另有大量 inline `setStyleSheet`。無外部 .qss、無主題切換。
- 浮動數值面板 `gui/preview_overlay_window.py`：QLabel（非表格）+ 少量 QPainter 波形，樣式數十處 inline。這是「數值一眼看清」的重點檔。
- 影像 overlay `gui/fatigue_worker.py:131` `draw_fatigue_annotations()`：cv2 直接畫在 frame（字級 0.30–0.40 硬編碼、`_STATUS_COLOR` dict 於 `:36-81`）。
- 心跳帶目前**只有**控制列一顆 checkbox（`_chk_belt_calib`, `main_window.py:529`）+ 一顆狀態 label（`_update_belt_status_label`, `:2325-2365`），**無專屬區塊**。
- Web dashboard（`gui/web_ui/`）CSS 完全獨立，改桌面樣式不影響它。
- tests/ **無任何測試**斷言 GUI 佈局/QLabel 文字/objectName——純視覺重設計對測試安全。

**心跳帶資料鏈（區塊資料都現成，多數只需接顯示）**
- 已解析但完全沒顯示：RR intervals 原始值、RSSI、`notifications` 累計數、`connected_since`、`device_address`、`sensor_location`、校準 `raw_residual_bpm`/`corrected_residual_bpm`/`total/accepted_observations`。來源：`HrBeltStatus`（`rppg/hr_belt_ble.py:314`）、`AdaptiveCalibState`（`rppg/adaptive_calibration.py:52`）。
- **最大缺口＝HRV**：`rppg/watch_physio.py:27` `compute_watch_physio()` 能從心跳帶 RR 樣本算 RMSSD/SDNN/LF-HF/波形/PSD，但目前 GUI 顯示的 rmssd/sdnn 其實來自 rPPG（`main_window.py:1245`），非心跳帶。心跳帶 HRV 從未進 GUI。
- `energy_expended_kj` 解析後即丟棄（`HrBeltStatus` 無此欄位）；要顯示需補一小段。
- 唯讀取樣：`BeltRuntime.belt_status()`（`gui/belt_runtime.py`）現為 GUI 輪詢，沿用。

**行為校準基建（不必造新輪子）**
- `scripts/utarldd_accuracy.py`：吃 UTA-RLDD 目錄，算各 label 分數分佈 / Spearman / 成對 AUC / 尺度塌陷比例。**純量測、不 gate、不改碼**。可直接吃 `UTA_test`。
- `gui/fatigue_scorer.py:48` `FuserConfig`：7 個行為子分數權重＋PERCLOS 門檻全是**寫死常數**（`:82-93`，上輪已用 6 subjects 校準過）。要調＝改這些常數＝**重量級數值路徑**＋重建 golden。
- `tests/golden/utarldd_golden_baseline.json`：近零容差回歸基準。改任何門檻常數 → golden check 必報漂移（設計如此），需 `scripts/utarldd_golden.py create --force` 重建。
- 專案**零 ML 依賴**（requirements 無 sklearn/torch/onnx）；E 槽剩 672GB。

**rPPG 現況（2026-07-04 實錄結論，見 `docs/history/2026-07-04-p6b4-first-belt-truth-validation.md`）**
- offset 校準會隨使用自動收斂、跨 session 改善——「一直測」**只有這一小塊**會變好。
- 穩態原始 BPM 已幾乎無系統性偏差（中位 +0.09 BPM），offset 修不了多少。
- MAE 的 79% 來自半頻/諧波鎖定離群視窗——**這不是繼續測能修的**，要改 Welch 峰選（重量級，未動）。

---

## 階段 1（本次 session 主體）：GUI/overlay 純視覺重設計 ＋ 心跳帶全數值區塊

**任務分級：中量**（GUI 佈線＋新增顯示區塊，不碰 `rppg/`/`fatigue_engine`/`fatigue_scorer` 數值行為）。心跳帶 HRV 為唯讀顯示、**不進疲勞融合分數**（守紅線）。

### 1a. 深色監控風視覺系統（集中化）
- 在 `application_stylesheet()`（`gui/main_window.py:74`）建立語意化色彩 token：狀態色（清醒綠/輕度黃/中度橙/高度紅/極度深紅，對齊 `fatigue_scorer._LEVELS`）、字級階層（數值大字 ≥20px、標籤 12–13px）、區塊卡片。
- 收斂 `preview_overlay_window.py` 數十處 inline style 到共用樣式 + objectName，數值字體放大、加狀態色底、分組排版讓「一眼看清」。
- 不改任何 signal→slot 連線、不改 `update_*` 方法的資料來源，只改視覺呈現。

### 1b. 影像 overlay（cv2）可讀性
- 提高 `draw_fatigue_annotations()`（`gui/fatigue_worker.py:131`）字級與對比、加半透明底板讓文字在任何背景可讀；把散落的字級/顏色抽成檔頭常數表。
- HUD/警示徽章/PERCLOS 條的**內容與數值不變**，只改繪製樣式。overlay 開關與透明度滑桿行為不變。

### 1c. 心跳帶專屬區塊（新增，含 HRV）
- 在 `main_window` 新增一個 `QGroupBox("心跳帶")`（放控制區附近），顯示分組：
  - **即時**：BPM、RR intervals（原始值）、sensor contact、電量、RSSI、資料停滯警告
  - **連線**：裝置名/位址、sensor location、連線時長、累計封包數、last error
  - **HRV**（新接線）：RMSSD/SDNN/LF-HF/HRV 信心——週期性從 `BeltRuntime.hub` 取樣本快照丟 `watch_physio.compute_watch_physio()` 算，唯讀顯示。
  - **rPPG 校準**：offset、raw/corrected 殘差、信心、converged/diverged、配對數（`AdaptiveCalibState` 全欄位）
- 資料多為現成，主要是新增顯示 widget + 一個輪詢 tick（沿用既有 belt 輪詢節奏）。HRV 那條需注意 hub 樣本讀取的執行緒安全（取快照，不長時間持鎖）。
- 保留控制列既有 checkbox 行為；新區塊是顯示，不改校準啟停邏輯。

### 1d. 驗證
- `.venv\Scripts\python -m compileall -q` 改動檔。
- `.venv\Scripts\python -m pytest -q`（完整）確認沒弄破——GUI 對測試免疫，應維持現有全綠數。
- **手動目視**：`python main.py` 啟動，開相機+rPPG+疲勞，勾心跳帶校準，確認三種 worker 模式（僅 rPPG / 僅疲勞 / combined）overlay 與數值面板都正常、心跳帶區塊有數值。（使用者執行或提供截圖確認觀感。）
- golden **不需重建**（沒碰數值路徑）；數值行為聲明：無數值變更。

---

## 階段 2（本次可並行，低風險、不改碼）：行為校準基準報告 ＋ rPPG 計畫文件

### 2a. 跑 UTA 準確度基準（純量測，不改任何數值）
- 先小樣本試跑打通管線，再全量：
  ```powershell
  .venv\Scripts\python -m scripts.utarldd_accuracy "C:\Users\USER\Downloads\UTA_test" --subjects 01,02,03,04,05,06 --max-frames 1200 --jobs 4 --out scratchpad\uta_baseline_6subj.json
  ```
- 產出 `docs/history/2026-07-04-uta-accuracy-baseline.md`：現況 AUC / Spearman / 各 label 分佈 / 尺度塌陷比例，指出**哪個門檻脫離 operating range**——這是階段 3 調門檻的證據基礎。
- 註記 subject 46 的 2 個 `.m4v` 會被 `utarldd_replay` 的 `VIDEO_EXTS` 濾掉（180/182），不影響統計。

### 2b. rPPG 改善計畫文件
- 產出 `docs/plans/rppg-improvement-plan.md`：
  - **直接回答**：「一直測會不會自己好？」→ offset 那塊會、且跨 session 累積；但主要誤差（半頻/諧波鎖定）不會，需改 Welch 峰選。
  - 半頻/諧波抑制的候選方案（諧波約束峰選、生理合理性門檻、時序連續性約束）＋各自風險（易鎖諧波、影響即時性）。
  - 驗證方法：用已有 belt-truth capture 回放（`scripts/rppg_param_replay` 家族）離線量化，先離線後 live。
  - 斷點續接指引：目前進度、下一步、紅線。

---

## 階段 3+（後續 session，roadmap，本次不做）

- **調行為門檻**（重量級）：依 2a 基準，改 `FuserConfig` 門檻/權重常數 → 完整 pytest + 重建 golden + 數值行為聲明。可延伸為「用 UTA 統計重定 `personal_profile` 的 margin/factor 錨點」。
- **輕量 ML scorer**（可選，預設 OFF）：引入 sklearn，用資料集特徵訓練分類器接進 scorer，沿 `personal_profile` 的向後相容模式（None＝逐位元回退）。需先證明階段 3 調門檻不夠。
- **rPPG 半頻/諧波抑制實作**：先離線驗證版，數據有效再進 live。
- **更多資料集**（YawDD+/DROZY/MRL Eye）：擴充 `video_replay` 的 label 映射，做跨域驗證與眼/嘴偵測器強化。DROZY 68 點可校準 landmark 精度。
- 使用者提供的資料集 md 放 `docs/datasets-reference.md` 供參照——**不可**改名為 CLAUDE.md（會蓋掉專案權威規則）。

---

## 紅線與注意事項（全程）

- 不碰 `rppg/`、`gui/fatigue_engine.py`、`gui/fatigue_scorer.py` 的數值行為（階段 1、2 全程）。心跳帶 HRV 顯示唯讀、不進融合分數。
- 階段 3 調門檻才動數值路徑，屆時走完整重量級流程（完整 pytest + golden 重建 + 數值行為聲明），且先問使用者。
- 每完成一子項：compileall + 對應 pytest + commit+push（Conventional Commits 中文）+ 同步 docs/。
- 環境：PowerShell 5.1 無 `&&`；寫檔用 Write tool（避免 UTF-16）；git push 已永久修好可直接用。

---

## 重置後如何繼續（token session 於 2026-07-04 用到 93% 暫停，計畫已定案未動工）

**下個 session 直接把下面整段貼給 Claude Code：**

```
接續「非接觸式疲勞偵測系統」的三線升級。完整計畫在
C:\Users\USER\.claude\plans\frolicking-growing-waterfall.md，先整份讀完再動手。

狀態：計畫已與使用者定案，尚未開始實作（上個 session token 用盡暫停）。
決策已拍板：GUI 深色監控風、GUI 先行、心跳帶區塊含 HRV、行為先出 UTA 基準
報告再調門檻、rPPG 只留計畫文件。UTA 資料集在 C:\Users\USER\Downloads\UTA_test。

從階段 1 開始做（GUI/overlay 純視覺重設計 + 心跳帶全數值區塊），這是中量級：
只動視覺層（application_stylesheet / preview_overlay_window / fatigue_worker 的 cv2
繪製樣式）與新增心跳帶顯示區塊，絕不碰 rppg/ 、fatigue_engine、fatigue_scorer 的
數值行為，心跳帶 HRV 唯讀顯示、不進疲勞融合。做法、檔案:行號、reuse 對象、驗證方式
都在計畫檔階段 1。做之前先按 ~/.claude/rules/ 派工（指揮官不下場、驗證不自驗）。

階段 2（可並行、不改碼）：跑 utarldd_accuracy 出 UTA 基準報告 + 寫 rPPG 計畫文件。
階段 3+ 是後續 roadmap，這次先別碰（會動數值紅線，要先問使用者）。
```

**給重置後自己的提醒**：
- 計畫檔在 `~/.claude/plans/`，不會被專案自動載入——務必手動 Read 一次。
- 三個探索與四個 QA 決策的結論都已濃縮進本計畫檔上半部「關鍵事實基礎」，不需重跑探索。
- 若要把計畫搬進 repo 版控（plan 檔不在 repo 內），可另存一份到 `docs/`，但別覆蓋既有檔。

---

## 進度更新 — session 2（2026-07-04，大量完成）

**已完成並推送 main（依序 commit）：**
- 階段 1 GUI 深色監控風重設計全部：`2d1ca80`(視覺系統) / `9b4877c`(心跳帶專屬區塊含HRV) / `1e17b30`(overlay可讀性) / `1286acb`(overlay中文改Pillow渲染修方塊)。
- 階段 2a UTA 準確度基準：`1620412`，`docs/history/2026-07-04-uta-accuracy-baseline.md`。根因＝尺度塌陷（門檻映射壓死分數）。
- 階段 2b rPPG 改善計畫：`a6824f0`，`docs/plans/rppg-improvement-plan.md`。
- 階段 3 持續閉眼強通道（重量級完整流程）：`43a60f7`，`docs/history/2026-07-04-eye-closure-channel.md`。
  修好「閉眼10秒僅輕度」——加 additive 強通道，閉眼10s→高度、3s→中度、眨眼/無閉眼 bit-identical。
  三重審查全過、golden PASS 免重建、424 passed。

**關鍵方法論教訓（已寫進 memory fatigue-accuracy-perclos）：**
- UTA「整段平均」與「即時瞬時體驗」是兩回事，別用前者評估後者（平均會稀釋間歇疲勞）。
- UTA drowsy 無「頭端正持續閉眼」場景 → closure 通道在 UTA/golden 零觸發、指標零變化 →
  **閉眼類即時修復 UTA 測不到**，只能靠合成驗算 + 實機驗證。
- additive 鐵律模式：新通道未觸發時恰 +0.0 逐位元回退 → golden 零漂移免重建、其他情境零污染。

**待使用者做（尚未完成的唯一驗證）：實機驗證**
- 戴機、頭端正、持續閉眼 ~10 秒 → 應顯示「高度疲勞」（3秒左右進中度）。同時目視 GUI 深色風 +
  心跳帶區塊（戴心跳帶勾校準才有數值，HRV 要暖機幾十秒）+ overlay 中文是否正常。

### 下個 session 接續 prompt（實機驗證後貼這段）
```
接續「非接觸式疲勞偵測系統」升級。先讀 docs/history/2026-07-04-three-line-upgrade-plan.md 的
「進度更新 session 2」段掌握現況，再讀 docs/history/2026-07-04-eye-closure-channel.md 與
docs/history/2026-07-04-uta-accuracy-baseline.md。memory fatigue-accuracy-perclos 有方法論教訓。

已完成：GUI 深色重設計全部、心跳帶區塊含HRV、overlay中文修復、UTA基準、rPPG計畫、
持續閉眼強通道（閉眼10s→高度，已推 main 43a60f7）。UTA 資料集在 C:\Users\USER\Downloads\UTA_test。

我實機驗證的結果是：【在此填我戴機閉眼10秒/GUI觀感/overlay中文的實測結果】

依結果選下一步：
(a) closure 通道太靈敏/不夠力 → 微調 onset(1.0s)/full(8.0s)/權重(engine0.35/beh0.30)，
    只改 gui/fatigue_scorer.py 常數，走重量級流程（三審+golden+數值聲明）。
(b) 修頭低 10-15° pitch 死區（閉眼偵測另一盲區，見 eye-closure-channel.md「既有邊界」與
    fatigue_engine.py pitch gate :1376-1409 / microsleep :1121）。
(c) GUI 觀感要微調（純視覺、快又安全）。
(d) 回頭做 rPPG 半頻/諧波抑制（docs/plans/rppg-improvement-plan.md，重量級）或資料集擴充。

紅線：碰 rppg/、fatigue_engine、fatigue_scorer 數值行為＝重量級（完整pytest+golden+三審+
數值聲明+先問我）。派工守 ~/.claude/rules/（指揮官不下場、驗證不自驗、同任務最多2輪）。
```

## 進度更新 — session 3（2026-07-05）

**實機驗證結果（使用者回報）：** 閉眼 10 秒判斷準確 ✅；但發現新誤判——視線往螢幕下方看
（頭微低或純視線下移帶動眼皮下垂）幾秒內被誤判中度以上疲勞。

**已完成：下視偵測器（重量級完整流程）**——`docs/history/2026-07-05-downgaze-detector.md`。
- 根因：pitch gate ±10° 硬開關且不讀視線；gaze_y 有算沒接線；低 EAR 推高 5 條路徑。
- 修法：gaze_y+EAR 帶+雙向去抖的 down-gaze detector，成立時同 pitch gate 語意暫停 EAR 衍生
  累積；未觸發逐位元回退。engine 單檔改動，scorer/rppg/worker 零改動。
- 驗證：438 passed（新增 14 測試含深帶正反例、負向對照）；golden PASS 零漂移免重建；
  三重審查一致可合入零 blocker。
- **注意**：本修復（視線下移→EAR 假性偵測）與 session 2 選項 (b) 的「頭低 10-15° pitch 死區」
  （pitch gate 與 EAR 路徑同時失效的漏報盲區）是**兩個不同機制**，(b) 仍未做。

**計畫外既有 bug——blendshape 命名不匹配：已證實、已實作修復、但被 A/B 量化否決未落地**
（詳見 `docs/history/2026-07-05-blendshape-fix-ab-result.md`）：修復後 fused AUC 0.750→0.722、
清醒影片非清醒幀比例 0.286→0.839（誤報爆炸）——下游 blend 門檻全是在訊號恆 0 狀態下
校準的,裸修鍵名反而變差。主樹已 revert 零殘留。未來重啟須「逐通道啟用+門檻重校+
逐通道 A/B」,見該文件「若未來要重啟」節。

### 下個 session 接續 prompt（實機驗證下視偵測器後貼這段）
```
接續「非接觸式疲勞偵測系統」。先讀 docs/history/2026-07-04-three-line-upgrade-plan.md「進度更新
session 3」與 docs/history/2026-07-05-downgaze-detector.md。UTA 資料集在 C:\Users\USER\Downloads\UTA_test。

已完成：下視偵測器（往下看誤判修復）；blendshape 命名 bug 修復已被 A/B 否決 revert
（docs/history/2026-07-05-blendshape-fix-ab-result.md,重啟須逐通道+門檻重校）。待辦依序：
(1) 頭低 10-15° pitch 死區（漏報盲區,與下視偵測器不同機制）；
(2) rPPG 半頻/諧波抑制（docs/plans/rppg-improvement-plan.md）；
(3) 尺度塌陷主修（uta-accuracy-baseline.md 階段3候選:perclos_high_th 下修等,需裁決）。

我實機驗證下視偵測器的結果（照 downgaze-detector.md 實機驗證清單 5 項）：
【填:往下看是否仍誤判/閉眼10秒是否仍準/其他觀感】

紅線：碰 rppg/、fatigue_engine、fatigue_scorer 數值行為＝重量級（完整pytest+golden+三審+
數值聲明+先問我）。派工守 ~/.claude/rules/（指揮官不下場、驗證不自驗、同任務最多2輪）。
```
