# 非接觸式疲勞監測系統

**讓一般攝影機成為操作員狀態觀測工具：即時提示、品質可見、結果可回放。**

本系統面向無人機操作員的長時間操控與監看情境，將臉部行為分析與遠端光體積變化描記（rPPG）整合在同一個桌面操作台。使用者可觀察閉眼、眨眼、視線與姿態變化，查看心率估測及訊號品質，並將監測過程保存為可追溯的紀錄。

核心分析在本機 Python engine 執行；正式介面由 **Tauri v2 + Flutter Web** 提供。日常監測只需要攝影機，BLE 心跳帶為選配的心率校準參考。

這是一套研究與工程驗證工具，尚未具備醫療診斷或飛行安全認證。疲勞分數與壓力指標用於輔助觀察，不能作為適航、健康或繼續執勤的唯一依據。

## 能做什麼

| 能力 | 提供的資訊與操作 |
| --- | --- |
| 即時狀態觀測 | 攝影機預覽、MediaPipe 臉部標註、行為疲勞、心率與訊號品質；可分別啟用行為或 rPPG 分析 |
| 疲勞提示 | 閉眼時間、PERCLOS、眨眼、瞇眼、視線與頭部姿態等特徵，融合分數、趨勢與分級音效 |
| 桌面 Overlay | 獨立透明預覽與數值視窗，支援位置、尺寸、透明度及點擊穿透；實際能力依平台而異 |
| 在地紀錄 | SQLite 指標紀錄與 MP4 錄影，可選自動記錄，供事後追蹤與校準分析 |
| 可重現回測 | 任意影片或 UTA-RLDD 批次回放，輸出 CSV、HTML、manifest 與逐幀資料庫 |
| 個人化校準 | 眼部／表情基線、清醒個人基線，以及選配 BLE 心跳帶的背景 BPM 校準 |
| 診斷與管理 | Flutter 設定區、本機控制 API v2、HTTP／Socket.IO 診斷服務、相機與封裝 smoke 工具 |

## 工作原理

```text
攝影機 → 最新影格佇列 → MediaPipe Face Landmarker
                           ├─ 眼部、視線、姿態、表情 → 行為疲勞
                           └─ 臉部皮膚 ROI → 色彩投影 → 濾波／頻譜 → rPPG
                                             ↓
                                  品質守門 → 融合分數／告警
                                             ↓
                           Flutter 操作台／Overlay／SQLite／MP4

BLE 心跳帶 → 品質檢查與 BPM 校準 → rPPG 校正量
```

同時啟用兩種分析時，`CombinedWorker` 共用一個 Face Landmarker，讓相同影格的特徵同時供應兩個引擎。核心運算與 UI 分離；Python 的 PySide6 負責隱藏 runtime、工作執行緒及音效，Flask／Socket.IO 提供診斷與資料傳輸。原生資料夾、瀏覽器與視窗操作由 Tauri 處理。

### 行為疲勞與融合

- Face Landmarker 提供 478 個臉部特徵點、blendshapes 與姿態資訊；疲勞判讀採用規則、時間窗與個人基線，並非端到端疲勞分類模型。
- EAR 眼睛開合、PERCLOS 閉眼時間比例及持續閉眼是主要觀測；眨眼時序、瞇眼、視線、點頭、皺眉與 MAR 哈欠作為補充。姿態與下視守門用來減少低頭看儀表時的假性閉眼累積。
- 預設融合為 **行為 85% + rPPG 15%**。rPPG 須有人臉、暖機完成、`SQI ≥ 0.45`、`quality ≥ 0.55` 且至少 3 個有效 ROI 才參與；行為訊號須完成人臉與基線校準。單一訊號有效時承擔全部權重，兩者皆無效時顯示「無資料」。
- 融合分數為 0–1，提供清醒、輕度、中度、高度及極度危險五段提示，並保留降級遲滯與趨勢資訊。這些名稱是系統提示等級，不代表經臨床驗證的嚴重度。

### rPPG、HRV 與品質

