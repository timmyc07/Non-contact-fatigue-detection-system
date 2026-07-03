# 疲勞判斷準確度校準（2026-07-03）

## 問題

使用者實測回報：特徵數值都有捕捉到，但輸出的疲勞等級與真實疲勞程度差距很大。系統的
`README.md` 也早已記錄「融合分數未隨 `0 -> 5 -> 10` 穩定上升」。

## 量測方法（先量再改）

新增 `scripts/utarldd_accuracy.py`（與 golden「回歸偵測」不同，本工具量「準確度」）：
把 UTA-RLDD 整段標籤（0=Alert / 5=Low Vigilant / 10=Drowsy）當序位真值，量測各分數欄位
能否隨標籤單調上升、以及 Drowsy 與 Alert 的成對 AUC。校準集：subject 01–06 × label 0/5/10，
每片 1200 幀（純運算指標測試見 `tests/test_utarldd_accuracy.py`）。

## 診斷：訊號在，但被計分映射壓死

各通道對 label 的分辨力（AUC，>0.7 可用）：

| 通道 | AUC | 判讀 |
|---|---|---|
| avg_perclos | **0.79** | 唯一強訊號 |
| max_perclos | 0.76 | 同源有效 |
| lowvig_frac | 0.64 | 弱 |
| squint_frac | 0.54 | 雜訊 |
| drowsy+critical_frac | 0.50 | 從不觸發（門檻太高） |
| avg_bpm | 0.44 | 非疲勞單調量 |
| avg_blink_temporal | **0.42** | 反訊號 |
| microsleep_frac | **0.42** | 反訊號（清醒 0.043 > 嗜睡 0.0） |

原始 PERCLOS 的 AUC 0.79 證明訊號存在，但最終輸出 `avg_fused_score` 的 AUC 只有 0.53、
且**倒著走**（清醒 0.020 > 嗜睡 0.009）。兩個病根：

1. **PERCLOS 計分門檻脫離實際範圍**：`perclos_mild_th=0.10 / perclos_high_th=0.25`，
   但系統實際產生的 PERCLOS 只有 0.005–0.067，永遠到不了計分起點 0.10 → 唯一有效訊號恆輸出 0。
2. **composite 把大權重壓在反訊號上**：微睡（AUC 0.42）權重 0.20–0.30、blink_temporal（0.42）
   權重 0.25，兩者在此資料上是反訊號，把好訊號淹沒成雜訊。

微睡反向的原因：微睡靠「頭下垂 >1.5s」偵測，UTA-RLDD 為坐姿 webcam，清醒者低頭（看下方）
比嗜睡者更常見。此為資料特性——對真實無人機駕駛員的點頭，微睡仍有價值，故降權而非移除。

## 修法（資料驅動，不動 PERCLOS 量測本身）

PERCLOS 本身 AUC 0.79 沒問題，只需讓它進得了輸出、壞訊號別再拖：

- `gui/fatigue_scorer.py` FuserConfig：`perclos_mild_th 0.10→0.015`、`perclos_high_th 0.25→0.07`；
  行為子權重重配並仍總和 1.0（PERCLOS `0.35→0.55`、blink_temporal `0.25→0.12`、microsleep `0.20→0.10`、
  gaze `0.10→0.08`、frown `0.00→0.05`；squint/yawn 不變 0.05）。
- `gui/fatigue_engine.py` FatigueParams：狀態門檻 `low_vigilance_perclos_th 0.10→0.02`、
  `tired_perclos_th 0.25→0.05`（舊值系統永遠到不了，DROWSY 狀態從不觸發）。
- `gui/fatigue_engine.py` composite：PERCLOS 以**獨立常數** `perclos_composite_full=0.05` 正規化到 0–1
  後給 0.55 權重，微睡 `0.30→0.12`。此常數與狀態門檻 `tired_perclos_th` 刻意分離（值相同但可各自
  調整），避免「想調 DROWSY 狀態靈敏度卻連動分數尺度」（三重審查發現的耦合）。
- `gui/utarldd_replay.py`：驗證報表的 `perclos_low_frames`/`perclos_drowsy_frames` 計數門檻改為引用
  引擎狀態門檻（原硬編碼 0.10/0.25 在新 operating range 下恆為 0，與狀態欄矛盾）。

## 結果（校準集 subject 01–06）

最終輸出 `avg_fused_score`：

