# rppg_mediapipe_system_v2

rPPG + MediaPipe based fatigue/physiology monitoring with a desktop GUI and a web dashboard.

本專題主旨為「無人機駕駛員疲勞狀態監測」：使用一般攝影機觀察遠端操作員的臉部、眼部、姿態與 rPPG 輔助生理訊號，提供長時間監控或操控任務中的警覺度下降提示。UTA-RLDD replay 是可重現驗證與門檻校正工具，不是把專題改成汽車駕駛分類器。

## Features
- Live camera preview with MediaPipe annotations
- rPPG heart-rate and HRV metrics
- Fatigue/behavior analysis overlays
- Recording to SQLite (.db) and video (.mp4)
- Web dashboard for live metrics and playback
- Web dashboard 預設僅本機存取；可在 GUI「設定 → 允許區域網存取 Web 儀表板」開啟後，由同區域網裝置以 `http://<主機IP>:5000` 連線。為降低資安風險，Socket.IO CORS 僅允許本機與 LAN IP 來源（請以主機 IP 連線，勿用主機名稱），且 File Browser（`/api/fb/*`）端點僅接受本機發起的請求。
- Web dashboard 會在新連線與重新整理後同步 GUI 最新狀態，live camera preview 目標為 30 FPS；UTA-RLDD 離線 replay 預覽仍約 20 FPS。
- 疲勞警報器：GUI「設定 → 警報器設定…」可依 `LOW_VIGILANCE` / `DROWSY` / `CRITICAL` / `MICROSLEEP` 指定不同音效（預設路徑 `assets/alerts/*.wav`）
- rPPG BPM 估測回到第一版基準：有效 ROI 等權平均、Welch peak 直接輸出，並用峰值插值與輕量平滑補足 71/72/73 這類細節。
- 疲勞融合預設以 MediaPipe 行為疲勞為主，rPPG 權重降為 15%，且 SQI、quality 或 ROI 數不足時不參與融合。
- MediaPipe 姿態補償、ROI 動態權重、遮擋降權與品質診斷
- Blendshape 個人化 baseline 校準與跨 session 持久化

## Requirements
- Python 3.10+ recommended
- Windows and Ubuntu Linux supported
- Ubuntu desktop/runtime libraries for Qt, OpenCV, and V4L2 cameras

## Setup
Windows:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Ubuntu:
```bash
bash scripts/setup_ubuntu.sh
```