rPPG 從額頭、雙頰與眉間皮膚 ROI 取得 RGB 時間序列。預設對通過姿態／遮擋篩選的 ROI 等權平均，再以目前 `pos_pulse` 函式分離脈波：各 RGB 通道先作 Z-score，計算 `x = 3R − 2G`、`y = 1.5R + G − 1.5B`，再輸出 `x − std(x) / (std(y) + ε) × y`。此處描述實際色彩投影公式；函式名稱不代表已完整重現原論文 POS。

後續使用 Butterworth 帶通濾波（0.65–3.7 Hz）與 Welch 頻譜峰值估測 BPM，並以峰值插值、平滑及跳變確認處理輸出。ROI 權重、landmark jitter、面積穩定度與 SQI 同時保留供診斷。

HRV 由脈波峰值間隔估測，使用 MAD 去除異常間隔，輸出 RMSSD、SDNN、LF/HF 與可信度。預設至少累積約 30 秒訊號才嘗試 HRV 計算；可顯示 BPM 不代表 HRV 已可靠。一般攝影機的取樣率、曝光、頭部動作及光線會限制心搏間隔精度，短時間窗的 LF/HF 與壓力 heuristic 尤其應視為探索性指標。

BLE 心跳帶使用標準 Heart Rate Service（`0x180D`／`0x2A37`），比對心跳帶 BPM 與 **rPPG 原始 BPM**，通過品質門檻後以低增益自適應方式調整 offset。校準模型為 `scale × bpm + offset`，目前線上流程只調整 offset，信心足夠時保存版本。**心跳帶數值不直接進入疲勞融合分數**；是否提供 RR-Interval 取決於裝置模式。

## 平台與成熟度

| 平台 | 現況與邊界 |
| --- | --- |
| Windows x64 | 已有桌面、相機與 NSIS 安裝版驗證紀錄；相機優先 DirectShow，再嘗試 MSMF；全域快捷鍵目前僅此平台有原生實作 |
| macOS 15+ | 已建立 Apple Silicon arm64 的 `.app`／`.dmg` 建置流程，並保留 source engine 的相機／combined smoke 紀錄；使用 AVFoundation、MediaPipe CPU delegate，須授予相機／Bluetooth 權限 |
| Ubuntu 24.04+／Linux | 已提供 V4L2、WebKitGTK 4.1、啟動及 AppImage／deb 建置腳本；仍需目標主機實測安裝、相機與資料目錄。平台能力表尚未宣告 BLE／Overlay 支援 |
| Android／iOS | `planned`：已有平台邊界與部分原生橋接骨架，尚無可用的原生推論 runtime 或完成驗收的手機版本 |

平台能力契約位於 `gui/platforms/registry.py`。相機 smoke 只證明管線及資料來源運作，不代表疲勞準確度、BLE、Tauri 畫面或完整產品驗收；不同平台的驗證不可互相替代。macOS 本機封裝目前使用 ad-hoc signing，公開散佈仍需正式簽章與 notarization。

## 從原始碼開始

### 1. 準備工具

建議使用已驗證的 **Python 3.12**，並安裝 Node.js／npm、Rust stable 與 Flutter SDK。Windows 需 Microsoft C++ Build Tools；macOS 需 Xcode Command Line Tools；Ubuntu 的系統相依由下方設定腳本安裝。

Python runtime 固定使用 `mediapipe==0.10.35` 與 **唯一**的 `opencv-contrib-python==5.0.0.93`。不要並裝 `opencv-python` 或其他 OpenCV wheel，以免覆寫 `cv2`。MediaPipe `1.0.1` 已知會在目前 macOS Face Landmarker 初始化時於原生 Metal 層中止程序。

### 2. 安裝相依與本機資產

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m scripts.prepare_local_assets --download-model
npm ci
.\.venv\Scripts\python -m scripts.runtime_preflight
```

macOS：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.prepare_local_assets --download-model
npm ci
.venv/bin/python -m scripts.runtime_preflight
```

Ubuntu 24.04+：

```bash
PYTHON_BIN=python3.12 bash scripts/setup_ubuntu.sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.prepare_local_assets --download-model
npm ci
.venv/bin/python -m scripts.runtime_preflight
```

