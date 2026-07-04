# 持續閉眼強通道（Persistent Eye-Closure Channel，2026-07-04）

> 疲勞判定數值行為變更報告（重量級）。對應三線升級計畫階段 3 第一項。
> 設計 spec 與驗算見本文件；程式碼 `gui/fatigue_engine.py`、`gui/fatigue_scorer.py`；
> 測試 `tests/test_eye_closure_channel.py`。

## 問題（診斷依據）

2026-07-04 opus 深診斷（逐環節真實常數代入）定位：**系統無「持續閉眼→高分」的專門通道**。
使用者實測「頭端正、坐著持續閉眼 ≥10 秒，只顯示輕度疲勞」。根因：

- 純閉眼（頭端正靜坐）的所有證據只透過 **PERCLOS 單通道**表達，而 PERCLOS 在 engine
  `fatigue_level`（`fatigue_engine.py:1489` `perclos_norm × 0.55`）與 scorer behavior pillar
  （`fatigue_scorer.py` `beh_w_perclos=0.55`）兩處都只佔 0.55 權重。
- 其餘 0.45 綁在「點頭微睡（頭低於 −15°）/ 瞇眼 / 皺眉 / 凝視」——純閉眼不會產生這些訊號。
- `microsleep` 只認點頭、`long_closed` 只改 status 標籤不進分數。
- 結果 behavior 天花板 ≈0.55，fused = 0.85×0.55 + 0.15×平靜 rPPG ≈ **0.47**，貼著中度邊界 0.40，
  稍有品質折損即掉回輕度。**最高危的持續閉眼，系統設計裕度過窄。**

（PERCLOS 60s 視窗稀釋**不是**主因：perc_s 在 PERCLOS 0.07 就飽和，閉眼10秒的 0.167 早已滿分，
縮短視窗無效。pitch gate 在頭端正時不觸發，亦非主因。）

## 設計（使用者裁決：加持續閉眼強通道，治本）

新增一條由「當前持續閉眼秒數」驅動的 **additive 強化通道**：

- 資料：eye 模組每幀從既有 `fat_dur` 導出 `eye_closure_sec`（睜眼/掉臉/pitch gate 關閉時 = 0.0，
  非跨幀累加）；`FatigueMetrics.eye_closure_sec` 新欄位。
- 映射純函式（engine 與 scorer **共用** `fatigue_scorer.compute_closure_s`，單一結構保證）：
  ```
  closure_s = clamp((eye_closure_sec - CLOSURE_ONSET_SEC) / (CLOSURE_FULL_SEC - CLOSURE_ONSET_SEC))
  ```
  常數：`CLOSURE_ONSET_SEC = 1.0`（低於此不計，擋眨眼/正常短閉眼）、`CLOSURE_FULL_SEC = 8.0`（起飽和）。
- engine `fatigue_level` 加 `+ closure_s × W_ENGINE_CLOSURE`（`w_engine_closure = 0.35`）。
- scorer behavior pillar 末端加 `+ BEH_W_EYE_CLOSURE × closure_s`（`beh_w_eye_closure = 0.30`）。
  `FusedFatigueScore.beh_eye_closure_score` 記錄供 breakdown。

### 為何 engine 0.35 與 scorer 0.30 不同
fused = 0.85×(0.7×scorer_behavior + 0.3×engine_fatigue_level) + 0.15×rppg。engine `fatigue_level`
只佔 blend 的 0.3、scorer behavior 佔 0.7；engine 端權重略高（0.35 vs 0.30）補償其較低的 blend 佔比，
使兩條路對 closure 都有足夠槓桿。**此為初始估值（v1），非嚴格推導**；依實機/資料驗證可微調
這兩個常數與 `CLOSURE_FULL_SEC`，調整只改常數不改結構。

## 效果驗算（真實程式實跑，rPPG 靜坐 sub≈0.1）

| 情境 | eye_closure_sec | closure_s | engine fatigue_level | fused | 等級 |
|---|---|---|---|---|---|
| 眨眼 0.3s | 0.3 | 0 | 0.55 | 0.4825 | 現況（未變）|
| 無閉眼 | 0.0 | 0 | 0.55 | 0.4825 | **bit-identical** |
| 閉眼 1.5s | 1.5 | 0.07 | 0.575 | 0.50 | 中度 |
| 閉眼 3s | 3 | 0.29 | 0.65 | 0.56 | 中度 |
| 閉眼 10s | 10 | 1.0 | 0.90 | 0.75 | **高度** |

閉眼10秒→高度、3秒→中度、眨眼/無閉眼完全不變。達成使用者要求。

## additive 鐵律與驗證

`closure_s = 0`（`eye_closure_sec ≤ onset`，即無長閉眼）時，兩處新增項恰為 `+0.0`（IEEE754
`x + 0.0 == x` 精確等值），fatigue_level 與 fused **逐位元回退**現有值。這保證改動只在真的持續
閉眼時生效，其他所有情境（含 replay/golden 絕大多數幀）不變。

- **golden check：PASS（零漂移）**——subject 04 三片無「頭端正持續閉眼>1秒」片段，通道不觸發，
  現有 UTA 回歸零影響，**不需重建 baseline**。
- **UTA accuracy 6-subject：所有指標與 baseline 完全相同**——UTA 的 drowsy 影片沒有純閉眼場景
  （多是打哈欠/點頭/低頭），通道不觸發。
- 完整 pytest 424 passed（既有 416 + 新 8，含 bit-identical 測試）。

## 誠實限制（重要）

- **UTA 資料集無法驗證此修復**：UTA drowsy 不含「頭端正持續閉眼」場景，故 UTA/golden 指標零變化。
  這修的是即時瞬時場景（使用者實測痛點），價值靠上表合成驗算 + **使用者實機驗證**（戴機閉眼10秒
  應顯示高度）。UTA 平均指標與即時瞬時體驗是兩回事（見 docs/2026-07-04-uta-accuracy-baseline.md）。
- ~~誤報取捨（使用者已接受）：長時間正常下視/閉眼休息會判疲勞~~ **此取捨已於 2026-07-05
  被下視偵測器推翻**：實機驗證發現「往下看幾秒即誤判中度」不可接受，已加 down-gaze detector
  暫停下視情境的 EAR 衍生累積（見 docs/2026-07-05-downgaze-detector.md 與
  tests/test_downgaze_gate.py）。閉眼休息（EAR 跌破 floor）仍會判疲勞，此半句取捨仍成立；
  `CLOSURE_ONSET_SEC=1.0` 擋眨眼與正常短閉眼不變。
- 顯示接線未做：`eye_closure_sec` 目前只進分數計算，未接 overlay/dashboard 顯示（若要顯示秒數需另接）。
- 既有邊界（非本次引入、不修）：`_fat_enter_t == 0.0` 的 truthy 判斷理論上會使該幀 fat_dur 卡 0，
  但實務不可達（校準需 ~5s，t_now 早已 >0）、失敗方向安全（低報）。