If the virtual environment already exists, reinstall/update Python dependencies with:
```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Run
```bash
python main.py
```

Ubuntu:
```bash
.venv/bin/python main.py
```

Ubuntu GUI 若出現 `Could not load the Qt platform plugin "xcb"`，先重新執行 setup 補齊 Qt xcb runtime：

```bash
bash scripts/setup_ubuntu.sh
```

若仍需追蹤 Qt plugin 載入路徑，可用：

```bash
QT_DEBUG_PLUGINS=1 QT_QPA_PLATFORM=xcb .venv/bin/python main.py
```

本專案 GUI 使用 PySide6。程式啟動時會在建立 `QApplication` 前把 Qt platform plugin 路徑固定回 PySide6，避免 OpenCV wheel 的 `cv2/qt/plugins` 覆蓋 PySide6 的 xcb plugin。

Windows 若 FPS 可達 30 但畫面延遲逐步增加，通常是相機、分析端或 Qt 預覽訊號累積舊幀。GUI 會嘗試把 OpenCV camera buffer 降低，讓分析 worker 永遠取最新幀，並限制預覽影像訊號輸出避免主執行緒堆積。Windows 的自動後端會優先嘗試低延遲的 `DSHOW`，再 fallback 到 `MSMF`；若仍有特定相機卡頓，可在 GUI 後端手動切換比較穩定性。

若相機畫面左右相反，可在 GUI 攝影機區啟用或關閉「水平翻轉（鏡像校正）」。此設定會同步套用到預覽、錄影與分析輸入，避免畫面與分析來源不一致。

若 `setup_ubuntu.sh` 在非互動環境因 sudo 密碼失敗，請在自己的終端機直接執行：

```bash
sudo apt-get update
sudo apt-get install -y libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 v4l-utils
```

Optional demo:
```bash
python -m rppg.demo_rppg_live
```

## Canva 系統流程圖 App

`rppg-flowchart/` 是以 Canva CLI 建立的流程圖插入 App，用於把本專案的系統流程圖放入 Canva 設計頁面。流程圖節點以用途描述呈現，例如影像輸入、臉部推論、行為疲勞分析、rPPG 生理訊號估測、品質守門、融合評分、即時告警、記錄、Web 與回放，不以實際程式檔名作為區塊名稱。

```powershell
cd rppg-flowchart
npm install
npm start
```

Canva App ID 為 `AAHAACArWJM`，可在 Developer Portal 檢查設定：https://www.canva.com/developers/app/AAHAACArWJM

常用檢查：

```powershell
npm run lint
npm run lint:types
npm test -- --runInBand
npm run build
canva apps config status --lite
canva apps doctor --ci
```

## UTA-RLDD replay

本專案可把 UTA-RLDD 影片當作可重現的「離線鏡頭」來批次測試，不會改動即時攝影機 worker。UTA-RLDD 官方定義為 `0=Alert`、`5=Low Vigilant`、`10=Drowsy`，來源：https://sites.google.com/view/utarldd/home。回放模式會使用影片 FPS 產生 deterministic timestamp，疲勞校準起點會對齊第一個有效人臉 frame 的時間，因此前約 5 秒為 `CALIBRATING`，後續才進入 `OK / LOW_VIGILANCE / DROWSY / CRITICAL` 等狀態統計。

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "%USERPROFILE%\Downloads\Fold1_part1" --max-videos 1 --max-frames 300
```

