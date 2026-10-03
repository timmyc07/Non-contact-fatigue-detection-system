# 五平台系統分割實作計畫

## 目標與不可退讓條件

本計畫把系統整理成 Windows、macOS、Linux、Android、iOS 五個平台邊界，同時保留一份共用的分析契約與數值核心。平台分割的目的，是讓相機、權限、程序生命週期、檔案路徑、封裝與裝置能力可以獨立演進；不是複製五份疲勞或 rPPG 演算法。

以下條件在每一階段都成立：

- 不修改 `gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、`rppg/` 的既有數值公式、門檻、ROI、濾波、校準與融合權重，除非另立數值變更任務。
- 每個平台都使用明確的 capability contract；不以 `sys.platform` 判斷散落在分析邏輯中。
- 桌面平台的 Python/MediaPipe engine、`.venv`、PyInstaller sidecar 與 Tauri/Rust 產物，必須在目標平台原生建立。
- Android/iOS 在宣稱可運行前，必須有對應原生 runtime、相機權限、模型載入、背景/前景生命週期與實機驗收；目前 Flutter 專案只有 Web/Tauri 桌面入口，不能把手機平台標成已完成。
- 每次跨平台搬移都用同一組 replay/golden 輸入比對輸出，並記錄容差、失敗原因與硬體限制。

## 目標架構

```text
shared/
  analysis contract + replay/golden fixtures + serializable metrics
  Python numerical core (desktop engine)
  Dart UI/domain models
platforms/
  windows/  macos/  linux/  android/  ios/
  camera, permissions, storage, process/runtime, packaging policy
desktop shell
  Tauri v2 + Flutter Web -> Python engine sidecar
mobile shell
  Flutter Android/iOS -> native on-device inference adapter
```

共用層只定義資料格式、分析輸入輸出與可重現驗證；平台層負責裝置能力。桌面 Python engine 不會被包進 Android/iOS，手機端要以 Flutter plugin 或原生 Kotlin/Swift runtime 實作同一份契約。

## 分階段工作

### Phase 0：基線與現況盤點（已具備，持續維護）

- 固定 MediaPipe `0.10.35` 與唯一 `opencv-contrib-python 5.0.0.93`。
- 以 `scripts.video_replay`、既有 pytest 與 UTA-RLDD golden 建立目前輸出基線。
- 保留 `gui/platforms/{windows,macos,linux}.py` 的硬體 policy；確認數值模組不依賴平台模組。

### Phase 1：共用契約與平台註冊（本次開始）

- 建立單一平台清單、能力名稱、runtime 類型與 artifact 類型的機械可驗證契約。
- 將 desktop/mobile 的能力差異集中在 registry，讓啟動、測試與文件能使用同一來源。
- 為 Windows/macOS/Linux 建立既有 runtime 的正式註冊；Android/iOS 註冊為 `planned`，直到原生 runtime 完成前明確拒絕 desktop engine 啟動。
- 新增契約測試，確保五平台都有定義、能力名稱不漂移、數值核心不匯入平台 UI/原生 adapter。

### Phase 2：桌面三平台封裝隔離（進行中）

- 將 Windows NSIS、macOS App/DMG、Linux AppImage/deb（或選定的 Tauri target）分別放入平台建置設定。
- Linux 已建立 AppImage/deb Tauri 設定與 Ubuntu 啟動/建置腳本；Linux 原生建置與安裝後 smoke 尚待目標設備驗收。
- 每個平台原生建立 sidecar、模型資源與設定資料目錄；加入安裝後 smoke、啟動/停止/相機/解除安裝驗收。
- macOS 作為主要開發與驗收平台，先完成相機、BLE、Overlay、休眠/喚醒與權限流程。

### Phase 3：行動共用資料契約

- 將 Flutter UI 使用的 metrics、control state、錯誤碼與 recording metadata 抽成 platform-neutral Dart models。
- 明確標示手機不提供的桌面能力（Tauri external shell、全域快捷鍵、Python sidecar、桌面 Overlay），以 capability gating 隱藏或替代 UI。
- 建立 Android/iOS plugin interface：camera frames、permission、model lifecycle、foreground state、local storage。

### Phase 4：Android 原生 runtime

- 使用 Android 原生相機與 MediaPipe Tasks/可驗證等價 runtime；在裝置上完成模型載入、前景服務/生命週期與權限。
- 以同一 replay 片段比對 landmark、EAR/PERCLOS、rPPG BPM/quality 與 fatigue state；超出基線容差時停止移植並修正。
- 產出 signed/unsigned APK 測試包、安裝/升級/解除安裝 smoke 與硬體矩陣。

### Phase 5：iOS 原生 runtime

- 使用 AVFoundation 與 MediaPipe Tasks/可驗證等價 runtime；處理 camera permission、background interruption、memory pressure 與 app lifecycle。
- 在 macOS 上以實機與 simulator 分開驗證；產出 development IPA/TestFlight-ready archive（簽署由使用者帳號完成）。
- 同樣執行 replay/golden 數值比對與長時間穩定性測試。

### Phase 6：五平台 release gate

- `pytest -q`、`compileall`、`pip check`、Flutter analyze/test 與平台契約測試全數通過。
- macOS 作為主驗收機：source、bundle、camera、BLE、replay、shutdown、權限與資料遷移。
- Windows/Linux 執行各自原生建置與 smoke；Android/iOS 以實機安裝包執行 cold start、permission、camera、metrics、停止、升級與資料保留。
- 任何平台缺少原生 runtime、簽署或硬體驗證時，報告標記為未完成，不以資料夾存在取代支援。

## 驗收矩陣

| 平台 | 目前狀態 | 目標 artifact | 必測項目 |
|---|---|---|---|
| Windows | desktop runtime 已有 | NSIS installer | sidecar、WebView、相機 DSHOW/MSMF、停止、解除安裝 |
| macOS | desktop runtime 已有，主測試平台 | App/DMG | AVFoundation、MediaPipe CPU、BLE、Overlay、休眠喚醒、資料目錄 |
| Linux | engine/runtime policy 已有；封裝設定已建立，原生驗收待完成 | AppImage、deb | Ubuntu 原生 build、V4L2、Qt/xcb、相機、停止、資料目錄 |
| Android | 原生 runtime 尚未完成 | APK/AAB | permission、camera lifecycle、on-device inference、低記憶體 |
| iOS | 原生 runtime 尚未完成 | IPA/archive | permission、AVFoundation、interruptions、signing、memory pressure |

## 精度與回退策略

桌面目前輸出作為 baseline。平台 adapter 只能改變 frame acquisition、timestamp、權限與資源管理；若輸入 frame 或 runtime 造成結果差異，必須在報告中量化，不得用調整門檻掩蓋差異。手機 runtime 在能力不足時採 fail-closed：明確回報不可用並保留最後有效狀態，不偽造 BPM、疲勞分數或警報。

## 交付與版本控制

每一階段以獨立 commit 推送；commit 內容只包含該階段的程式、測試、文件與可重現命令。二進位安裝包不直接納入 git，改由 CI/release artifact 保存。每次交付回報修改檔案、測試命令、平台限制、數值行為影響與尚未完成項目。
