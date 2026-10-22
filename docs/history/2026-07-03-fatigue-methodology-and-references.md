# 疲勞監測系統：方法學、演算法理論、數值校準與驗證報告

> 撰於 2026-07-03。涵蓋近日對「非接觸式疲勞監測系統」的改動、所用技術與理論、
> 參考文獻與其貢獻、數值調整方法、可進一步提升的方向與理由，以及如何驗證。
> 本報告區分「文獻明載」與「本專案工程決定」；不確定處明確標註。

---

## 0. 摘要

本系統以一般攝影機做非接觸式疲勞監測，結合兩條管線：
(1) **MediaPipe 臉部行為分析**（眨眼、PERCLOS、頭部姿態、凝視、哈欠）為主要判斷依據；
(2) **rPPG 生理訊號**（心率／HRV）為輔（權重 15%）。

近日工作分四階段：**回歸基準工具 → 六軸系統審查與修復 → 臉部特徵模組深度審查與修復 →
資料驅動的準確度重校準**。核心成果：把最終疲勞輸出對 UTA-RLDD 標籤的
Drowsy-vs-Alert 判別力（AUC）從 0.53（約等於亂猜、且方向反向）提升到 0.75（校準集）／
0.69（留出集），並建立可重複的量測與迴歸防護工具。

---

## 1. 系統所用技術、演算法與理論

### 1.1 臉部關鍵點偵測：MediaPipe Face Landmarker

- **技術**：Google MediaPipe Face Mesh / Face Landmarker，單張影像回傳 **478 個 3D 臉部關鍵點**
  （468 個臉部網格點 + 10 個虹膜點），並可輸出 blendshape 係數與臉部變換矩陣。
- **理論**：以輕量 CNN 從單目影像回歸臉部表面幾何（regression of face surface geometry）。
- **文獻**：Lugaresi et al. (2019) *MediaPipe: A Framework for Building Perception Pipelines*；
  Kartynnik et al. (2019) *Real-time Facial Surface Geometry from Monocular Video on Mobile GPUs*
  (CVPRW)。**參考了什麼**：478 點的 canonical 索引拓樸（哪些索引對應眼周／嘴部／虹膜／臉輪廓），
  本系統的所有幾何量測（EAR/MAR/凝視/頭姿）都建立在這組索引上。

### 1.2 眨眼與眼睛閉合：EAR（Eye Aspect Ratio）

- **演算法**：以單眼 6 個關鍵點計算眼睛長寬比
  `EAR = (‖p2−p6‖ + ‖p3−p5‖) / (2·‖p1−p4‖)`，雙眼取平均。睜眼時 EAR 較大、閉眼時趨近 0。
- **理論**：眼睛縱橫比是眼睑開合的尺度不變量度量（對臉部大小近似不變）。
- **文獻**：Soukupová, T. & Čech, J. (2016) *Real-Time Eye Blink Detection using Facial Landmarks*
  (Computer Vision Winter Workshop)。**參考了什麼**：EAR 的定義式與「以 EAR 低於門檻＋回升判定一次
  眨眼」的狀態機構想。本系統據此做眨眼計數、眨眼時長、眨眼時序特徵（blink temporal）。
- **本專案實作**：`gui/fatigue_engine.py` 的 `eye_aspect_ratio()` 與眨眼狀態機（雙門檻遲滯：
  進入用原始 EAR、離開用 EMA 平滑 EAR，並以 `blink_min_sec`/`blink_max_sec` 區分正常眨眼與長閉眼）。

### 1.3 疲勞核心指標：PERCLOS

- **演算法**：PERCLOS = 單位時間內眼睛閉合超過某比例的時間佔比。學界標準為 **P80**
  （眼睑遮蓋瞳孔 ≥80% 的時間比例），另有 P70 與 EYEMEAS 變體。
- **理論**：PERCLOS 是與精神運動警覺任務（PVT）表現高度相關、最受驗證的疲勞生理指標之一。
- **文獻**：Wierwille et al. (1994) 提出 PERCLOS 概念；Dinges, D. F. & Grace, R. (1998)
  *PERCLOS: A Valid Psychophysiological Measure of Alertness*（US DOT FHWA-MCRT-98-006）
  確立 P80 定義與其與警覺度的關聯。**參考了什麼**：「以閉眼時間佔比、而非單一瞬間」量測疲勞的核心
  概念，以及 P80 這個閉合幅度門檻。
