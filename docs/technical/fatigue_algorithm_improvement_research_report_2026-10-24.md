# 疲勞演算法精進研究與交叉審核報告

**研究日期：2026-10-24**

**範圍：** MediaPipe 臉部行為特徵、rPPG 心率／HRV、分數融合、資料與驗證方法。

**用途：** 提供下一輪演算法工作的證據分級、優先順序與實證驗收方法；本報告不代表已完成程式改動或已證明準確率上升。

## 1. 結論摘要

目前最可能提升「可被資料證明的疲勞判讀品質」的工作順序如下：

1. **先把標註與評估做對。** 以受試者為單位隔離訓練、校準、測試資料；取得逐時間窗的疲勞標註與任務表現參考，並回報誤報／小時、漏報、預警時間、可信覆蓋率及受試者群集信賴區間。這不會自動改變演算法，但會避免把影片級標籤、重複影格或同一受試者資料誤當成獨立驗證證據。
2. **保留行為特徵作主軸，優先驗證個人清醒基線及 PERCLOS／閉眼時序。** PERCLOS 是現有指標中有較成熟研究支持的一種，但其定義、量測門檻、情境及任務表現關係會影響效果；不能把 UTA-RLDD 的固定門檻直接視為無人機場域真值。[PERCLOS 證據回顧](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/)、[疲勞駕駛表現統合分析](https://pubmed.ncbi.nlm.nih.gov/42809921/)
3. **先修正 rPPG 方法身分與生理指標用途，再比較融合。** 現有 `pos_pulse()` 的投影公式與標準 CHROM 公式一致，並非標準 POS；此為程式碼可直接核對的事實。POS 與 CHROM 沒有跨情境的固定勝者，應使用本專案同步真值資料做配對比較。[CHROM／POS 公式比較](https://iris.unimore.it/retrieve/d399cd61-0047-4038-b1b8-b92215a9ae99/2020_rPPG.pdf)、[POS 原始研究](https://doi.org/10.1109/TBME.2016.2609282)
4. **不要讓單獨 rPPG 心率直接代表疲勞。** 心率與 HRV 同時會受任務負荷、壓力、姿勢、活動、個體差異及量測品質影響；系統目前在行為 pillar 不可用、但 rPPG 可用時，會讓 rPPG 承擔整個融合分數。這種 fallback 在沒有本專案疲勞標註證據前不適合解讀為疲勞程度。[HRV 駕駛疲勞系統性回顧](https://pubmed.ncbi.nlm.nih.gov/36155280/)、[HRV 駕駛研究系統性回顧](https://pubmed.ncbi.nlm.nih.gov/34565082/)
5. **現有 30 秒 HRV 視窗不適合將 LF/HF 當穩定疲勞特徵。** 傳統標準化短時 HRV 通常採 5 分鐘；LF 頻帶 0.04 Hz 的週期約 25 秒，至少觀察 10 個週期約需 250 秒。30 秒視窗不能穩健估計此頻帶。即使加長視窗，rPPG 的脈搏間期變異仍須先和 ECG／接觸式 PPG 比對。[ESC/NASPE HRV 標準](https://pubmed.ncbi.nlm.nih.gov/8598068/)、[HRV 頻帶與短時紀錄建議](https://doi.org/10.1016/S0735-1097%2899%2900354-X)

**實作後準確度提升信心：** 個人基線、品質分層及以受試者獨立資料重新校準為「中至高」；POS/CHROM 互相比較、ROI 加權或時間模型為「中」或「低至中」，視資料涵蓋而定；只增加 rPPG 權重、直接以 BPM／LF/HF 診斷疲勞為「低」。現有資料不足以負責任地預測提升幾個百分點。完整判定表見第 8 節。

## 2. 搜尋範圍與證據處理

本次查閱可公開存取的 PubMed／PMC、IEEE Xplore、Nature、Springer、ScienceDirect、NeurIPS 論文頁、arXiv、官方資料集頁及 GitHub 專案／實作；涵蓋系統性回顧、原始研究、資料集文件、基準工具箱與演算法程式碼。搜尋重點是：疲勞真值與行為指標、HRV 作為疲勞訊號的有效性、rPPG 在光線／動態／心率改變下的可靠度、融合和跨受試者驗證，以及本專案現有實作與上述證據是否相符。

這是有明確範圍的工程研究整理，**不是 PRISMA 系統性回顧，也不能證明已窮盡全球所有論文網站、期刊付費全文或學術論壇**。論壇與開源討論可協助發現問題，但未經控制實驗、獨立資料集及可重現指標佐證的貼文不作為準確度證據。下文將「已在本專案程式碼確認」、「多來源研究支持」及「需本專案實測」分開陳述。

證據等級：

- **較強：** 系統性回顧／統合分析、標準文件、原始方法論論文或公開基準研究，且結論與本系統量測目標一致。
- **中等：** 同領域實驗結果，但資料集、感測器、族群或任務與無人機操作情境仍有落差。
- **待驗證：** 開源實作、單一資料集結果、工程推論，或尚未以本專案真值資料測試的方案。

## 3. 本專案現況與本地證據

### 3.1 已有的基礎

目前系統不是只看單張臉部影像。`gui/fatigue_engine.py` 已使用 EAR、個人 EAR 校準、閉眼／眨眼時間、60 秒 PERCLOS、眨眼時序、頭姿、瞇眼、凝視、哈欠與品質 gate；`gui/personal_profile.py` 已提供個人清醒基線；`gui/fatigue_scorer.py` 以行為特徵為主、rPPG 為輔；rPPG 由額頭、雙頰和眉間多 ROI 輸出心率、HRV 及品質診斷。這些方向與文獻常用的多時間尺度行為監測及品質控管一致。

系統已具備回放、逐幀紀錄、UTA-RLDD 準確度統計、golden regression 與心跳帶同步參考的部分工具。這是後續實證的優勢，不必先推倒現有管線或另訓練大型模型。

### 3.2 已有的本地準確度結果不能過度解讀

專案歷史校準紀錄以 UTA-RLDD subject 01–06 的六位受試者調整 PERCLOS 映射和權重：融合分數 Drowsy 對 Alert AUC 點估計由 0.53 升至 0.75，95% bootstrap CI 為 0.39–1.00；subject 07–12 留出組 AUC 為 0.69，95% CI 為 0.36–0.97。這顯示分數趨勢改善且在小型留出組方向一致，但區間很寬，不能視為統計顯著或無人機場域的分類準確率。每一標籤只有 6 支影片的分析也限制了結論強度。細節見 [`2026-07-03-fatigue-accuracy-calibration.md`](../history/2026-07-03-fatigue-accuracy-calibration.md)。

UTA-RLDD 官方資料說明每支影片以受試者錄影時的主要自評狀態分類為 Alert、Low Vigilant 或 Drowsy；影片級標籤不是精確到每個短時間窗的真值。[UTA-RLDD 官方資料頁](https://sites.google.com/view/utarldd/home)及原始論文均支持這個限制。原始研究使用受試者折分，並以 blink 特徵序列建模；其 HM-LSTM 在該研究的影片準確率為 65.2%，高於一般 LSTM 與全連接基線，但該結果屬原始資料集及其標註協定，不能直接套用到本系統。[原始 UTA-RLDD 時序研究](https://arxiv.org/abs/1904.07312)、[原作者程式庫](https://github.com/rezaghoddoosian/Early-Drowsiness-Detection)

### 3.3 程式碼直接核對到的 rPPG 差異

`rppg/rppg_worker.py` 的 `pos_pulse()` 先逐 RGB 通道做標準分數，再以 `X = 3R − 2G`、`Y = 1.5R + G − 1.5B`、`pulse = X − αY` 產生輸出。這三個式子是標準 CHROM 色度投影常見寫法；POS 的投影基底則以 `G − B` 及 `G + B − 2R` 為主，並有其分窗、重疊合成流程。函式名稱、文件中「POS」的描述與實際公式不一致。

這個發現不等於現行訊號一定較差；CHROM 本身是成熟方法。它代表目前報告裡的「POS BPM 表現」無法直接成立，除非確認實際使用了標準 POS。最小修正方向是先把目前輸出標示為 CHROM-like，另以正確 POS 作候選版本，在同一段同步影片／真值上做配對測試，再決定是否更換演算法或只修正名稱與文件。

此外，ROI 程式會計算姿態／遮擋權重與每 ROI 診斷值，但一般取樣路徑的有效 ROI RGB 最後仍採等權平均。只有有效套用 `rppg_params` 權重覆寫的路徑才使用加權混合；該線上自適應機制預設關閉。這不是錯誤，而是表示畫面上有 ROI 權重診斷，不代表它們已在一般路徑中按比例參與訊號融合。

### 3.4 融合器目前的風險點

- rPPG pillar 將 `stress_prob`、BPM 偏離一般範圍、LF/HF 映射組合成分數；目前 BPM 一般範圍是固定 60–100，而不是駕駛員基線或疲勞標定範圍。
- rPPG 是否可用主要看臉部存在、暖機、SQI、quality score 及 ROI 數；rPPG fatigue score 未以 `hrv_confidence` 作必要 gate。
- rPPG 與行為都可用時權重為 15%／85%；若行為不可用而 rPPG 可用，程式會將 rPPG 權重改為 100%。生理訊號可能因壓力、運動、咖啡因、說話、姿勢或疾病而改變，因此此時單一 rPPG 不宜輸出高信心疲勞結論。
- 專案 rPPG HRV 預設使用 30 秒視窗；該長度不符合 LF/HF 的標準化短時分析需求。HRV 即使計算成功，也不代表在 30 秒人臉影片中已可靠估計 LF/HF。

## 4. 文獻交叉比對：哪些訊號較站得住腳

### 4.1 行為特徵：優先強化時間變化及個人差異

PERCLOS 是較常見且研究較多的嗜睡指標；相關回顧也整理出它的失效條件與和其他生理、行為及駕駛表現指標融合的研究。近期統合分析發現 PERCLOS-80 與駕駛表現受損有關，但整體證據確定性仍低，需更多標準化、真實場域研究。這支持把 PERCLOS 作為重要特徵，不支持將它當成唯一真值或通用固定門檻。[PERCLOS 證據回顧](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/)、[睡意工具與駕駛適任度統合分析](https://pubmed.ncbi.nlm.nih.gov/42809921/)

UTA-RLDD 原始工作使用連續 blink 特徵並採受試者交叉驗證，為本系統保留眨眼時序和未來評估小型 temporal baseline 提供直接參考。不過它將每段影片標籤套給該段內所有 blink sequence；原作者也指出段內所有眨眼不會有相同疲勞程度。若直接用片段級 label 訓練幀級分類器，標籤噪音會擴散。[原始 UTA-RLDD 論文](https://arxiv.org/abs/1904.07312)

近期涵蓋 78 篇研究的多模態疲勞系統性回顧指出，許多研究在受控資料有高準確率，但少數完成真實情境驗證；個人化和可解釋性報告比例也低。這與本專案需要把無人機操作者實證列為下一階段門檻一致。[IEEE Access 系統性回顧，2025](https://ieeexplore.ieee.org/document/11153487/)

有研究在全天候汽車情境將可見光、紅外線 rPPG 與時序融合，報告多模態方案準確率提升 8.1%（沿用論文表述，不推定是百分點）；但該數字來自特定資料集、紅外線硬體及其模型設計，不能當成只加 RGB rPPG 後本專案的預期增益。它支持的是「互補模態經配對消融可能有價值」，仍需本地驗證。[全天候駕駛疲勞多模態研究](https://pubmed.ncbi.nlm.nih.gov/39048601/)

### 4.2 rPPG 心率：性能受場景控制，不能以「有數字」推論為準

rPPG 受臉部運動、ROI 幾何改變、光源與曝光變化、相機／壓縮、影格率、遮擋及膚色影響。MMPD 收錄手機錄製、不同光線與動作、Fitzpatrick III–VI 膚色；研究者指出早期常用資料集在膚色、動作及攝影裝置代表性上的缺口。[MMPD 論文](https://arxiv.org/abs/2302.03840)、[MMPD 開源資料說明](https://github.com/McJackTang/MMPD_rPPG_dataset)

近期 CHILL 研究以 45 位受試者、明暗光線及靜息／運動後較高心率比較 8 種方法。結果指出方法排序會隨資料集改變；該研究內 POS 在 CHILL 整體表現最佳，但多種傳統與深度方法在較高心率時都出現性能下降。這提醒無人機操作負荷可能抬高心率，應納入實際情境測試；不能引用一個基準數字推定另一台相機或場景也會提升。[npj Digital Medicine：CHILL rPPG 評估](https://www.nature.com/articles/s41746-025-02192-y)

基準工具箱的共同價值不是某個演算法一定最好，而是統一資料處理、方法參數、多資料集評估與統計比較。rPPG-Toolbox 支援監督／非監督方法、跨資料集測試與 motion augmentation；pyVHR 收錄 POS、CHROM、ICA、LGI 等傳統方法並強調多資料集、非參數統計比較。它們適合作為驗證參照，不是直接加進目前執行環境的依賴需求。[NeurIPS 2023 rPPG-Toolbox 論文](https://papers.nips.cc/paper_files/paper/2023/hash/d7d0d548a6317407e02230f15ce75817-Abstract-Datasets_and_Benchmarks.html)、[rPPG-Toolbox GitHub](https://github.com/ubicomplab/rPPG-Toolbox)、[pyVHR GitHub](https://github.com/phuselab/pyVHR)

### 4.3 rPPG HRV：疲勞相關，但個人與情境混淆明顯

兩份駕駛疲勞 HRV 系統性回顧均發現研究間結果不一致：不同研究的指標方向和分類表現差異大，實地 HRV 會被非疲勞因素混淆；較新的回顧整理到 HRV 系統準確率 44%–100% 的大幅差異，結論仍要求涵蓋更多真實駕駛情境的受試者研究。[Burlacu 等人系統性回顧](https://pubmed.ncbi.nlm.nih.gov/34565082/)、[Hörnsten 等人系統性回顧](https://pubmed.ncbi.nlm.nih.gov/36155280/)

rPPG 輸出的 pulse-rate variability 也不能在沒有驗證時直接等同 ECG HRV。HRV 標準文件建議短時分析以標準化 5 分鐘記錄比較；要估 LF，記錄需涵蓋低頻週期，而 0.04 Hz 的 10 個週期約 250 秒。30 秒只約 1.2 個最低 LF 週期，LF/HF 的點估計不應被解讀成穩定疲勞／壓力特徵。[ESC/NASPE 標準](https://pubmed.ncbi.nlm.nih.gov/8598068/)、[標準與頻域紀錄長度說明](https://doi.org/10.1016/S0735-1097%2899%2900354-X)。另外，rPPG HRV／PRV 的近期回顧亦指出活動狀態與訊號品質會降低對 ECG 的一致性；因此每項 HRV 特徵均應和同步參考設備做誤差與一致性分析。[rPPG 用於壓力／工作負荷的範疇回顧](https://pmc.ncbi.nlm.nih.gov/articles/PMC13533986/)

## 5. 建議方案與優先順序

### P0：先建立不洩漏、可重現的準確度驗收

**作法**

- 分清兩個標籤：疲勞／警覺的參考真值，以及 rPPG 心率／心搏間期的生理真值。心跳帶或 ECG 只能驗證脈搏測量，不能直接當疲勞標籤。
- 取得逐時間窗標註：以 KSS／任務後評分、盲化人工事件標註、反應時間／操作錯誤等互補；對標註不一致或不確定區間保留 `ambiguous`，不硬分成確定清醒／嗜睡。
- 以 participant 為 group 切分 train／validation／test；同一個人的影片和重疊時間窗不可跨集合。所有 threshold sweep、特徵選擇、個人化模型選項都只能在 train/validation 執行，最後 test 一次鎖定。
- 以受試者為單位 bootstrap 信賴區間；不以數十萬相鄰影格製造虛假的大樣本數。UTA-RLDD 全部 60 位都可作受試者折分分析，但需保留獨立測試折；同時新增無人機控制台情境的自有資料。

**主要驗收量**

- 疲勞：macro AUROC、macro AUPRC、各類 recall／specificity、混淆矩陣、誤報次數／小時、漏掉的嗜睡事件、首次穩定警告提前量、低品質／無判斷比例及校準誤差。
- rPPG：每窗 BPM MAE／MedAE／RMSE、平均 bias 和 Bland–Altman 95% limits of agreement、可用資料比例、拒答／錯誤比例；HRV 另比較 RMSSD／SDNN 與 ECG 或經驗證接觸式參考。只回報相關係數不足以證明測量一致。

### P1：行為主幹做個人化、品質分層的時序校準

- 保留 PERCLOS 與持續閉眼為主特徵，以已有的 `PersonalProfile` 評估每人相對清醒基線的偏移和變化率；基線只能用確認清醒的校準段建立，測試期間不可偷看該受試者的未來標籤。
- 依使用情境標註 PERCLOS 規則：本系統由 EAR 門檻計算的比例，不必然等同文獻「眼瞼遮住瞳孔超過 80%」的 PERCLOS-80。報告輸出應寫明本地演算法定義與有效觀測分母，避免名稱相同但量測不同。
- 對 PERCLOS、閉眼 duration／opening velocity、blink rate、head nod、gaze 等特徵做 10／30／60 秒的視窗摘要與趨勢比較，使用 nested subject-wise validation 決定視窗，避免單純改成更長視窗而增加警告延遲。
- 現有歷史 UTA 校準中 blink temporal、microsleep 在小型樣本呈弱或反向訊號；維持低權重並對無人機情境重新標註，不因文獻或直覺而上調。凝視固定、皺眉、說話張嘴和視線轉移先保留為輔助特徵，報告其獨立 AUC 及增量效益。

### P2：修正 rPPG 方法身分，進行配對離線比較

先將目前函式標記為 CHROM-like 並補上正確對照測試，再以同一批 per-ROI RGB 時序比較：現行 CHROM-like、標準 POS、（可選）CHROM／POS 後的單 ROI 與現行四 ROI。比較必須固定同一段影片、時間戳、濾波、Welch 和 reference 對齊，分別回報全體和低光、轉頭、說話、遮擋、高心率子集。

不要直接把 CHROM 換 POS 就預設會更準。CHILL 的結果支持「方法表現會依條件改變」，而 pyVHR／rPPG-Toolbox 強調多資料集比較；因此本地真值的配對誤差和涵蓋率才是決策依據。

### P3：建立 rPPG 的訊號品質與可信度分級

- 由實際 reference 誤差校準 quality score/SQI，而非只把頻帶能量比例當成準確度機率。候選診斷包含 PSD 主峰集中度／諧波一致性、有效 ROI 數、各 ROI pulse 頻率一致性、皮膚區面積、亮度變化、頭動、臉部姿態及可用樣本率。
- 逐 ROI 量出與真值的誤差，再比較等權與質量加權；只有被真值證明品質與準確度關係穩定時，才考慮以該訊號權重做混合。幾何姿態權重不能直接等同脈搏 SNR。
- 用品質分數分層量測 error-versus-coverage 曲線，驗證較低品質時系統是否正確 abstain，而不是單純把所有視窗都輸出 BPM。
- 公開／研究資料可用 MMPD、PURE、UBFC、COHFACE 等先做演算法回歸和跨資料集 sanity check；最終決策仍需目標相機、室內／夜間、頭動及操作負荷下同步記錄 ECG／PPG 真值。

### P4：把生理輸出和疲勞判斷拆開驗證

- 心率估計通過 BPM 真值驗證，只表示可測心率，不表示心率能預測疲勞。將 BPM 從單純的通用 60–100 bpm 區間偏離分數改成候選研究變項，先比較「不使用 BPM」與「個人靜息／任務基線偏移」對疲勞標籤的增量效益。
- 30 秒 HRV 中的 LF/HF 目前不應作 fatigue score 的有效訊號。最小風險方案是先將 LF/HF／stress heuristic 排除於疲勞真值結論之外，在維持觀察紀錄下以足夠長的穩態資料和參考設備重新驗證；若不能取得足夠資料，保留生理趨勢顯示但不給疲勞加分。
- RMSSD／SDNN、HR、stress probability 分別評估，不用一個合成 stress_prob 掩蓋各特徵誤差；報告須揭示個體 baseline、任務負荷及光線／運動子群結果。
- 若行為品質不足或尚未校準，結果顯示「疲勞資料不足／低信心」，不要讓 rPPG 單獨承接 100% 疲勞分數；除非未來已用獨立無人機操作者資料證明該使用模式安全且有效。

### P5：有足量標註後再評估 temporal ML

先做可解釋的序位邏輯迴歸或小型樹模型作行為特徵 baseline，再比較原始 UTA-RLDD HM-LSTM 的 blink-sequence 思路；避免在目前約 60 位 UTA subject 和少量自有資料上直接訓練大型 CNN／Transformer。影片級弱標籤下可評估以 session/window aggregation 或 multiple-instance learning 對齊片段標註粒度，而不是把整支影片 label 當逐幀真值。

輸入保留可說明的事件摘要（PERCLOS 變化、長閉眼次數、blink temporal、品質及可用比例），並用 subject-wise holdout、外部資料集及無人機情境最後測試。只有模型在行為規則基線之外穩定改善誤報／漏報、校準和延遲，才接受額外模型複雜度。

## 6. A/B 與消融實驗矩陣

同一個鎖定測試集上至少比較以下設定；每一列僅在 validation fold 調參：

| 方案 | 行為來源 | 生理來源 | 目的 |
|---|---|---|---|
| A：現行基線 | 現行規則／個人基線設定 | 現行 rPPG 融合 | 固定比較基準 |
| B：PERCLOS 主幹 | PERCLOS + 個人清醒偏差 | 關閉 | 判斷本地較強行為特徵 |
| C：行為時序 | PERCLOS、閉眼及 blink 時序 | 關閉 | 估計時序特徵增量 |
| D：已驗證 rPPG BPM | 與 A 相同 | 只有 BPM，使用 reference-valid window | 心率是否增加疲勞預測資訊 |
| E：rPPG HRV | 與 A 相同 | 有足夠視窗且對照 ECG／PPG 的 RMSSD／SDNN；不把 30 秒 LF/HF 當有效 | 生理變項增量 |
| F：品質感知融合 | 與 A 相同 | 依已校準 quality 和可用性融合；不足則 abstain | 檢驗錯誤警示與覆蓋率 |
| G：訊號演算法 | 固定 ROI 與後處理 | 現行 CHROM-like vs canonical POS | rPPG 特徵抽取配對比較 |
| H：ROI 策略 | 固定疲勞分數 | 等權 vs per-ROI 品質加權 | 檢驗 ROI 權重是否有真值效益 |

主要成功條件：F 相對 A 在相同覆蓋率下，受試者群集信賴區間顯示誤報／漏報或預警時間有實質改善；或在固定誤報率下提升嗜睡事件 recall。若只提高 AUC 卻大幅增加誤報、延遲或無判斷比例，不算安全有效的整體提升。實質改善幅度應由產品需求與危害分析預先設定，不應在看到測試結果後才挑有利門檻。

## 7. 執行順序建議

| 階段 | 工作 | 完成條件 |
|---|---|---|
| 0 | 鎖定資料字典、PERCLOS 實際定義、現行 fusion baseline 和資料切分 | 可從固定 commit 重現基準報表，受試者不跨 split |
| 1 | 逐窗疲勞標註與同步 rPPG 參考資料；先涵蓋目標相機、光線、轉頭／說話及任務負荷 | 有受試者層級訓練、驗證、鎖定測試折，並記錄不確定標註 |
| 2 | 重跑現行規則、PERCLOS 個人化、CHROM-like vs POS、rPPG 品質／coverage 評估 | 完成預先定義的 A–H 消融表及按情境分層結果 |
| 3 | 只對通過評估的訊號重新校準融合與遲滯 | 與凍結基線比較誤報／漏報、預警時間、信賴區間及數值漂移 |
| 4 | 擴展更多無人機操作員及實際任務驗證 | 外部受試者仍維持改善，且沒有重要子群的可接受度退化 |

不建議先做：只在現有 12 位 UTA subject 上再掃大量權重；以 rPPG 的生理指標提高疲勞權重；先訓練大模型再用同一組受試者報驗證結果；把人臉偵測率當疲勞準確率；以相關係數或單一平均值代替錯誤分布與可用率。

## 8. 實作後準確度提升信心

這裡的「信心」是對方法在完成所列實驗後，能否改善**本專案目標資料上的可測判讀**之證據信心，不是保證百分比。若未遵守受試者隔離、品質分層、真值同步與鎖定測試，所有等級至少下調一級。

| 候選改進 | 準確度提升信心 | 原因與限制 |
|---|---|---|
| 使用受試者獨立、逐窗標註與群集信賴區間做門檻驗證 | **高（提升測量可信度）；準確度提升本身不保證** | 可避免資料洩漏及錯誤結論，卻不會自動改變分類器。 |
| PERCLOS／長閉眼以個人清醒基線重校準，並按品質與場景分層 | **中至高** | 和疲勞機制及本地已觀察到的 PERCLOS 訊號一致；本地小樣本 AUC 與受試者 CI 仍不足，還需無人機目標族群驗證。 |
| 行為短／中／長時間窗趨勢與原始規則消融 | **中** | UTA-RLDD 原始時序研究與多來源疲勞研究支持時間特徵；標籤粒度、預警延遲及弱特徵仍可能抵銷收益。 |
| 修正函式為標準 POS，和現有 CHROM-like 配對測試後選最佳者 | **方法身分判定：高；數值提升：低至中** | 現行公式與標準 CHROM 高度吻合是程式碼可核對事實；兩種方法表現依資料與相機改變，沒有理由預設換成 POS 就提升。 |
| 以 per-ROI 真值誤差驗證質量加權混合 | **中** | 有明確的訊號融合合理性，但現有幾何／遮擋權重不等於脈搏 SNR；必須用帶真值的同段 A/B 決定。 |
| rPPG 品質門控與 abstain/no-data 狀態 | **中至高（降低不可信輸出）；對覆蓋率有代價** | 研究明確顯示光線、動作及心率狀態會改變誤差；可望降低錯誤資料參與融合，但有效輸出比例可能下降。 |
| 把通用 BPM 偏差／30 秒 LF/HF 從疲勞分數移除或暫停 | **高（避免無效生理證據造成誤判）；提升 AUC 未知** | HRV 疲勞證據矛盾、30 秒 LF/HF 不足以估低頻；移除可能減少假陽性，但須以真值資料確認沒有犧牲真實正例。 |
| rPPG-only 時仍輸出完整疲勞分數 | **低；目前不建議** | 文獻支持 HR／HRV 與疲勞有關聯，不表示一段心率可特異診斷疲勞；現行生理映射與 BPM 正常帶不是疲勞驗證模型。 |
| 現有小資料直接改用大型 CNN／Transformer | **低** | 受試者數不足以支撐可泛化的端到端模型；高 paper benchmark 分數不能取代 subject-disjoint 外部驗證。 |

**整體判斷：** 下一輪若先完成 P0，再實作 P1、P2、P3 並執行鎖定測試，對「目標環境下的可信疲勞判斷」有**中等**提升信心；其中誤報控制與知道何時不該相信輸出，比單純追求總準確率有較高把握。若僅替換 POS、提高 HRV 權重或調整 85/15 融合比例，提升精準度的信心為**低**。

目前沒有足夠依據估算「預期準確率增加 X%」。本地最好的 AUC 為小樣本點估計，且留出區間寬；外部論文結果使用不同攝影設備、族群、標籤定義和資料切分，不可直接轉換成本專案預期提升值。

## 9. 風險與成功定義

- **疲勞標籤不是疾病診斷。** 系統適合作為操作員警覺風險提示與研究原型；不能以本報告或 UTA-RLDD AUC 宣稱醫療診斷或已證明可避免事故。
- **無判斷是有效輸出。** 當臉部、行為基線或 rPPG 品質不足，低信心／資料不足比用不可靠數值輸出清醒或疲勞更誠實。
- **心率真值不是疲勞真值。** 心跳帶可協助校正 BPM；疲勞仍需獨立、盲化、逐時間窗標註及任務表現參考。
- **不同族群及裝置要分層。** 報告平均值同時列出性別、膚色範圍、眼鏡、光線、相機、姿勢和任務負荷子群；若資料量不足，清楚標成未知，不能把平均值當公平性保證。
- **安全用途要保留人工判斷。** 在操作員安全應用中，所有閾值與介入策略都需由實際危害分析、操作者測試及使用情境決定，不宜自動控制飛行器或作人事判定。

本報告不宣稱已完成新的準確率測試，也不更動任何數值演算法。下一次修改 `rppg/`、`gui/fatigue_engine.py` 或 `gui/fatigue_scorer.py` 前，應先依第 5–7 節完成資料與 A/B 設計，然後依專案重量級演算法改動流程執行完整測試、golden check 和數值影響審查。

## 10. 主要參考資料

1. Ghoddoosian, R., Galib, M., & Athitsos, V. (2019). *A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection*. CVPR Workshops. [論文](https://arxiv.org/abs/1904.07312) · [作者程式庫](https://github.com/rezaghoddoosian/Early-Drowsiness-Detection) · [UTA-RLDD 官方頁](https://sites.google.com/view/utarldd/home)
2. May, J. F., & Baldwin, C. L. (2023). *PERCLOS-based technologies for detecting drowsiness: current evidence and future directions*. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/)
3. Burlacu, A. et al. (2021). *Accurate and early detection of sleepiness, fatigue and stress levels in drivers through Heart Rate Variability parameters: a systematic review*. [PubMed](https://pubmed.ncbi.nlm.nih.gov/34565082/)
4. Hörnsten, E. G. et al. (2022). *Detecting driver fatigue using heart rate variability: A systematic review*. [PubMed](https://pubmed.ncbi.nlm.nih.gov/36155280/)
5. Task Force of the ESC and NASPE. (1996). *Heart rate variability: standards of measurement, physiological interpretation and clinical use*. [PubMed](https://pubmed.ncbi.nlm.nih.gov/8598068/) · [短時頻域分析建議](https://doi.org/10.1016/S0735-1097%2899%2900354-X)
6. Quigley, K. S. et al. (2024). *Publication guidelines for human heart rate and heart rate variability studies in psychophysiology—Part 1*. [Psychophysiology](https://doi.org/10.1111/psyp.14604)
7. Tang, J. et al. (2023). *MMPD: Multi-Domain Mobile Video Physiology Dataset*. [arXiv](https://arxiv.org/abs/2302.03840) · [資料庫 GitHub](https://github.com/McJackTang/MMPD_rPPG_dataset)
8. Lee, R. J., Sivakumar, S., & Lim, K. H. (2024). *Review on remote heart rate measurements using photoplethysmography*. Multimedia Tools and Applications. [Springer](https://doi.org/10.1007/s11042-023-16794-9)
9. *The reliability of remote photoplethysmography under low illumination and elevated heart rates* (2025). npj Digital Medicine. [論文與 CHILL 資料集](https://www.nature.com/articles/s41746-025-02192-y)
10. Liu, X. et al. (2023). *rPPG-Toolbox: Deep Remote PPG Toolbox*. NeurIPS Datasets and Benchmarks. [論文 PDF](https://papers.nips.cc/paper_files/paper/2023/file/d7d0d548a6317407e02230f15ce75817-Paper-Datasets_and_Benchmarks.pdf) · [GitHub](https://github.com/ubicomplab/rPPG-Toolbox)
11. Boccignone, G. et al. (2022). *pyVHR: a Python framework for remote photoplethysmography*. PeerJ Computer Science. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9044207/) · [GitHub](https://github.com/phuselab/pyVHR)
12. Wang, W. et al. (2017). *Algorithmic Principles of Remote-PPG*. IEEE Transactions on Biomedical Engineering. [DOI](https://doi.org/10.1109/TBME.2016.2609282) · [TUE Research Portal](https://research.tue.nl/en/publications/algorithmic-principles-of-remote-ppg/)
13. Boccignone, G. et al. (2020). *An Open Framework for Remote-PPG Methods and Their Assessment*. IEEE Access. [論文](https://doi.org/10.1109/ACCESS.2020.3040936)
14. *A Multimodal Systematic Review of Drivers’ Fatigue Detection Methodologies, Datasets, and Models* (2025). IEEE Access. [IEEE Xplore](https://ieeexplore.ieee.org/document/11153487/)
15. *Technologies for detecting and monitoring drivers' states: A systematic review* (2024). Heliyon. [ScienceDirect](https://doi.org/10.1016/j.heliyon.2024.e39592)
16. *When is rPPG physiologically valid for stress and workload monitoring? A PRISMA-ScR scoping review* (2026). [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC13533986/)
17. *Sleepiness assessment tools for predicting fitness to drive: a systematic review and meta-analysis* (2026). [PubMed](https://pubmed.ncbi.nlm.nih.gov/42809921/)

---

**本次未執行：** 沒有改動或重跑數值演算法、未重新下載／回放論文資料集、未新增 fatigue 標註或 HRV 真值，也未執行 pytest；本次交付是研究報告與程式碼靜態對照。

**剩餘風險：** 文獻支持的是候選方法與驗證方式；實際準確度提升仍取決於逐窗疲勞標註、同步生理參考及受試者獨立的無人機情境測試。