常用參數：

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "%USERPROFILE%\Downloads\Fold1_part1" --subject 01,02 --label 0,5,10
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "%USERPROFILE%\Downloads\Fold1_part1" --output-dir recordings\utarldd_runs\test --write-annotated-video
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "%USERPROFILE%\Downloads\Fold1_part1" --jobs 4
```

預設輸出到 `recordings/utarldd_runs/<timestamp>/`：每支影片一個 `metrics_utarldd_<subject>_<label>_<timestamp>.db`，整批會輸出好讀摘要 `utarldd_summary_<timestamp>.csv`、驗證趨勢報表 `utarldd_validation_report_<timestamp>.csv`、完整欄位 `utarldd_summary_full_<timestamp>.csv`、可視化報表 `utarldd_visual_report_<timestamp>.html` 與 `utarldd_manifest_<timestamp>.json`。`summary` 會包含有效判讀幀數、rPPG 可用率、低品質比例、PERCLOS/眨眼/瞇眼/凝視/哈欠觸發幀數、標籤對齊判讀、主要判斷依據、建議修正方向與優化旗標；`validation_report` 會整理 label 0/5/10 的整體平均，以及同一受試者三段影片是否呈現疲勞趨勢上升，適合判斷這批資料是否支持系統。只有指定 `--write-annotated-video` 才會輸出標註影片，避免容量暴增。

若已經有既有 summary CSV，可不重跑影片，直接產生 HTML 可視化報表：

```bash
.venv/bin/python scripts/utarldd_csv_report.py recordings/utarldd_runs/<timestamp>/utarldd_summary_<timestamp>.csv
```

CLI 支援 `--jobs N` 以多進程平行處理多支影片，建議先從 `--jobs 2` 或 `--jobs 4` 開始，依 CPU、記憶體與溫度調整；同一支影片內仍維持逐幀順序分析，避免破壞 MediaPipe VIDEO mode 的 timestamp 與 tracking 假設。桌面 GUI 也提供「UTA-RLDD 影片測試」區塊，可選資料夾、開始/停止批次、顯示目前 subject/label/video 進度、MediaPipe 人臉特徵與 ROI 標註預覽，以及摘要檔路徑。`開始批次` 會啟用單工預覽，適合抽查偵測畫面；`平行驗證` 會依 GUI 的「平行數」設定使用多進程、停用預覽，適合正式大量驗證，GUI 平行數上限為 4。平行驗證會自動停用 `輸出標註影片`，避免多個子行程同時寫 mp4 造成 Windows/OpenCV/MediaPipe 資源壓力；需要標註影片時請用單工 `開始批次`。若某個子行程異常中止，批次會停止派發新工作，把未完成影片寫成 `failed` 並保留 CSV/manifest。平行驗證時可看 GUI 的「處理清單」：`進行中` 會列出目前正在跑的影片，`已完成` 顯示完成數/總數，`最近完成` 顯示剛處理完的 subject/label、frame 數、狀態與 face rate。GUI 預覽為了保持主視窗流暢，會以最高約 20 FPS 顯示並限制預覽影像尺寸；這只影響螢幕顯示，不影響 SQLite、CSV 與 manifest 的逐幀分析結果。這套 replay 適合用來蒐集門檻校正資料與比較趨勢，但 UTA-RLDD label 是整段影片類別，不是逐幀 ground truth，也不能完全取代無人機駕駛場域的真人測試。

2026-06-07 最新 36 支影片測試結果整理於 `docs/2026-06-07-utarldd-analysis.md`。本次影片處理完成率為 100%，平均人臉偵測率約 99.93%，代表回放與偵測管線穩定；但融合分數未隨 `0 -> 5 -> 10` 穩定上升，因此不能宣稱三分類準確率接近 100%。同批次 `recordings/utarldd_runs/20260607_122601/utarldd_summary_20260607_122601.csv` 已可轉成 `utarldd_visual_report_20260607_122601.html`，適合用於畢專報告的限制分析與後續門檻校正依據。

## MediaPipe tuning and calibration

目前 `active_profile` 預設為 `stable_indoor`，提高 Face Landmarker tracking confidence 並加強 ROI polygon 平滑，目標是降低室內 webcam 下的 landmark 與 ROI 抖動。若環境偏暗或頭部動作較大，可切換 `low_light` 或 `high_motion` 後用固定錄影回放比較。

rPPG BPM 輸出以第一版較準的流程為基準：有效皮膚 ROI 直接等權平均後送入 POS、band-pass 與 Welch peak。新版只在頻譜峰值附近做插值來提升解析度，避免只跳 70、80、90、100 這類粗略數值；BPM 只排除明顯不合理的生理範圍，避免因品質 gate 太嚴而長時間顯示空白。

可調參數集中在 `config/mediapipe_tuning.json`：

- `face_landmarker`：Face Landmarker 的 detection / presence / tracking confidence。
- `rppg_roi`：ROI 基礎權重、姿態懲罰、遮擋門檻、最小權重、ROI polygon EMA 平滑、landmark jitter 與 ROI 面積穩定度門檻。
- `quality`：rPPG / fatigue 統一品質分數的組合權重。
- `blendshape`：blendshape baseline 校準秒數、最小樣本、EMA 與眼眉嘴輔助閘門。
- `active_profile` / `profiles`：可切換 `default`、`stable_indoor`、`low_light`、`high_motion` 等 MediaPipe 場景 profile。切換後需重啟 worker / 應用程式，Face Landmarker options 不做熱更新。

`canonical_roi_warp_enabled` 是實驗開關，預設關閉。啟用後會做保守的姿態導向 ROI 幾何正規化；因會改變 ROI 取樣分布，正式比較前應保持關閉。

個人化 baseline 會自動儲存在 `config/mediapipe_calibration.json`，此檔案包含使用者/環境校準結果，不納入版本控制。

## rPPG BPM 校準（手錶參考）

手錶心率僅用於**校準 session**；日常疲勞監測不戴手錶，主程式會讀取 `config/rppg_calibration/manifest.json` 的 active 版本並套用 BPM 偏移。

在 `main.py` 中開啟 **校準 → 開啟 rPPG 心率校準器…**，即可：

- 接收手錶 `POST /hr` HTTP 資料
- 即時比對手錶 BPM 與 rPPG BPM
- 儲存校準版本、切換版本（含回到未校準的 `v000_origin`）

校準資料儲存於 `config/rppg_calibration/`（不納入版本控制）。

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
```

