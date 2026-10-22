# 全專案審核報告（2026-07-03）

## 審核方法

六軸並行專項審查（每軸一個獨立 agent，唯讀），所有 blocker/major 級 findings 再交由 **fresh-context 對抗驗證者**（預設立場：反駁該 finding）逐一覆核後才定級。未經對抗驗證的推測性 findings 一律標 PLAUSIBLE。

| 軸 | 範圍 | 審查 | 驗證 |
|---|---|---|---|
| 1 | rPPG 數值演算法（POS/濾波/PSD/校準鏈/BLE 協定） | opus | opus 對抗驗證 |
| 2 | 疲勞引擎與融合分數 | opus | opus 對抗驗證 |
| 3 | 併發/執行緒/資源生命週期 | opus | sonnet 對抗驗證 |
| 4 | Web 與安全（區網威脅模型） | sonnet | 設計層事實，未另派驗證 |
| 5 | 測試覆蓋與品質 | sonnet | pytest 實跑佐證 |
| 6 | 文件—程式一致性與平台 | sonnet | agent 自行以 --help/pip 實測 |

審核期間全套件 `pytest -q` 168 passed。以下行號以 commit `550a77f` 為準。

## 總覽

| 嚴重度 | 數量 | 說明 |
|---|---|---|
| **P0（高，已對抗驗證 CONFIRMED）** | 2 | 皆為「該警報時不警報」的漏報路徑 |
| **P1（中，已驗證或實測）** | 7 | 含 1 項由 blocker 下修、1 項 PARTIAL |
| **P2（PLAUSIBLE，未驗證）** | 3 | 需進一步實驗確認 |
| Minor | ~18 | 各軸報告內列明 |

## 修復狀態（2026-07-03 同日完成，含臉部特徵模組深度審查）

使用者指示全面修復，並對「MediaPipe 臉部行為特徵捕捉模組」加做兩軸深度審查（幾何正確性＋時序邏輯，皆 opus）。結果：

- **深度審查追加裁決**：P2-1/P2-2/P2-3 全數 CONFIRMED（升 major）；新增 major：B2（微睡在 pitch 校準前可觸發＋過期姿態無年齡上限）、G-M1（低頭時 EAR 無 gate→誤報 DROWSY）、G-M2（低頭誤觸 squint）、G-M3（眨眼污染掃視偵測→漏報空洞凝視）。landmark 索引全數驗證無鏡像錯誤（僅命名與 MediaPipe 官方相反，屬命名污染）；MAR 的 86/316 標 SUSPECT 未改。
- **已修復**（三重審查三軸皆判可合入；golden：04/0、04/5 零漂移，04/10 漂移逐欄歸因後重建 baseline）：
  P0-1（無臉寬限期 1.0s，三呼叫點傳同源 t_now）、P0-2（微睡 latch 持續＋警報危險群組共用計時＋微睡 0.5s 快速觸發）、
  P1-1（BPM 確認窗改 3 樣本×重算節奏推導，舊死碼移除）、P1-2（雙 pillar 失效顯示「無資料」灰）、P1-3（等級降級遲滯 0.03＋警報計時群組）、
  P1-4 部分（LAN shared-token 認證＋Socket.IO 拒連；**TLS 未實作**，以 GUI/README 警告揭露）、P1-6（相機 try/finally＋MSMF timeout 盡力設定）、P1-7（README dev 依賴）、
  P2-1（掃視暖機旗標）、P2-2（EAR 校準 sane-min 0.20＋pitch offset sanity ±20——初版 ±12 被 golden 抓到誤傷正常相機傾角後校正）、P2-3（PERCLOS 分母改可量測時間＋floor 5s）、
  B2（pitch 校準前禁微睡＋姿態過期凍結計時不清空）、G-M1/G-M2（±10° 對稱 pitch gate，需 pose 新鮮）、G-M3（眨眼幀凍結凝視）。
  新增測試：test_fatigue_engine_behavior.py（10）、test_fatigue_scorer.py（6）、alarm（+3）、rppg（+3）、web token（+11）。
