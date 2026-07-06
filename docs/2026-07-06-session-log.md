# 工作日記 2026-07-06

## 今日 commits（main）

- `5254d58` feat(gui): 新增「自動採集」一鍵按鈕（啟管線+metrics 記錄+可選心跳帶 capture、倒數自動停）
- `12708e1` fix(gui): 自動採集停止入口補回滾 + 精確化錄製誤停防護（review Warning 收尾）
- `26d584d` feat(gui): 主 GUI 全面重設計為側邊導航四頁 dashboard

memory 更新：`~/.claude/projects/.../memory/upgrade-directions-95pct-eval-2026-07-06.md`（完整診斷鏈與待辦）。

---

## 主線一：GUI 全面重設計（✅ 完成、已 commit/push）

使用者裁決：全面重設計佈局+風格、心跳帶做獨立區、佈局＝**左側邊導航**、風格＝**深色監控風精緻化**。

- `gui/main_window.py` 從單一長捲動 → 「左側導航 QListWidget +右側 QStackedWidget 四頁（監測/心跳/回測/設定）」。
- 監測頁：鏡頭預覽 + 疲勞/rPPG/HRV 指標卡（從 worker 快照唯讀訂閱，未改 overlay 視窗本身）+ 主控制 + 狀態列。
- 心跳頁：六分區完整面板（背景校準/連線/即時/HRV/rPPG校準/設備設定），涵蓋 40+ 欄位。
- 純 GUI 版面重組，未動任何數值路徑/worker/overlay；獨立 code review 驗證既有 signal/slot 零漏接；煙霧測試四頁四導航關鍵 widget 全在、pytest 438 passed。
- 使用者已實機確認「版面可以」。

---

## 主線二：PERCLOS「開機即中度 / 疲勞過 47% 卡住」— 診斷到底、方向已定、卡在資料

> 這是本 session 花最多力氣的線。兩個使用者症狀（開機即中度、過 47% 不降）**是同一個根因**。

### 診斷鏈（實機 db 逐層定位）
開機即中度／47% 卡住 ← `perclos_score` 恆釘死 1.0 ← 使用者清醒 PERCLOS 高達 **0.13~0.19**（正常應 <0.08）← 使用者**清醒時真的持續半閉眼**（每約 8s 一次、每次~1s，gaze 中性、頭不低；個人眼型~60% + 桌面久坐~30%，非雜訊、非誤判睜眼）。

- **47% 精確 = `0.85(行為權重)×0.55(行為子分數)`**；飽和點 `perclos_composite_full=0.05`（`fatigue_engine.py` 附近）與 `PERCLOS_HIGH_TH_DEFAULT=0.07`（`fatigue_scorer.py:43`）遠低於使用者操作區 0.17~0.28 → 0.07 以上全映滿分、頂端無動態範圍 → 體感「怎樣都不降」。**非 latch/sticky bug**（microsleep latch 全程未觸發、perclos 60s 窗會釋放只是慢）。

### 已排除/否決的方向（都經實機 A/B 或掃描，勿重試）
- **close_fat 校準（含用 FL3D 資料集）＝否決**：掃描證實 close_fat 0.75→0.45 分數全程 1.0，要 0.40（眼開 40%）才動、已不安全。close_fat 非有效槓桿。
- **單參數 `perclos_close_ratio`＝否決**：傷 UTA drowsy AUC（0.72→0.58）、對 db1 無效（comp_full 飽和是共因）。
- **用資料集校準全域門檻＝對此使用者無效**：10 位 UTA 清醒者 PERCLOS≈0（無人達 0.13），使用者的「清醒半閉」失敗模式在乾淨錄製資料集中不存在，無從校準/驗證。
- 使用者兩直覺經資料證實：「撐大眼睛沒用」（分數已飽和，corr(ear,fatigue)=-0.17/-0.26）、「暖機階段就該學個人生理」（個人化 high_th 是唯一有效槓桿）。

### 選定方向：運行中線上學個人清醒 PERCLOS → 動態個人化 high_th（使用者裁決）
- 機制有效性高（門檻抬過 baseline → fused 0.47→<0.15，收斂 20-35s，開機暫定值不誤判）。`profile=None`/UTA/golden 逐位元零漂移。
- **卡在兩個生死問題（需使用者 drowsy 資料才能判）**：
  1. **純線上學安全護欄不穩**：防「把真疲勞學成清醒 baseline→自我麻痺」的佐證訊號（blink_temporal/microsleep/squint）**實機恆 0**（同 blendshape 死通道病根），gate 是空的；唯一真護欄是絕對上限，正確值需 drowsy 定。
  2. **使用者清醒 PERCLOS(0.19-0.25) 疑與真疲勞重疊、margin 極薄**：若真重疊則 PERCLOS 對此人失去鑑別力，個人化再怎麼調都沒用，須往上游查或換訊號。
