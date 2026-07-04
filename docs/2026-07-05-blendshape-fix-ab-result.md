# blendshape 命名 bug 修復——A/B 量化否決紀錄(2026-07-05)

## 背景:bug 屬實

`gui/fatigue_engine.py` 的 `_blendshape_map()` 只做 `.lower()`,但 MediaPipe FaceLandmarker
回傳 camelCase category_name(`eyeBlinkLeft`,已用 `models/face_landmarker.task` 二進位字串
驗證:`eyeBlinkLeft` 1 筆、`eye_blink_left` 0 筆),`_bs()` 查 snake_case → 永遠查不到 →
實機 `blend_eye_blink` / `blend_eye_squint` / `blend_brow_down` / mouth blend 四組訊號
**自系統上線以來恆為 0.0**,所有 blend 輔助 gate 與 additive 貢獻沉睡。既有測試全部直接設
`eye.blend_*` 屬性、從不經過真實鍵名路徑,故從未被抓到。

## 修法(已實作、測試通過、但被 A/B 否決未落地)

- `_normalize_blend_key()`:小寫 + 去除非 [a-z0-9],camelCase 與 snake_case 收斂到同鍵。
- `_blendshape_map()` 兩分支與 `_bs()` 查表都走正規化。
- 保護剛上線的下視偵測器:新參數 `downgaze_blend_blink_gate=1.0`(fail-open),
  `downgaze_cond` 改用之,避免 blend 變活後在下視半閉眼時誤擋 latch。
- 新測試 14 個(含端到端 camelCase→blend_eye_blink 取值)。完整 pytest 452 passed。
- 實作完整保留在 git worktree 分支 `worktree-agent-a3ee209aad226cb1b`(若已清理,
  按上述三點重做即可,~30 行)。

## A/B 量化(否決依據)

方法:`scripts/utarldd_accuracy.py`,UTA_test 前 6 subjects × 3 labels × 1200 幀,
修復前後同配置各跑一次(修復前=HEAD `73dfe3e` 含下視偵測器,實測與 session 2 基準
逐位一致,亦即下視偵測器對 UTA 零影響)。

| 指標 | 修復前 | 修復後 | 判定 |
|---|---|---|---|
| avg_fused AUC(Drowsy>Alert) | 0.750 | 0.722 | 惡化 |
| avg_fused Spearman | +0.380 | +0.328 | 惡化 |
| p95_fused AUC | 0.667 | 0.639 | 惡化 |
| avg_fatigue Spearman | +0.341 | +0.354 | 持平微升 |
| avg_perclos AUC | 0.792 | 0.792 | 不變(幾何訊號) |
| **label-0 清醒影片 status_active_fraction** | **0.286** | **0.839** | **誤報爆炸** |
| label-10 avg_fused mean | 0.186 | 0.200 | 微升(不足以補償) |

golden check 同時檢出大幅漂移(subject04/label5:low_vigilance_frames 20→415、
avg_fatigue 0.0005→0.092;squint_frames 164→62)。單看 label-5 是「偵測增強」,
但 label-0 清醒影片被同幅推高,整體分離度下降。

## 根因分析:這個 bug 是承重牆

下游所有 blend 相關門檻與權重(`blend_squint_gate`、`blend_brow_gate`、squint/frown/
early_warning 的 blend 條款、mouth blend 哈欠輔助)都是在「blend 恆 0」的狀態下
校準/調參的(2026-07-04 的門檻校準輪)。裸修鍵名 = 把一批**從未見過真實分佈**的訊號
直接灌進分數,清醒時的自然 blend 活動(正常眨眼 eyeBlink、表情 browDown)全被當成
疲勞徵兆。

## 若未來要重啟(正確做法)

1. **逐通道啟用 + 門檻重校**,不要一次全開:先錄真實清醒/疲勞的 blend 分佈
   (可用 UTA replay 傾印 `_blendshape_map` 後的原始值),再逐一設定 gate。
2. 每啟用一個通道跑一次 `utarldd_accuracy` A/B,單通道證明有增益才保留。
3. `_blend_baseline` 個人化校準(校準期採樣)修復後會自然學到非零 baseline,
   有部分自適應能力,但 gate 常數仍需人工重錨。
4. 下視偵測器的 `blend_eye_blink` guard(fail-open)與 eyeLookDown 正向訊號的評估
   一併在此時做(見 docs/2026-07-05-downgaze-detector.md 誠實限制 3)。

## 結論

- bug 屬實,但**修復被 2026-07-05 A/B 量化否決**(使用者裁決條件:變好才落地)。
- 主樹已 revert 回 `73dfe3e`,零殘留(438 passed)。
- 現狀 = blend 通道維持沉睡,系統實效行為以幾何訊號(EAR/PERCLOS/gaze/head pose)為準
  ——這也是所有既有校準與基準的真實前提,文件與程式註解描述 blend 通道時應意識到
  它們實機無效。