- **本專案實作與誠實差異**：目前實作是**固定 EAR 門檻式 PERCLOS**（EAR 低於
  `base_ear_th = 個人清醒 EAR 中位數 × 0.75` 即計為閉眼），並非教科書的**幅度式 P80**
  （相對睜眼幅度的 80% 閉合）。近日已把分母改為「可量測時間」（排除低品質幀），
  但「幅度式 P80」尚未實作——這是後續提升方向（見 §5）。

### 1.4 頭部姿態：solvePnP（PnP 問題）

- **演算法**：以一組 3D 臉部模型點與其 2D 影像投影，解 Perspective-n-Point 求相機外參
  （旋轉 rvec、平移 tvec），再由旋轉矩陣分解出俯仰（pitch）／偏航（yaw）／翻滾（roll）歐拉角。
- **理論**：PnP 是由 2D–3D 對應求剛體位姿的經典幾何問題。
- **文獻**：Lepetit, Moreno-Noguer & Fua (2009) *EPnP: An Accurate O(n) Solution to the PnP Problem*
  (IJCV)；OpenCV `solvePnP` 實作（Bradski, 2000, *The OpenCV Library*）。**參考了什麼**：由
  landmark 求頭姿的方法。本系統用 pitch 判「點頭型微睡」與抑制低頭時失真的 EAR。
- **本專案**：`solve_head_pose()`；近日修復了「pitch 校準未完成即判微睡」「姿態過期仍撐住閘門」等問題。

### 1.5 嘴部與哈欠：MAR（Mouth Aspect Ratio）

- **演算法**：類比 EAR，以嘴部關鍵點計算嘴巴長寬比，持續張大超過門檻與時長判為哈欠。
- **理論／文獻**：MAR 為 EAR 的嘴部類比，常見於駕駛疲勞文獻（例如 Abtahi et al. 2014 提出
  YawDD 哈欠資料集與 MAR 類方法）。**參考了什麼**：以嘴部縱橫比偵測哈欠的做法。本系統將哈欠列為
  **後期、低權重**特徵（0.05）。

### 1.6 凝視與掃視：Gaze / Saccade

- **演算法**：以虹膜中心相對眼角的正規化位移估凝視方向；由相鄰幀凝視位移的速度判定掃視（saccade），
  並統計掃視頻率與凝視固定時長（空洞凝視）。
- **理論**：疲勞時掃視速度下降、凝視固著時間拉長（mental fatigue / 空洞凝視）。
- **本專案**：近日修復「眨眼期間眼高塌陷被誤記為假掃視」「開機掃視窗未暖機即假性拉滿凝視分」。

### 1.7 rPPG 生理訊號：POS / CHROM + 帶通 + Welch + HRV

- **ROI → 脈搏訊號**：從前額／臉頰／眉間 ROI 抽取 RGB 均值時間序列，投影成脈搏訊號。
  - **POS（Plane-Orthogonal-to-Skin）**：Wang, den Brinker, Stuijk & de Haan (2017)
    *Algorithmic Principles of Remote PPG* (IEEE TBME)。**參考了什麼**：把 RGB 投影到與膚色方向
    正交的平面以抽出脈搏、抑制運動假影的原理。
  - **CHROM（Chrominance）**：de Haan & Jeanne (2013) *Robust Pulse Rate from Chrominance-based
    rPPG* (IEEE TBME)。**誠實標註**：本專案函式名為 `pos_pulse`，但審查發現其實作為
    **CHROM 式色度投影 + z-score 正規化**，與嚴格 POS 有差異（見審查報告軸 1）。
- **帶通濾波**：Butterworth band-pass（實作預設 **0.65–3.7 Hz**，約 39–222 BPM 心率頻段；
  BPM 另以 42–210 的生理合理範圍鉗制），濾除非心率頻段。理論依據為 Butterworth (1930)
  最大平坦濾波器。
- **頻譜與心率**：Welch 功率譜密度估計取峰值頻率 → BPM，並做峰值拋物線插值提升解析度。
  **文獻**：Welch, P. D. (1967) *The use of FFT for the estimation of power spectra* (IEEE
  Trans. Audio Electroacoust.)。**參考了什麼**：分段平均週期圖以降低譜估計變異的方法。
- **HRV**：由脈搏間期（IBI）計算時域（SDNN、RMSSD）與頻域（LF/HF）指標。
  **文獻**：Task Force of ESC/NASPE (1996) *Heart Rate Variability: Standards of Measurement,
  Physiological Interpretation, and Clinical Use* (Circulation / European Heart Journal)。
  **參考了什麼**：SDNN/RMSSD/LF-HF 的標準定義與正常範圍。

### 1.8 決策融合與狀態機

- **融合**：`FatigueFuser` 以行為 85% + rPPG 15% 加權；任一支柱品質不足時權重轉移到另一支柱。
  行為支柱內部再對 PERCLOS／眨眼／微睡／凝視／瞇眼／哈欠加權求和。
