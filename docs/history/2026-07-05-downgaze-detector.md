# 下視偵測器(down-gaze detector)— 修復「往下看被誤判疲勞」(2026-07-05)

## 背景(實機發現)

持續閉眼強通道(docs/history/2026-07-04-eye-closure-channel.md)實機驗證通過(閉眼 10 秒正確進高度)後,
使用者回報新誤判:**往螢幕稍下方看(頭微低,或頭不動純視線往下、眼皮被帶動下垂)時,
幾秒內被推到中度以上疲勞**。兩種情境都會觸發,升級速度吻合 closure 強通道(3 秒進中度)。

## 根因

1. **pitch gate 是 ±10° 硬開關**(`pitch_eye_gate_deg=10.0`):頭微低通常 <10°,gate 不啟動。
2. **gate 只讀 solvePnP 頭姿,不讀視線**:純視線往下(pitch≈0)永遠不觸發。
3. `gaze_y`(虹膜垂直位置)已在 `GazeTrackingModule.step` 算出,但全程式無方向性使用——訊號存在未接線。
4. 下垂眼皮的低 EAR 同時推高至少 5 條路徑:closure 強通道(最快)、PERCLOS、squint、
   early_warning(門檻 1.25×base 更寬)、gaze_mental_fatigue(盯螢幕低掃視)。
5. 個人清醒基線不覆蓋 EAR 門檻,校準救不了。

## 修法(方案 1,使用者裁決;不採軟化 pitch gate、不採 EAR 連續補償)

`gui/fatigue_engine.py` 單檔改動(+~80 行),`fatigue_scorer.py`/`rppg/`/worker/`personal_profile` 零改動:

- **條件**(全 AND,用前一幀屬性,與 pitch gate/fatigue_q 同批):`eye.calibrated`(校準期一律不成立)
  + `has_iris`(僅防陣列截斷/首幀,**非**閉眼防護)+ `gaze_y > downgaze_gy_th(0.12)`
  + `EAR ∈ (downgaze_ear_floor=0.45×, downgaze_ear_hi=1.10×)·base_ear_th` + `blend_eye_blink < blend_blink_gate`。
- **雙向去抖**(本檔首見,squint/pitch gate 皆單向):連續成立 `downgaze_enter_sec(0.3s)` 才 latch on、
  連續失效 `downgaze_exit_sec(0.3s)` 才 latch off,防偵測帶邊緣抖動使累積時斷時續。
- **抑制語意 = pitch gate 完全相同**:elif 鏈尾第三分支(pitch gate 優先短路)設 `blink_ok=False;
  fatigue_ok=False`,下游自然清零 fat_dur、排除 PERCLOS eligible 分母、停 squint/blink 計數。
- **early_warning** 的 `lid_balance>gate 且 ear_smooth<1.25×base` 條款尾加 `and not down_gaze_active`。
- **on_no_face**:一掉臉即清兩個去抖計時器(空窗時間不得計入防抖);`_downgaze_active` 沿用
  寬限期語意,超過 `no_face_reset_sec` 由全重置清 False。
- 新增 `FatigueMetrics.down_gaze_active`(觀測旗標,下游顯式欄位存取、不接線不會壞)。

### 防漏報設計(鐵律:真閉眼不得漏報)

- 真閉眼 EAR 跌破 `0.45×base` → 條件失效 → 經 exit 去抖解除 → closure/PERCLOS 照常累積。
- 深帶(0.45×~1.0×base,實機誤判真正發生帶)機制:EAR<1.0×base 時 blink/fatigue 狀態機判閉眼、
  gaze 凍結在「往下看」舊值 → 靠凍結值完成 enter 去抖 latch → latch 後閉眼旗標被清、gaze 解凍
  改用即時值維持。此完整迴圈有正反例配對測試鎖住。

## 鐵律:未觸發逐位元回退

偵測器不成立的每一幀,所有輸出與改動前完全一致:elif 新分支不進入、early_warning 的
`and not False` 恆真、on_no_face 清 `None→None` 為 no-op、新 metrics 欄位預設 False 且 scorer 不消費。