| | label 0 | label 5 | label 10 | 單調 | AUC [95% CI] | 塌陷率(<0.20) |
|---|---|---|---|---|---|---|
| 改前 | 0.020 | 0.011 | 0.009 | ❌ 反向 | 0.53 [0.19–0.89] | 100% |
| 改後 | 0.036 | 0.109 | 0.186 | ✅ | **0.75** [0.39–1.00] | 50% |

輸出從「比亂猜差、倒著走」變成隨疲勞單調上升、點估計 AUC 0.75（逼近 PERCLOS 天花板 0.79）。
狀態路徑 AUC 亦 0.56→0.75。**注意樣本量**：每組僅 6 片，bootstrap 95% CI 很寬（下界 0.39），
單次跑未達統計顯著（見下方限制）。真正的證據力來自三件事同時成立且方向一致：點估計大幅上升、
單調性由反向翻正、且在未見過的留出集重現。

## 留出驗證（subject 07–12，未參與校準）

最終輸出 `avg_fused_score`（subject 07–12，未參與校準）：

| | label 0 | label 5 | label 10 | AUC | 原始 PERCLOS 天花板 |
|---|---|---|---|---|---|
| 留出 | 0.177 | 0.167 | 0.255 | **0.69** | 0.72 |

未見過的 subject 上融合 AUC 0.69（95% CI 0.36–0.97），緊貼該組原始 PERCLOS 天花板 0.72
（校準集為 0.75/0.79）。方向與校準集一致：composite 在新資料上一樣把 PERCLOS 訊號傳到輸出，
未反轉或崩掉——與「過擬合到 01–06」的預期相反。但 CI 同樣寬（n=6），這是**方向性一致的佐證，
非統計顯著的定論**。（label 5「Low Vigilant」為模糊中間類，本就最難分，L0/L5 些微逆序不影響
Alert↔Drowsy 判別。）

## 限制與後續（誠實條款）

- **校準集小**：僅 6 個 subject 校準、6 個留出。門檻與權重對 UTA-RLDD 的 PERCLOS 尺度校準；
  真實無人機駕駛場景（不同相機/幀率/光照）的 PERCLOS 絕對值可能不同，門檻需以**真人、你的場景**
  重新驗證。UTA-RLDD label 是整段影片類別、演出來的坐姿汽車情境，不能取代真人測試。
- **絕對門檻無法完全跨個體轉移（最重要的後續）**：留出組 07–12 的清醒 PERCLOS 基線天生偏高
  （清醒 avg_fused 0.177，逼近 0.20 門檻），代表不同人的 PERCLOS 絕對值差異大，固定門檻會讓
  某些人的清醒態偏高。目前的 per-session EAR 校準只正規化 EAR 尺度、未正規化 PERCLOS 基線。
  **下一步最高槓桿**：加一段「清醒基線 PERCLOS」校準，把每個人的分數改成相對其自身清醒基線的
  偏移量（而非絕對值），可望同時提升跨個體一致性與真實場景轉移性。
  → **已於 2026-07-04 實作**（PERCLOS/gaze/frown/blink/yawn 全面個人化基線 + GUI 記錄按鈕），
  見 `docs/2026-07-04-personal-baseline-personalization.md`。準確度提升的最終量化仍待在有資料集/真人
  場景的機器上以 per-subject profile 注入版 `utarldd_accuracy.py` 復量。
- **統計顯著性不足（誠實條款）**：每組 6 片，AUC 的 bootstrap 95% CI 很寬且下界接近 0.5
  （校準 0.39、留出 0.36），單次量測**未達 α=0.05 顯著**。本次結論靠「點估計大幅上升 + 單調性
  翻正 + 留出重現」三者方向一致來支撐，不是靠單一 AUC 的統計檢定。要達顯著需擴大到更多受試者
  （UTA-RLDD 全 60 人或真人場景），這是後續必要工作，`scripts/utarldd_accuracy.py` 已內建 CI 輸出。
- **未達完美**：AUC 0.75 仍非 1.0；PERCLOS 是唯一強訊號，其餘通道（眨眼動態、微睡）在此資料
  貢獻有限。要再提升需要更能反映慢性疲勞累積的特徵，或針對場景重新蒐集標註資料。
- **迴歸保護**：本次為重量級數值變更，golden baseline 已重建並在 commit 逐項聲明；
  日後改動用 `scripts/utarldd_accuracy.py` 復量，確認 AUC 不退化。