- **數值行為影響聲明**（golden 04/10 預期漂移）：max_perclos 0.106→0.034（開機假尖峰消除＋可量測時間分母）、avg_perclos −0.011、LOW_VIGILANCE −3 幀（凝視暖機＋眨眼排除假掃視）；Alert/Low-Vigilant 片零漂移。微睡 latch 使 fatigue_level 在整段低頭期間 +0.30（原單幀）——04 子集無微睡事件故 golden 未覆蓋，由單元測試鎖定。
- **未修（殘留）**：TLS/安全標頭（僅警告揭露）、cap.read() 驅動 hang 的根治（僅 MSMF timeout 緩解）、時序 minors（EMA 對 FPS 相依、blink_rate 正規化、scorer 趨勢牆鐘、眨眼門檻 raw/smooth 混用、掃視 FPS 相依）、幾何 minors（命名鏡像、head pose 註解/焦距粗估、MAR 86/316、虹膜混軸、眉距品質 gate）、−10°~−15° 低頭死帶（設計取捨，EAR 與微睡皆不覆蓋該區間）、overlay/dashboard 掃視上色未同步暖機門檻、web minors（CDN SRI、fb_logout CSRF）。

---

## P0：漏報路徑（建議優先修復）

### P0-1 無臉單幀即清空 EAR 校準 → 5 秒重校期間警報全黑

- 位置：`gui/fatigue_engine.py:389-397`（`reset(full=False)` 仍設 `calibrated=False`）、`:1125-1131`（`on_no_face`）；`gui/fatigue_worker.py:472-473` 與 `gui/combined_worker.py:267-270`（每個無臉幀無條件呼叫，無 debounce）；`gui/alarm_player.py:184-186` 與 `decide_alarm_trigger` 開頭（`if not calibrated: return`，無旁路）。
- 失效情境：MediaPipe 單幀掉臉（低頭、遮擋、運動模糊）→ 校準作廢 → 重跑 `calib_sec=5.0` → 期間疲勞偵測與警報全部靜音。**「低頭」正是疲勞情境本身，形成最該響時靜音。**
- 對抗驗證：CONFIRMED（反駁全數失敗：無連續幀門檻、無寬限期、無警報旁路）。
- 建議修法：`on_no_face` 加連續無臉幀數/時間門檻（例如連續 >0.5 秒才降級），短暫掉幀只凍結不清空校準。

### P0-2 微睡（MICROSLEEP）狀態僅維持一幀 → 最高優先警報實質永不觸發

- 位置：`gui/fatigue_engine.py:1005-1017`（`_microsleep_fired` 使 alert 只在觸發那一幀為 True）、`:1271-1272`；`gui/alarm_player.py:63-82`（需同 status 持續 `trigger_delay_sec=2.0` 才播放，且 delay gate 在 escalation 之前）。
- 失效情境（驗證者時序推演）：t=0 status 變 MICROSLEEP、警報計時歸零；t=+1 幀 alert 已 False，status 落回 CRITICAL（眼閉）或 OK（純點頭）→ 計時再歸零。微睡警報永遠湊不滿 2 秒；單幀 blip 還會**重置** CRITICAL 的計時，反而延後其他警報。純點頭型微睡（眼未持續閉合）則完全無警報。
- 對抗驗證：CONFIRMED。
- 建議修法：MICROSLEEP 改為持續狀態（latch 保持至條件解除），或警報端給微睡獨立的即時觸發路徑（不受 2 秒 delay 限制）。

---

## P1（已驗證 / 實測）