## 驗證(全部實跑)

- 完整 `pytest -q`:**438 passed**(既有 424 + 新 14)。
- `tests/test_downgaze_gate.py` 14 案例:latch/深帶正反例配對/真閉眼 floor guard/眨眼/pitch gate
  共存/校準期/無虹膜/掉臉去抖三態。掉臉回歸測試經**負向對照**驗證鑑別力(暫時停用修法→2 failed,
  還原→全綠)。
- **golden check:PASS 零漂移**(subset subject 04×3 labels×600 幀)——golden 子集無觸發場景,
  不需重建 baseline。與 closure 通道同理:UTA 測不到此即時場景,最終效果以實機驗證為準。
- 三重審查(3 個獨立 fresh-context agent):軸 A 相容性/軸 B 正確性邊界/軸 C 慣例文件,
  **一致可合入、零 blocker**。前輪審查的 2 個 Critical(掉臉×去抖交互、深帶測試缺口)已修復並驗證。

## 數值行為影響聲明

- **會變**:實機「視線往下/頭微低(<10°)且眼皮下垂至 EAR 帶內」持續 ≥0.3s 的片段——
  closure/PERCLOS/squint/blink/early_warning(lid_balance 條款)暫停,疲勞分數不再被此情境推高。
- **不變**:真閉眼(EAR<0.45×base)、眨眼、正視、pitch>10°(既有 gate 管轄)、校準期、
  golden 比對子集(實測零漂移)、rPPG 與融合權重全部。
- **已接受的取捨**(審查軸 B):下視轉真閉眼時,exit 去抖使 closure 起算延後 ~0.3-0.4s
  (主場景 10s 進高度 → 影響 ~3%,可接受;若實機覺得慢,候選修法是 EAR 跌破 floor 時跳過
  exit 去抖直接解除)。

## 誠實限制(需實機驗證)

1. **gaze_y 在窄帶的雜訊**(審查軸 A major):gaze_y 以眼高為分母,眼皮半閉時分母縮小、雜訊放大,
   而偵測帶正是這個區間。合成測試無法證明實機穩定性;若實機出現 latch 振盪,調 `downgaze_gy_th`
   或去抖秒數。
2. **latch 無時長上限**(審查軸 B):「漸進式嗜睡眼皮下垂但未達深閉眼」的灰帶可能被長期抑制。
   互補防線:gaze_mental_fatigue 不受抑制、PERCLOS eligible 排除(不稀釋)、下垂加深即跌破 floor
   恢復。若實機發現壓制真疲勞,候選修法是「持續 X 秒後改降權而非全暫停」。
3. **blend_eye_blink guard 目前是死的**:blendshape camelCase/snake_case 命名 bug(另案,使用者
   已授權修復)使該值實機恆 0 → guard 恆真(fail-open,不增漏報但少一道防誤觸)。修復命名 bug 時
   須回頭驗證此 guard 在下視時是否誤擋 latch(eyeBlink 半閉眼時可能 >0.2),屆時可評估改用
   eyeLookDown 系列當正向訊號。
4. 五個常數(`downgaze_*`)皆為建議值,需實機掃描調校(尤其 `downgaze_ear_floor` 0.40~0.60 權衡
   「殘餘誤判 vs 真閉眼恢復延遲」)。
5. 命名風格 nit(審查軸 C):params 用 `downgaze_*`、metrics 用 `down_gaze_active`,grep 時兩種
   都要搜;不影響行為,未改以避免 churn。

## 實機驗證清單(下個 session 貼結果)

1. 頭端正、視線往螢幕下緣/鍵盤看 10~20 秒 → 不應升到中度(原誤判場景)。
2. 頭微低(<10°)往下看 → 同上不誤判。
3. 頭端正持續閉眼 ~10 秒 → 仍應 3 秒左右進中度、10 秒進高度(回歸驗證,不得漏報)。
4. 下視幾秒後直接閉眼 → closure 仍應在 ~1.3s 內開始累積(exit 去抖延遲可感知度)。
5. 正常工作(打字、看螢幕中央、眨眼)→ 無異常跳動。