- **狀態**：另有離散狀態機（清醒／低警覺／嗜睡／危急／微睡）由各特徵門檻直接驅動，供警報使用。
- **理論定位**：此為**加權特徵融合 + 規則式門檻**，非機器學習分類器——權重與門檻為人工設定，
  這正是近日校準工作的對象（見 §3、§4）。

### 1.9 離線驗證資料集：UTA-RLDD

- **資料**：University of Texas at Arlington Real-Life Drowsiness Dataset，60 位受試者、
  三種狀態（**0=Alert、5=Low Vigilant、10=Drowsy**，源自 KSS 嗜睡量表區間）的實拍影片。
- **文獻**：Ghoddoosian, Galib & Athitsos (2019) *A Realistic Dataset and Baseline Temporal Model
  for Early Drowsiness Detection* (CVPR Workshops)。**參考了什麼**：整段影片一個標籤的三分類真值，
  作為本系統門檻校正與準確度量測的**序位真值**。
- **限制**：label 是整段影片類別、非逐幀 ground truth，且為坐姿汽車情境的演出，不能取代真人測試。

---

## 2. 近日改動總覽

| 階段 | 內容 | 產物 |
|---|---|---|
| A. 回歸基準 | 建 golden-output 工具，機械偵測「演算法改動有沒有動到數值」 | `scripts/utarldd_golden.py`、`tests/golden/` |
| B. 六軸系統審查 | rPPG 數值／疲勞融合／併發／安全／測試／文件平台六軸並行審查＋對抗驗證 | `docs/history/2026-07-03-project-audit.md` |
| B. 修復 | P0 漏報路徑（無臉清空校準、微睡單幀）、P1（BPM 死碼、無資料誤顯清醒、遲滯、LAN 認證、相機釋放）等 | 多檔 |
| C. 臉部模組深審 | 幾何正確性（landmark 索引驗證無鏡像錯）＋時序邏輯兩軸深度審查 | 審查報告 |
| C. 修復 | PERCLOS 可量測時間分母、低頭對稱 gate、眨眼凍結凝視、校準合理性、微睡姿態閘門 | `gui/fatigue_engine.py` 等 |
| D. 準確度重校準 | 建準確度量測工具、診斷、資料驅動重配門檻與權重 | `scripts/utarldd_accuracy.py`、`docs/history/2026-07-03-fatigue-accuracy-calibration.md` |

（每階段皆經三重審查、完整 pytest、golden 迴歸與 commit；詳見對應 commit 訊息與審查文件。）

---

## 3. 數值調整怎麼做的（方法學）

核心原則：**先量測、再改、每步用資料驗證，不盲調**。

1. **建立量測工具**（`scripts/utarldd_accuracy.py`）：把 UTA-RLDD 的 0/5/10 當序位真值，對每個
   輸出欄位計算：
   - **各標籤分數分佈**（mean/median/min/max）
   - **單調性**（分數是否隨標籤上升）
   - **Spearman 序位相關**（標籤 vs 分數）
   - **成對 AUC**（Drowsy 分數 > Alert 分數的機率）
   - **bootstrap 95% 信賴區間**（小樣本不確定度）
   - **尺度塌陷率**（多少比例的 Drowsy 影片連第一道等級門檻都到不了）
2. **量基準**：在 subject 01–06 上跑，發現最終輸出 AUC 僅 0.53、且倒著走。
3. **逐通道拆解**：對每個特徵通道單獨算 AUC，找出「哪個訊號有效、哪個是雜訊／反訊號」。
4. **依資料重配**：把門檻對齊系統實際 operating range、權重集中到有效通道。
5. **復量驗證**：改完重跑，確認最終輸出 AUC 上升且單調。
6. **留出驗證**：在未參與校準的 subject 07–12 上復量，確認非過擬合。
7. **迴歸防護**：golden baseline 重建，日後任何改動用 golden + accuracy 兩工具復查。

---

## 4. 為什麼「調了會更精準」——機制解釋

診斷資料（各通道對 Drowsy-vs-Alert 的 AUC）：

| 通道 | AUC | 判讀 |
|---|---|---|
| **avg_perclos** | **0.79** | 唯一強訊號 |
| max_perclos | 0.76 | 同源有效 |
| microsleep_frac | 0.42 | 反訊號（清醒比嗜睡更常觸發） |
| avg_blink_temporal | 0.42 | 反訊號 |