1. **BPM 跳變確認機制為死碼**（由 blocker 下修）— `rppg/rppg_worker.py:859-863, 937-961, 1077-1081`。`_BPM_JUMP_CONFIRM_SEC=2.0` < 頻譜重算間隔 5.0s，pending 佇列每輪被 prune 到 1 筆，`CONFIRM_COUNT=4` 結構性不可達（`:953` 為死碼）。**實際後果（驗證者下修依據）**：只凍結平滑 `bpm`，`raw_bpm` 據實回報；心跳帶校準因 `reject_bpm_guarded=True`（`rppg/adaptive_calibration.py:40`、`rppg/calibration.py:189`）拒收 guarded 樣本、不受污染；疲勞融合有效影響僅約 4.5%。真實危害：真實持續性心率變化 >25 BPM（如出力、緊張）時平滑 BPM 永遠追不上。修法：確認窗改以樣本數計，或令窗長 ≥ COUNT×重算間隔。
2. **雙 pillar 同時失效時主 gauge 顯示「清醒/綠」** — `gui/fatigue_scorer.py:336-338`（score=0.0）＋ `gui/preview_overlay_window.py:659-662`（主 gauge 未 gate 可用性，子條有灰化）。警報走 `fatigue.status` 不受影響（NO_FACE 正確），屬誤導性顯示而非漏報。修法：`rppg_available`/`behavior_available` 皆 False 時主 gauge 顯示「無資料」。
3. **等級/狀態無遲滯＋警報計時重置**（PARTIAL）— `gui/fatigue_scorer.py:162-166, 329`（硬門檻、fused score 無 EMA）、`gui/alarm_player.py:63-82`（任何 status 變化重置 `status_since`，DROWSY/CRITICAL 無共用危險群組）。底層眼閉有雙門檻遲滯故 CRITICAL 相對穩定；易抖處為 OK↔LOW_VIGILANCE↔DROWSY。修法：警報端把 DROWSY/CRITICAL/MICROSLEEP 視為同一「危險群組」計時；等級門檻加遲滯帶。
4. **LAN 模式無認證即廣播人臉影像與生理數據** — `gui/main_window.py:1082`（勾選→綁 `0.0.0.0`）、`gui/web_server.py:789-818`（Socket.IO 無認證）。同網段任何裝置可即時觀看。修法：LAN 模式加 token/Basic Auth＋GUI 明確警告。
5. **LAN 模式純 HTTP 無 TLS/安全標頭** — `gui/web_server.py:875-884`。同網段被動側錄即可還原影像與生理資料。修法：自簽憑證選項或至少文件警告。
6. **相機主迴圈無 per-frame try/except、`cap.release()` 不在 finally** — `gui/camera_stream_worker.py:221-267`。迴圈內例外會洩漏相機裝置（驗證：結構 CONFIRMED、觸發機率低——`put_latest` 已有防護）。修法：迴圈包 try/except＋release 移入 finally。
7. **README Setup 缺 `requirements-dev.txt`** — `README.md:28-43` 只裝 requirements.txt，全新環境照文件裝完跑不了 pytest（axis-6 agent 以 pip show 實測確認）。修法：Setup 段補一行 dev 依賴安裝。

另：**`cap.read()` 被驅動 hang 住時 stop 無效**（`gui/camera_stream_worker.py:221-222`、`gui/main_window.py:1918-1922`，wait(3000) 逾時後執行緒孤兒化持有相機）— CONFIRMED 但依賴驅動異常才觸發，介於 P1/P2；GUI 不會卡死是現有設計的優點。

## P2（PLAUSIBLE，建議實驗確認後再修）

1. 融合層凝視分數缺 warmup 保護：開機初期 `saccade_freq_pm≈0` → 假性拉高（`gui/fatigue_scorer.py:253-259`；引擎端有保護、融合端沒有）。
2. 校準期無「基準需反映清醒」合理性檢查：開機即疲勞會把門檻校到疲勞態（`gui/fatigue_engine.py:607-615, 984-989`）。
3. PERCLOS 分母用牆鐘、分子只計 `fatigue_ok` 幀：品質不穩時系統性低估（`gui/fatigue_engine.py:481-496, 690-709`）。

## 測試覆蓋缺口（軸 5）