若有對應錄影檔，可用 profile sweep 比較不同 MediaPipe profile 的偵測率、ROI 可用數、landmark jitter 與 ROI 面積穩定度：

```bash
.venv/bin/python scripts/mediapipe_profile_sweep.py recordings/video_YYYYMMDD_HHMMSS.mp4 --csv reports/mediapipe_profile_sweep.csv
```

調整 tuning 會影響新錄製資料與舊錄製資料的可比性；需要比較精準度或穩定度時，請使用同一段錄影回放 sweep。

On Ubuntu, camera access uses V4L2 by default. If no camera appears, check device permissions:
```bash
ls -l /dev/video*
groups
```

Add your user to the `video` group if needed, then log out and back in:
```bash
sudo usermod -aG video "$USER"
```

若相機黑屏或 GUI 沒有畫面，先用專案診斷腳本分辨硬體/權限與程式問題：

```bash
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2
```

若 720p 僅有約 10 FPS，先檢查相機格式。許多 USB UVC webcam 在 `1280×720 YUYV`
只支援 10 FPS，但 `1280×720 MJPG` 可達 30 FPS；GUI 在 Linux 會優先要求 MJPG。
可用下列指令確認協商結果：

```bash
v4l2-ctl --list-formats-ext -d /dev/video0
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2 --width 1280 --height 720 --fps 30
```

可追加檢查：

```bash
v4l2-ctl --list-devices
v4l2-ctl --all -d /dev/video0
ls -l /dev/v4l/by-id/
fuser /dev/video0
.venv/bin/python -m rppg.demo_rppg_live --list-cameras --backend v4l2
```

診斷判讀：
- `/dev/video*` 不存在：偏向硬體未枚舉、驅動或容器/權限隔離問題。
- OpenCV 無法開啟相機：偏向權限、裝置被占用、後端不相容或硬體/驅動問題。
- OpenCV 可讀幀但亮度接近全黑：偏向鏡頭蓋、隱私快門、光線不足或虛擬相機無來源。
- 終端出現大量 `Camera index out of range` 或 `VIDIOC_QBUF`：通常是掃描不存在的相機 index 或把 metadata 節點當成相機；GUI 會在 Linux 只掃描實際存在且具備 Video Capture capability 的 `/dev/video*`。
- 診斷腳本可讀到非黑畫面但 GUI 黑屏：偏向 GUI 顯示或相機後端協商問題，請在 GUI 中切換「自動 / V4L2 / FFMPEG」後端再測。

## Project layout
- `rppg/`: rPPG-specific signal processing, MediaPipe ROI extraction, and the standalone live demo
- `gui/`: desktop GUI, fatigue analysis, recording, and web dashboard integration
- `config/mediapipe_tuning.json`: MediaPipe、ROI、quality score 與 blendshape 校準參數。
- `scripts/replay_calibration_summary.py`: 從錄製資料庫彙整 rPPG / fatigue 品質與 ROI 診斷。
- `scripts/mediapipe_profile_sweep.py`: 以錄影檔重跑 MediaPipe profiles，輸出偵測與 ROI 穩定度比較。
- `docs/rppg_technical_report.md`: rPPG 技術、演算法、模型與系統運作說明；可用 `scripts/build_rppg_pdf.py` 產生 PDF。
- `docs/2026-05-21-mediapipe-landmark-expansion-log.md`: 本次新增 MediaPipe 部位與精準度提升的更新紀錄。

- `scripts/utarldd_replay.py`: UTA-RLDD 影片批次回放測試，輸出 SQLite、summary CSV、validation CSV、完整 CSV、HTML 與 manifest。
- `scripts/utarldd_csv_report.py`: 將 UTA-RLDD summary CSV 轉成單檔 HTML 可視化報表，整理趨勢圖、判斷依據與優化建議。