**病根有二：**
1. **有效訊號被門檻壓死**：PERCLOS 本身能分辨（AUC 0.79），但計分門檻設在 0.10/0.25，
   而系統實際 PERCLOS 只有 0.005–0.067——**永遠到不了計分起點，所以唯一有效訊號恆輸出 0**。
2. **權重壓在反訊號上**：微睡與 blink_temporal（在此坐姿資料上是反訊號）佔了 0.20–0.30 與 0.25
   權重，把好訊號淹沒成雜訊。

**為什麼調整有效（理論上）**：分類的關鍵是**訊號的相對排序**（drowsy > alert）而非絕對值。
PERCLOS 已具備正確排序（這與 PERCLOS 作為驗證過的疲勞指標的文獻一致），問題純粹在
「映射函式把它落在飽和區的 0 端」。把計分門檻平移對齊實際分佈、並把權重集中到有正排序的通道，
等於讓一個線性判別的**權重向量對齊了資料的類別方向**——這是提升可分性的直接手段。
微睡在此資料上反向，故降權；但它對真實無人機駕駛員的點頭仍有價值，故降權而非移除。

**成效（最終輸出 avg_fused_score）**：

| | label 0 | label 10 | 單調 | AUC [95% CI] |
|---|---|---|---|---|
| 改前 | 0.020 | 0.009 | ❌ 反向 | 0.53 [0.19–0.89] |
| 改後 | 0.036 | 0.186 | ✅ | **0.75 [0.39–1.00]** |
| 留出 07–12 | 0.177 | 0.255 | ✅ | 0.69 [0.36–0.97] |

---

## 5. 調什麼可以更精準（後續方向，按槓桿排序）

1. **每人清醒基線 PERCLOS 校準（最高槓桿）**。留出集顯示不同人的清醒 PERCLOS 基線差異大
   （07–12 清醒者分數逼近門檻），固定絕對門檻無法跨個體轉移。做法：開機錄一段清醒基線 PERCLOS，
   把分數改成**相對自身基線的偏移量**（z-score 或比值），可同時提升跨個體一致性與真實場景轉移性。
   *為何更準*：消除個體基線差異這個混淆變數，讓門檻只反映「相對此人清醒的偏離」。
2. **PERCLOS 改幅度式 P80**（§1.3）。把「EAR < 固定門檻」改成「閉合幅度 =
   1 −(EAR − 完全閉眼 EAR)/(睜眼基準 EAR − 完全閉眼 EAR)，取 ≥80% 的時間比例」。
   *為何更準*：能捕捉疲勞最典型的**眼皮半垂**（EAR 落在 0.19–0.22 這種未閉緊區間），
   現行二元門檻會漏掉。符合 Dinges & Grace 的 P80 定義。
3. **時間累積特徵**。疲勞是慢性累積過程；現行為逐幀近似獨立計分。加入長眨眼比率、掃視速度下降、
   點頭頻率的數分鐘滑動累積。*為何更準*：利用疲勞的**時間結構**，區分「偶發一次閉眼」與「持續惡化」。
4. **擴大校準受試者**。目前每組 6 片，AUC 的 95% CI 很寬、未達統計顯著。擴大到 UTA-RLDD 全 60 人
   或真人場景資料。*為何更準*：降低門檻估計的變異，讓校準不因少數受試者而偏。
5. **以資料擬合門檻／權重**（取代人工設定）。有了量測工具與更大資料集，可用邏輯迴歸擬合權重向量與
   等級門檻，取代目前三套重疊的人工權重。*為何更準*：直接最大化類別可分性，而非靠手調。

---

## 6. 要怎麼證明（驗證方法論）

準確度宣稱必須用**可重複、對真值、附不確定度**的量測支撐，不能靠「看起來變好」。

1. **序位一致性**：Spearman 相關與**單調性**（分數是否隨 0→5→10 上升）。本系統改後由
   非單調變單調。
2. **判別力（AUC）**：Drowsy-vs-Alert 成對 AUC = P(Drowsy 分數 > Alert 分數)，
   等價於 Mann-Whitney U 統計量正規化。**文獻**：Hanley & McNeil (1982) *The meaning and use of
   the area under a ROC curve* (Radiology) 建立 AUC 與 Mann-Whitney 的等價與其意義。
   本系統最終輸出 AUC 0.53→0.75。
3. **不確定度（信賴區間）**：對小樣本，AUC 點估計不可靠。以 **bootstrap 重抽樣**（Efron, 1979,
   *Bootstrap Methods: Another Look at the Jackknife*, Annals of Statistics）估 95% CI。
   **誠實條款**：本系統每組 n=6，CI 寬（下界 0.39），單次量測**未達 α=0.05 顯著**；
   結論靠「點估計大幅上升 + 單調性翻正 + 留出集重現」三者方向一致支撐，不宣稱統計顯著。