- 安全替代：半自動錄基線（學習窗鎖已知清醒時段）比純線上學安全，但使用者傾向拒手動。

### 落地前需要的資料（使用者待錄，用「自動採集」按鈕）
1. **裝疲勞 1-2 段各 1-2min**（持續閉眼/慢眨眼/打瞌睡）→ 定疲勞 PERCLOS 天花板、確認與清醒是否可分。
2. **刻意撐大眼睛 1 段**→ 確認撐大時 EAR 降不降（區分眼型/疲勞/EAR 算法偏差）。

**分岔**：清醒與疲勞 PERCLOS 有間隔 → 個人化門檻可行（定 ceiling 後落地）；重疊 → PERCLOS 對此人失效，往上游查 EAR 校準/眼型或換疲勞訊號。

---

## 主線三：HRV 不顯示（⏳ 等使用者連線確認）

- **非接線 bug**：新心跳頁 HRV label 接線正確，值算出來會正常填入。
- 真因＝UX：整個心跳頁資料綁在控制列「心跳帶真值校準（背景）」勾選框，不勾就不連線、全頁「—」；且使用者先前 belt capture 都 belt_bpm=null（沒連上）。
- HRV 需 `compute_watch_physio` 的 min_samples=8、window_sec=90 → 暖機約 10-90s。
- **待使用者**：`python -m scripts.hr_belt_monitor --use-config` 確認連得上 → 勾框等暖機 → 回報 HRV 出不出來。出得來 → 加心跳頁「連線心跳帶」開關做 UX 改善；連不上 → 查硬體/設定。

---

## 其他保留線（來自四方向 95% 評估，見 memory）
- **rPPG 次諧波低鎖**：問題真實（主導 71% 誤差）但非 2x/0.5x 諧波，是 band-pass 下緣雜峰低鎖。`docs/rppg-improvement-plan.md` 的諧波 notch 方案**不對症勿照做**。待跨條件 belt capture（錄前先 `hr_belt_monitor --use-config` 確認連上）+ 針對次諧波重設計。
- pitch 死區（45%）、尺度塌陷（60-65%，status_active_fraction NO-GO）：建議擱置。

---

## 明日接續 prompt

> 複製以下給明天的 session：

```
接續 2026-07-06 的工作，請先讀 docs/2026-07-06-session-log.md 與 memory
upgrade-directions-95pct-eval-2026-07-06.md 了解脈絡。今日三條待續線：

1.【HRV，優先確認】我昨天請使用者試心跳帶連線。若使用者回報「勾了『心跳帶
   真值校準（背景）』+ 暖機後 HRV 有顯示」→ 在新心跳頁（gui/main_window.py
   _build_belt_page）加一個明顯的「連線心跳帶」開關/改善文案做 UX 改善（中量級
   GUI，不碰數值），做完 commit。若回報「連不上」→ 查 config/hr_belt.json 與
   hr_belt_ble.py 的裝置連線/掃描。

2.【PERCLOS 個人化，等資料】若使用者已用自動採集按鈕錄了 ①裝疲勞段 ②刻意撐大眼段
   （recordings/metrics_*.db，非 utarldd/replay），自己抓最新檔，離線分析：
   (a) 疲勞 PERCLOS 天花板 vs 清醒 0.19 是否有可分間隔；(b) 撐大時 EAR 降不降。
   有間隔→設計個人化 high_th 落地（重量級：需 golden 零漂移+三重審查+數值聲明，
   線上學安全護欄要能防自我麻痺）；重疊→PERCLOS 對此人失效，往上游查 EAR/眼型。
   注意：昨天的 scratchpad 設計檔已被清，關鍵設計結論在本日記主線二。

3.【rPPG 次諧波，等資料】若使用者錄了跨條件 belt-truth capture（先確認 belt_bpm
   非 null），針對「band-pass 下緣雜峰低鎖」重設計方案並離線 A/B（勿用諧波 notch）。

紅線提醒：碰 rppg/、fatigue_engine、fatigue_scorer 數值路徑一律重量級流程 +
使用者裁決；所有「先驗證再落地」，本 session 已用它擋下 3 個會傷系統的修法。
```