`requirements-dev.txt` 包含 runtime、測試、封裝與技術報告工具；只執行 engine 可改裝 `requirements.txt`。資產準備腳本在本機產生缺失圖示，加入 `--download-model` 才在模型缺失時下載並校驗官方 Face Landmarker 至 `models/face_landmarker.task`，已有檔案會保留。圖片、圖示與模型不納入 Git；啟動前請先完成資產準備，避免在 native preflight 才遇到模型缺失。source 分析 worker 亦保留缺模型時的固定版本補下載流程，準備完整資產後再作斷網驗證。

### 3. 啟動桌面操作台

| 平台 | 從專案根目錄執行 |
| --- | --- |
| Windows | `powershell -ExecutionPolicy Bypass -File .\scripts\start_desktop.ps1` |
| macOS | `bash scripts/start_desktop_macos.sh` |
| Linux | `bash scripts/start_desktop_linux.sh` |

腳本會處理 Flutter 套件並執行 runtime preflight，最後以 `npm run desktop` 啟動 Tauri 與背景 engine。需要單獨診斷 engine 時，可執行 `.venv/bin/python main.py --engine`（Windows 改用 `.\.venv\Scripts\python`）；這不會建立正式桌面主面板。

第一次使用：選擇相機 → 啟用行為與／或 rPPG → 開始監測 → 正視鏡頭、保持自然睜眼並等待校準。穩定光線下可再記錄清醒個人基線；需要 BPM 參考校準時才啟用心跳帶。相機、Overlay、警報與 LAN 選項在 Flutter 的設定／管理區域調整，按「儲存設定」持久化。

核心監測不需要 API 金鑰或 `.env`。一般可調選項放在設定區；開發用進階 tuning 集中於 `config/mediapipe_tuning.json`，預設 profile 為 `stable_indoor`，另有 `default`、`low_light`、`high_motion`。切換 profile 後需重啟 worker；`canonical_roi_warp_enabled` 為預設關閉的實驗功能。比較設定應使用同一段錄影回放。

### 4. 原生封裝

| 平台 | 建置命令 | 產物位置（`src-tauri/target/release/bundle/` 下） |
| --- | --- | --- |
| Windows | `powershell -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1` | `nsis/` |
| macOS | `bash scripts/build_desktop_macos.sh` | `macos/`、`dmg/` |
| Linux | `bash scripts/build_desktop_linux.sh` | `appimage/`、`deb/` |

建置以 PyInstaller 封裝 engine，再由 Tauri 帶入模型與 tuning。release 僅啟動 bundle 內的 engine，開發模式使用 checkout 原始碼。請在目標作業系統重新建立 `.venv`、Flutter、Rust 與 sidecar，不能跨平台複製產物。

## 本機資料與網路邊界

- 開發模式的紀錄位於 `recordings/`；設定、個人基線與校準亦保留本機。安裝版寫入使用者資料目錄，不需要 repository 或 `.venv`。
- `.env`、圖片、錄影、資料庫、模型、個人校準，以及 `AGENTS.md`／`CLAUDE.md` 都不納入版本控制。分享診斷報告前仍應檢查人臉、識別資訊與裝置資料；忽略規則不會清除既有 Git 歷史。
- HTTP／Socket.IO 服務預設只監聽本機：Windows／Linux 為 `127.0.0.1:5000`，macOS 為 `127.0.0.1:5055`（避開 AirPlay Receiver）。根路徑回傳服務診斷 JSON，正式可見介面為 Tauri／Flutter；桌面控制 API 與 `/api/fb/*` File Browser 端點限本機請求。
- 設定區的 LAN 選項可開放遠端 API／串流；請使用面板顯示的完整 token URL。LAN 存取受 shared token 與來源限制保護，**HTTP 沒有 TLS 加密**。只在受信任網路啟用，token URL 亦須視為敏感資訊。
- 核心推論在本機，release Flutter 建置使用 `--no-web-resources-cdn` 將 Web renderer 資源放入產物。初次安裝／模型準備仍需要網路；完整封裝能否在斷網環境運作，須在目標主機驗收。