4. **留出驗證（防過擬合）**：門檻用 01–06 校準，在**未參與校準**的 07–12 上復量。方向重現
   （AUC 0.69）代表非過擬合。
5. **回歸防護**：golden baseline（`scripts/utarldd_golden.py`）確保後續改動不會靜默改變數值；
   任何預期的數值變更需在 commit 逐欄聲明後重建 baseline。
6. **不能只靠 UTA-RLDD**：最終仍需**真人、你的無人機場景**錄製清醒／疲勞影片，用同一套
   `utarldd_accuracy` 指標驗證，並據以微調門檻。這是文獻方法無法替代的一步。

**如何在論文中呈現**：報告 (a) 各標籤分數分佈盒鬚圖、(b) ROC 曲線與 AUC±CI、(c) 單調性與
Spearman、(d) 校準集 vs 留出集對照表、(e) 明確的樣本量與統計顯著性限制。避免宣稱「三分類準確率
接近 100%」這類未經留出與顯著性檢定的說法。

---

## 7. 限制與誠實聲明

- **加權規則式、非學習式**：權重與門檻為人工＋資料輔助設定，非端到端學習，泛化受限。
- **樣本量小**：每組 6 片，統計未顯著；結論為方向性證據。
- **UTA-RLDD ≠ 目標場景**：坐姿汽車演出資料，跨到無人機駕駛需重新驗證。
- **PERCLOS 為固定門檻式、非幅度式 P80**：半垂眼可能漏抓（已列後續）。
- **rPPG `pos_pulse` 實為 CHROM 式投影**：命名與文獻術語不完全一致（已於審查標註）。
- **微睡在此資料反向**：靠頭部下垂偵測，坐姿看下方≠疲勞；對真實駕駛場景保留低權重。

---

## 參考文獻

1. Lugaresi, C. et al. (2019). *MediaPipe: A Framework for Building Perception Pipelines.* arXiv:1906.08172.
2. Kartynnik, Y. et al. (2019). *Real-time Facial Surface Geometry from Monocular Video on Mobile GPUs.* CVPR Workshops.
3. Soukupová, T. & Čech, J. (2016). *Real-Time Eye Blink Detection using Facial Landmarks.* Computer Vision Winter Workshop.
4. Wierwille, W. W. et al. (1994). *Research on Vehicle-Based Driver Status/Performance Monitoring.* NHTSA.
5. Dinges, D. F. & Grace, R. (1998). *PERCLOS: A Valid Psychophysiological Measure of Alertness as Assessed by Psychomotor Vigilance.* US DOT, FHWA-MCRT-98-006.
6. Lepetit, V., Moreno-Noguer, F. & Fua, P. (2009). *EPnP: An Accurate O(n) Solution to the PnP Problem.* International Journal of Computer Vision.
7. Bradski, G. (2000). *The OpenCV Library.* Dr. Dobb's Journal of Software Tools.
8. Abtahi, S. et al. (2014). *YawDD: A Yawning Detection Dataset.* ACM Multimedia Systems.
9. Wang, W., den Brinker, A. C., Stuijk, S. & de Haan, G. (2017). *Algorithmic Principles of Remote PPG.* IEEE Transactions on Biomedical Engineering.
10. de Haan, G. & Jeanne, V. (2013). *Robust Pulse Rate from Chrominance-Based rPPG.* IEEE Transactions on Biomedical Engineering.
11. Welch, P. D. (1967). *The Use of Fast Fourier Transform for the Estimation of Power Spectra.* IEEE Transactions on Audio and Electroacoustics.
12. Task Force of the European Society of Cardiology and NASPE (1996). *Heart Rate Variability: Standards of Measurement, Physiological Interpretation, and Clinical Use.* Circulation / European Heart Journal.
13. Ghoddoosian, R., Galib, M. & Athitsos, V. (2019). *A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection.* CVPR Workshops.
14. Hanley, J. A. & McNeil, B. J. (1982). *The Meaning and Use of the Area under a Receiver Operating Characteristic (ROC) Curve.* Radiology.
15. Efron, B. (1979). *Bootstrap Methods: Another Look at the Jackknife.* The Annals of Statistics.

> 文獻用途對照見各節「參考了什麼」。實作與文獻的差異（PERCLOS 門檻式 vs P80、pos_pulse vs POS/CHROM）
> 已於正文誠實標註。相關工程細節見 `docs/history/2026-07-03-project-audit.md` 與
> `docs/history/2026-07-03-fatigue-accuracy-calibration.md`。