## Technical reports
- `docs/無人機駕駛員疲勞狀態監測系統_實務專題報告.pdf`: 依電子工程系實務專題報告格式產生的完整 PDF 書面報告，包含首頁、中文摘要、英文摘要、目錄、圖目錄、緒言、簡介、理論、軟硬體分析、測試結果、結論、建議、附錄與參考資料。
- `scripts/build_practical_project_report_pdf.py`: 從 repo 既有技術文件與 UTA-RLDD 回測 CSV 重新產生正式 PDF 報告。
- `docs/system_overview_technical_report.md`: 系統總報告書，整合 rPPG、MediaPipe 疲勞偵測、融合分數、架構、驗證與限制。
- `docs/rppg_technical_report_v2.md`: rPPG 子系統報告書，整理模型、演算法、input/output、架構與可信度驗證方式。
- `docs/rppg_heart_rate_calibrator_technical_analysis.md`: rPPG 心跳校準器技術分析報告，整理手錶參考校準、offset 演算法、品質 gate、文獻支持與限制。
- `docs/mediapipe_fatigue_technical_report.md`: MediaPipe 疲勞偵測子系統報告書，整理 Face Landmarker、行為疲勞演算法、融合分數與驗證方式。
- `docs/drone_operator_fatigue_application_report.md`: 無人機操作員疲勞監測應用定位報告，整理民用專業無人機、訓練、巡檢與公共安全場景的系統價值。
- `docs/drone_operator_system_optimization_report.md`: 無人機操作員疲勞監測系統優化建議報告，整理可信度、校準、任務流程、誤報漏報、報告輸出與部署穩定性優化。
- `docs/utarldd_replay_validation_report.md`: UTA-RLDD 影片回放驗證系統技術報告，整理回測流程、資料可信度、演算法原理、輸出報表與限制。
- `docs/system_architecture_algorithm_map.md`: 用途導向的專案架構、資料流與演算法地圖，不以實際檔名作為架構節點。
- `docs/system_overview_technical_report.pdf`: 系統總 PDF 報告。
- `docs/rppg_technical_report_v2.pdf`: rPPG 子系統 PDF 報告。
- `docs/mediapipe_fatigue_technical_report.pdf`: MediaPipe 疲勞偵測 PDF 報告。
- `docs/drone_operator_fatigue_application_report.pdf`: 無人機操作員疲勞監測應用定位 PDF 報告。
- `docs/drone_operator_system_optimization_report.pdf`: 無人機操作員疲勞監測系統優化建議 PDF 報告。
- `docs/utarldd_replay_validation_report.pdf`: UTA-RLDD 影片回放驗證系統 PDF 報告。
- `docs/system_architecture_algorithm_map.pdf`: 用途導向專案架構、資料流與演算法地圖 PDF 報告。

既有技術報告 PDF 可使用下列指令重新產生：

```bash
.venv/bin/python scripts/build_technical_report_pdfs.py
```

正式實務專題 PDF 報告可使用下列指令重新產生：

```bash
.venv/bin/python scripts/build_practical_project_report_pdf.py
```

## Poster design artifacts
- `docs/rppg_fatigue_monitoring_poster_design.md`: 依競賽海報範本撰寫的無人機操作員疲勞監測系統海報製作稿，包含標題、摘要、研究方法、成果、SDG 與製作步驟。
- `output/pdf/rppg_fatigue_monitoring_poster_design.pdf`: 海報 PDF 預覽稿，可用於檢查版面配置、文字密度與後續替換 GUI/Web dashboard 截圖。

## Notes
- Recordings are saved under the `recordings/` folder.
- If playback video is needed in the web dashboard, make sure ffmpeg is available (imageio-ffmpeg is supported via requirements).
- `pygrabber` is a Windows-only optional dependency for DirectShow camera names. On Ubuntu/Linux, camera access uses V4L2 and the guarded `pygrabber` imports are not executed.
