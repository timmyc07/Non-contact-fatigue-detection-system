# UTA-RLDD 疲勞判斷準確度基準（2026-07-04，階段 2a）

> 對應三線升級計畫階段 2a。定位：用實機 UTA-RLDD 資料集量化現況準確度，
> 找出「哪個門檻脫離 operating range」，作為階段 3 調門檻的證據基礎。
> **本文件只量測、不動任何數值。** 工具：`scripts/utarldd_accuracy.py`（純量測、不 gate）。

## 方法

- 資料：`C:\Users\USER\Downloads\UTA_test` 前 6 位 subject × 3 label（0=Alert / 5=Low Vigilant /
  10=Drowsy）＝ **18 支影片**，每片 `--max-frames 1200`、`--jobs 4`。0 失敗。
- 指標：各 label 分數分佈、Spearman 序位相關（label vs 分數，理想 +1）、成對 AUC
  （label-10 分數 > label-0 的機率，0.5=亂猜、1.0=完美分離）、尺度塌陷（多少比例 Drowsy
  片段連第一/二道等級門檻都到不了）。
- 系統等級門檻（`gui/fatigue_scorer.py` `_LEVELS`）：輕度 0.20 / 中度 0.40 / 高度 0.60 / 極度 0.80。

## 結果

| 指標 | Spearman | AUC (Drowsy>Alert) | 塌陷<輕度(0.2) | 塌陷<中度(0.4) | label0→5→10 mean |
|---|---|---|---|---|---|
| avg_perclos | **+0.401** | **0.792** | 100% | 100% | 0.006 → 0.018 → 0.031 |
| avg_fused_score | +0.380 | 0.750 | 50% | **100%** | 0.036 → 0.109 → 0.186 |
| avg_fatigue_score | +0.341 | 0.750 | 33% | 83% | 0.059 → 0.155 → 0.254 |
| p95_fused_score | +0.275 | 0.667 | 33% | 50% | 0.134 → 0.205 → 0.286 |
| p95_fatigue_score | +0.258 | 0.653 | 33% | 33% | 0.192 → 0.297 → 0.355 |
| status_active_fraction | — | 0.750 | — | — | 0.286 → 0.378 → 0.616 |

（AUC 95% CI 下界普遍偏低如 0.39–0.47，因 n=6/label 小樣本；趨勢可信、絕對值待全量確認。）

## 核心診斷

**訊號能分辨，但分數映射把動態範圍壓死了。**

1. **方向正確、有分離度**：所有指標 label 0→5→10 單調遞增；PERCLOS AUC 0.79、融合 0.75、
   status_active_fraction 0.75（label10 有 61.6% 時間處於非清醒狀態 vs label0 的 28.6%）。
   訊號層沒壞——這與 memory「PERCLOS 是唯一強訊號、準確度差因門檻非訊號」一致。
2. **致命問題＝尺度塌陷**：**avg_fused_score 有 100% 的 Drowsy 片段到不了「中度」(0.4)**，
   平均只有 0.186、中位 0.227——即使最嗜睡的影片，系統也只判到「輕度疲勞」下緣。
   上面三段狀態（中度 0.4 / 高度 0.6 / 極度 0.8）在真實資料上**幾乎永遠觸發不了**。
3. **這印證了使用者實測**：2026-07-04「坐著閉眼超過 10 秒，行為特徵仍只顯示輕度疲勞」——
   不是個案，是系統分數天花板被結構性壓低的必然結果。

### 根因定位（推論，附數字）

behavior_sub 的上限被結構壓低：唯一強訊號 PERCLOS 佔行為權重 55%（`beh_w_perclos=0.55`），
但 PERCLOS 映射門檻是 `perclos_high_th=0.07`（`fatigue_scorer.py:43,93`），而 label10 實測
avg_perclos 只有 **0.031（中位 0.035、最大 0.062）**——代入映射 `(0.031-0.015)/(0.07-0.015)=0.29`，
PERCLOS 子分數只到 0.29，乘權重 0.55 ≈ 0.16。其餘 6 個行為子分數在 UTA 上多為弱/反訊號
（見 `fatigue_scorer.py:78-81` 上輪校準註解）。結果 behavior_sub 天花板 ≈ 0.16–0.30，
fused ×0.85 ≈ 0.14–0.25，**永遠上不了中度 0.4**。

也就是 `perclos_high_th=0.07` 這個「PERCLOS 到多少算滿分」的錨點，設得比真實 Drowsy 的
PERCLOS（~0.03–0.06）還高，把最強訊號的貢獻自己砍半。

## 階段 3 候選改法（重量級數值路徑，**需使用者裁決後才動**）

1. **把 `perclos_high_th` 下修到貼近實際 operating range**（如 0.07 → ~0.04–0.045），讓
   Drowsy 的 PERCLOS 能吃到接近滿分的子分數，撐起 behavior_sub。最小改動、最直接。
2. **重新配 behavior 子權重 / 映射曲線**：讓強訊號（PERCLOS、status_active_fraction）在其
   operating range 內能單獨把分數推過中度，弱訊號降權但保留。
3. **考慮把 status_active_fraction（AUC 0.75）納入融合**：它是不錯的獨立訊號，目前未直接進分數。
4. 每個改動都要：改 `FuserConfig` 常數 → 完整 pytest → 重建 golden baseline（會報漂移，屬預期）
   → 數值行為影響聲明 → 用本工具全量（60 subjects）複量確認 AUC 上升、塌陷下降。

## 限制

- **小樣本**：6 subjects/label，AUC CI 很寬；調門檻前後都應跑**全量 60 subjects**（180 影片）
  複量，別用這 18 支的絕對值下結論，只用它定方向。
- UTA label 是**整段影片類別、非逐幀 ground truth**，不能取代真人測試；分數用整段
  avg/p95 聚合，會平滑掉短暫的高疲勞瞬間（真實告警可能靠瞬時而非平均）。
- 本報告 JSON 原始檔在 scratchpad（`uta_baseline_6subj.json`），未入版控。