## 驗證與回測

下列範例使用 macOS／Linux 路徑；Windows 請將 `.venv/bin/python` 改為 `.\.venv\Scripts\python`。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py gui rppg scripts tests
.venv/bin/python -m pip check

# 任意影片：預設輸出 recordings/replay_runs/
.venv/bin/python -m scripts.video_replay /path/to/clip.mp4 --max-frames 300

# UTA-RLDD：輸出 recordings/utarldd_runs/ 下的資料庫與報告
.venv/bin/python -m scripts.utarldd_replay /path/to/UTA-RLDD --jobs 2

# 數值回歸與標籤關聯：須自行準備資料集
.venv/bin/python -m scripts.utarldd_golden check /path/to/UTA-RLDD
.venv/bin/python -m scripts.utarldd_accuracy /path/to/UTA-RLDD --subjects '01,02,03,04,05,06' --max-frames 1200 --jobs 2 --out report.json
```

回放依影片 FPS 產生確定時間戳記，沿用核心分析引擎；只有要求時才輸出標註影片。UTA-RLDD 的 `0／5／10` 分別為 Alert／Low Vigilant／Drowsy，屬整段影片標籤。golden 檢查數值漂移，accuracy 工具檢查分數單調性、Spearman、Drowsy-vs-Alert AUC 與尺度塌陷；兩者不能互相取代，也不能取代無人機操作現場驗證。人臉偵測率或影片處理完成率不等於疲勞分類準確率。

硬體與部署另有專用檢查：`scripts.desktop_hardware_smoke` 測相機管線生命週期，`scripts.hr_belt_monitor` 測真實 BLE notification；`scripts.installed_desktop_smoke`、`scripts.installed_desktop_smoke_macos`、`scripts.installed_desktop_smoke_linux` 分別測原生安裝產物。`scripts.desktop_engine_benchmark` 的合成預覽量測不含實體相機、網路傳輸或 Flutter 繪製。既有結果見 [`docs/benchmarks/`](docs/benchmarks/)。

## 專案導覽

```text
main.py                    Python engine 入口
gui/                       engine 編排、行為分析、記錄、回放與 API
  platforms/               Windows／macOS／Linux 硬體與 runtime 政策
rppg/                      ROI、脈波分離、HRV、BLE 與校準
flutter_app/               正式桌面操作介面與 Overlay
src-tauri/                 原生視窗、桌面整合與 engine 封裝
config/                    共用 tuning；個人資料僅本機保存
scripts/                   安裝、資產準備、診斷、回測與報告工具
tests/                     自動測試與 golden 基準
tools/canva-flowchart/      選用的 Canva 流程圖 App
docs/
  guides/                  安裝與完整操作手冊
  technical/               系統、演算法與驗證技術報告
  reviews/                 REA 分析、發現與改善紀錄
  benchmarks/              已保存的量測結果
  history/                 有日期的實驗與開發紀錄
  plans/                   設計與後續規劃
```

- [文件索引](docs/README.md)與[完整操作手冊](docs/guides/operations.md)：相機與權限疑難、Overlay、LAN、BLE、回測參數、封裝驗收及 PDF 報告產生。
- [系統總報告](docs/technical/system_overview_technical_report.md)與[架構／演算法地圖](docs/technical/system_architecture_algorithm_map.md)：輸入輸出、資料流及設計邊界。
- [rPPG 技術報告](docs/technical/rppg_technical_report_v2.md)、[行為疲勞技術報告](docs/technical/mediapipe_fatigue_technical_report.md)與[回放驗證報告](docs/technical/utarldd_replay_validation_report.md)：演算法、品質、驗證方式與限制。
- [REA 分析與改善報告](docs/reviews/2026-10-22-rea-report.md)：本次以實際產物及程式證據檢查的範圍、發現、修正與未驗證項目。

歷史文件可能描述當時的 UI 或實驗流程；目前行為以原始碼、測試與對應版本的驗證紀錄為準。離線回測的標籤關聯結果，仍需以不同使用者、光線、相機與實際操作情境確認外部有效性。