85% 權重的行為疲勞引擎與融合分數幾乎無直接數值測試——**P0-1/P0-2 若有對應測試早會被攔下**。無測試的核心純運算：`fatigue_engine` 的 EAR/MAR/head-pose 與眨眼/PERCLOS/微睡模組、`FatigueFuser` 子分數與 `_score_to_level` 邊界、`pos_pulse`、ROI 系列函式、`CalibrationVersionStore` 載入容錯。

最值得補的 5 個測試（依序）：
1. 眨眼/PERCLOS/微睡動態回歸測試（新檔 `tests/test_fatigue_engine_behavior.py`）——修 P0 時一併加。
2. `FatigueFuser` 子分數與等級邊界測試。
3. `pos_pulse` 獨立單元測試（合成訊號驗頻率還原）。
4. ROI 遮擋/均值函式邊界測試。
5. `CalibrationVersionStore` 重啟載入與 manifest 損毀容錯測試。

## 已確認健全（審過、無 finding，未來 session 不必重複審）

- **rPPG 數學**：Butterworth 參數與 fallback、Welch 窗長/解析度、峰值插值、NaN/空陣列/短訊號邊界、HRV（MAD 清洗、SDNN ddof、RMSSD、LF/HF 除零）、**校準鏈無自我回饋（CONFIRMED）**、bias 疊加順序無雙重套用。
- **BLE**：0x2A37 flag/8-16bit/RR 1/1024s/長度檢查全符合規格；斷線重連與 stop 路徑乾淨。
- **併發**：frame queue 有界背壓、跨執行緒 signal 全 queued、啟停順序無死結、SQLite 單執行緒寫＋WAL 並行讀、QImage 一律深拷貝。
- **Web 安全**：SQL 全參數化、路徑遍歷三層防護、XSS sink 全 escape、`/api/fb/*` 限本機、無秘密入版控、shutdown token 常數時間比對。
- **文件**：所有 README/CLAUDE.md 的 CLI 宣稱與 argparse 逐一相符；requirements 與實際 import 一致（除 dev 缺口）；平台分支與選配 import guard 正確；無手錶模式殘留（除一份海報設計文件未加已取代標記）。

## Minor 摘要（詳見各軸完整報告）

軸 1：`pos_pulse` 實為 CHROM 投影（命名/文件不符）、SQI 對帶通後訊號計算鑑別力弱、bpm_hint 夾取範圍不一致、未使用參數。軸 2：融合微睡分數累計不衰減、幀計數校準低 FPS 漂移、關鍵路徑缺測試。軸 3：停止時未先斷訊號（殘留 queued 事件）、`write_live_feed` 非原子寫、VideoRecorderWorker 啟動失敗不 emit finished（驗證後下修：執行緒有無條件回收，非洩漏）。軸 4：CDN 缺 SRI、`fb_logout` 缺 CSRF、`_ensure_lan_endpoint_allowed()` 誤導性死碼、API 回傳 `str(e)` 洩漏路徑。軸 6：海報文件手錶描述未標已取代、README 引用不隨版控的範例路徑。

## 修復路線建議

1. **先修 P0-1、P0-2**（皆屬重量級：碰 fatigue_engine 數值路徑——走完整流程：全量 pytest＋golden check＋三重審查＋數值行為影響聲明）。修復同時補軸 5 的 top1/top2 測試把行為釘住。
2. P1 依序：README dev 依賴（輕量、5 分鐘）→ 主 gauge 無資料顯示（中量）→ 警報危險群組計時（重量）→ BPM 確認窗（重量）→ 相機 try/finally（中量）→ LAN 認證/TLS（中量，或短期先只做 GUI 警告文字）。
3. P2 三項先設計實驗（UTA-RLDD 或錄影回放）確認再動，避免無據改數值行為。

## 審核產物

各軸完整 findings（含全部 minor 與時序推演）當時落於 session scratchpad `audit/1-rppg-numerics.md` ~ `6-docs-platform.md`；本報告已收錄全部 P0/P1/P2 與 minor 摘要，scratchpad 消失不影響可追溯性（行號以 commit `550a77f` 為準）。
