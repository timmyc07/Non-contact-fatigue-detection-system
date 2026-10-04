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

### Phase 1：共用契約與平台註冊（核心實作已完成）

- 建立單一平台清單、能力名稱、runtime 類型與 artifact 類型的機械可驗證契約。
- 將 desktop/mobile 的能力差異集中在 registry，讓啟動、測試與文件能使用同一來源。
- 為 Windows/macOS/Linux 建立既有 runtime 的正式註冊；Android/iOS 註冊為 `planned`，直到原生 runtime 完成前明確拒絕 desktop engine 啟動。
- 新增契約測試，確保五平台都有定義、能力名稱不漂移、數值核心不匯入平台 UI/原生 adapter。

已完成：`gui/platforms/registry.py` 定義 Windows/macOS/Linux/Android/iOS 五平台 runtime、能力與 artifact；Android/iOS 標記 `planned`，desktop engine 啟動採 fail-closed。`tests/test_platform_runtime.py` 覆蓋五平台登錄、能力名稱與行動平台拒絕 desktop engine。Flutter 端也已建立對應的 `PlatformCapabilities` 型別與契約測試。桌面能力是否在目標設備可用，仍以 Phase 2/6 的原生驗收為準。

### Phase 2：桌面三平台封裝隔離（可交付實作與 macOS 驗收完成；跨主機驗收待補）

- 將 Windows NSIS、macOS App/DMG、Linux AppImage/deb（或選定的 Tauri target）分別放入平台建置設定。
- Linux 已建立 AppImage/deb Tauri 設定、Ubuntu 啟動/建置腳本與 AppImage 安裝後 smoke；Linux 原生建置、安裝後 smoke 與相機流程仍待目標設備驗收。
- 每個平台原生建立 sidecar、模型資源與設定資料目錄；各平台都已提供安裝後 smoke 入口，實際啟動、相機選取、live metrics、停止與（Windows）解除安裝仍須在目標主機驗收。
- macOS 作為主要開發與驗收平台，本輪已完成相機與封裝生命週期驗證；BLE、Overlay、休眠/喚醒與權限流程仍待對應硬體／作業系統情境驗收。

已具備 Windows NSIS、macOS App/DMG、Linux AppImage/deb 的平台 Tauri 設定與各平台 sidecar/build 啟動流程；Windows、macOS、Linux 各有對應的安裝 smoke 入口。三個 smoke 入口都定義 API v2、相機選取、raw camera pipeline live metrics 與停止的檢查；Windows 額外定義隔離安裝、主視窗與靜默解除安裝，Linux 支援 `APPIMAGE_EXTRACT_AND_RUN=1` 與 Tauri data directory 檢查。macOS 已在本機 Apple Silicon 完成 PyInstaller sidecar、Flutter Web release、Tauri `.app/.dmg` 建置，並通過 bundle codesign 檢查與 API v2／相機列舉／`app.shutdown`／非預設埠 smoke。`scripts/desktop_hardware_smoke.py` 現在也可直接以檔案路徑執行，raw 與 combined 相機驗收命令已在 macOS 重新跑通。Phase 2 的封裝實作與目前 macOS 可執行的驗收已完工；Windows/Linux 的新一輪原生 build、安裝與相機流程仍必須在各自目標主機完成，不能由 macOS 結果代替。

**Phase 2 結案狀態（2026-10-04）**

- **已完成：** 三平台 Tauri bundle 設定、sidecar/model/resource/data-directory 邊界、Windows NSIS、macOS App/DMG、Linux AppImage/deb 的建置與 smoke 入口；不涉及分析公式、門檻、ROI、濾波、校準或融合權重。
- **已驗收：** macOS Apple Silicon 的現有 release bundle 重新通過 packaged smoke：API version `2`、camera count `1`、camera `1280x720@30 FPS`、raw pipeline select/configure/start/live metrics/stop、資料目錄建立、`app.shutdown`、control port 釋放、shell exit code `0`；`codesign --verify --deep --strict` 與 `hdiutil imageinfo` 亦通過。
- **Windows VM 證據（2026-10-04）：** Parallels Windows 11 ARM64（Windows build `10.0.26200.9457`）內以 Windows x64 Python 3.12.10 建立專案 `.venv`；`pip check` 通過。於 VM 內以 `scripts/build_engine_sidecar.py` 原生執行 PyInstaller 6.22.3，產生 `dist/ncfd-engine/ncfd-engine.exe`（約 19.0 MB），並通過 `--runtime-preflight` 與 `--runtime-preflight-face-landmarker`；完整 Python 測試為 `806 passed, 2 skipped in 6.51s`。這證明 Windows x64 Python 相容層的 sidecar 打包、共用測試與 MediaPipe Face Landmarker 載入可行，但不是實體 Windows x64 驗收。
- **尚未完成：** Windows NSIS 與 Linux AppImage/deb 必須在 Windows／Ubuntu Linux 原生主機重新 build、安裝、啟動、相機、資料目錄、停止與解除安裝。這是 Phase 2 的跨主機驗收缺口，不以 macOS 交叉執行結果替代。
- **目前問題：** Windows VM 的 `Get-PnpDevice -Class Camera` 可列舉到 Parallels 暴露的「MacBook Pro Camera」（狀態 `OK`），但 VM 尚未完成 NSIS 安裝，因此不能把裝置列舉當成 packaged camera live-metrics 證據；VM 為 ARM64 主機上的 x64 相容層，也不能取代實體 Windows x64。Linux 原生主機、Windows NSIS 安裝/解除安裝與實體相機 smoke 仍待補；macOS BLE、Overlay、休眠/喚醒與權限情境也未納入 packaged smoke。Phase 4 Android、Phase 5 iOS 與 Phase 6 release gate 維持未開始。
- **結案判定：** Phase 2 的程式、封裝設定、可重現命令、測試與 macOS 可驗收範圍已完工；跨主機驗收保留為明確外部 blocker，待對應主機補證後才可宣稱五平台 Phase 2 全部驗收完成。

### Phase 3：行動共用資料契約（已完成；原生推論待 Phase 4/5）

- 將 Flutter UI 使用的 metrics、control state、錯誤碼與 recording metadata 抽成 platform-neutral Dart models。
- 明確標示手機不提供的桌面能力（Tauri external shell、全域快捷鍵、Python sidecar、桌面 Overlay），以 capability gating 隱藏或替代 UI。
- 建立 Android/iOS plugin interface：camera frames、permission、model lifecycle、foreground state、local storage。

本階段已完成共用資料契約：`PlatformCapabilities` 集中五平台 runtime/artifact/capability 描述，`MetricsSnapshot`、`ControlState`、`RecordingMetadata` 與 `ApiError` 保留未知欄位並提供 typed access；結構化錯誤對 malformed 欄位採 fail-closed，仍可 lossless 重序列化；既有 `Map<String, dynamic>` Flutter API 仍保留，避免桌面 UI 行為改變。桌面專屬能力（`tauri_shell`、`global_hotkey`、`python_sidecar`、`desktop_overlay`）集中在 capability registry，行動平台自動 gating。

`MobileRuntimeChannelAdapter` 已以 `MethodChannel`/`EventChannel` 接上 permission、camera start/stop、model load/unload、foreground state、local storage 與 camera frame metadata；channel 名稱、method/event 名稱與 enum 序列化集中在 `MobileRuntimeChannelContract`。`createMobileRuntime` 只對 Android/iOS 建立 channel adapter，desktop/unsupported platform 維持 `UnsupportedMobileRuntimeAdapter`，plugin 缺失或 native 回報 unavailable 時 fail-closed，絕不回退到 Python desktop engine。

`flutter_app/native/mobile_runtime/android/MobileRuntimePlugin.kt` 與 `ios/MobileRuntimePlugin.swift` 已提供同一契約的原生 channel stub；stub 可處理 foreground/local storage，camera、permission 與 model inference 以 `runtime_unavailable` 回報。Android runner 現已建立：Gradle main source set 直接編譯 canonical Kotlin stub，`MainActivity.configureFlutterEngine` 將 plugin 加入 Flutter engine registry，不複製第二份 Kotlin source。此接線讓 Phase 3 channel 可由 runner 呼叫，但不代表 Android runtime 可運行；camera frame、MediaPipe/model inference、真實權限流程與裝置驗收屬 Phase 4。iOS runner 與實機驗收仍未開始。

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

## 目前進度（2026-10-04）

- **已完成：** Phase 0 基線與桌面平台 policy；Phase 1 五平台 registry、行動平台 fail-closed 與契約測試；Phase 3 共用 Dart models、capability gating、`MobileRuntimeAdapter`、`MethodChannel`/`EventChannel` adapter 與 Android Kotlin/iOS Swift channel stub。`ApiError` 也已完成未知欄位保留、typed parsing 與 lossless `toJson()`；既有 Flutter Map API 保留。
- **已完成：** Phase 2 的三平台封裝隔離實作與本機 macOS 驗證。Windows NSIS、macOS App/DMG、Linux AppImage/deb 的 Tauri 設定、sidecar/model/resource/data-directory 邊界、build/start 腳本與安裝 smoke 入口均已具備；新增 Linux AppImage smoke，並修正 macOS／Windows／硬體 smoke 可直接以檔案路徑執行及使用指定 backend port。2026-10-04 在 macOS Apple Silicon 重新完成 sidecar、Flutter Web release、Tauri `.app/.dmg` 原生建置；packaged smoke 通過 API version `2`、camera count `1`、raw camera pipeline start/metrics/stop、app data directory 建立、engine shutdown、backend port release 與 shell exit code `0`，bundle 也通過 `codesign --verify --deep --strict`，DMG 通過 `hdiutil imageinfo` 檢查。內建相機 raw 與 combined source-engine smoke 均通過，兩份結果保存於 `docs/benchmarks/desktop-hardware-smoke-2026-10-04-macos-raw.json` 與 `docs/benchmarks/desktop-hardware-smoke-2026-10-04-macos-combined.json`。
- **待外部主機驗收：** Windows NSIS 與 Linux AppImage/deb 尚未在 Windows／Ubuntu Linux 原生主機重新建置、安裝、啟動、相機、資料目錄與解除安裝；目前主機為 macOS arm64，不能以跨平台產物或 macOS 結果宣稱通過。macOS 的 BLE、Overlay、休眠/喚醒與相機權限仍屬硬體／作業系統情境測試，未納入本輪 packaged smoke。
- **Windows VM 補充證據：** Parallels Windows 11 ARM64 已完成 x64 Python/MediaPipe 環境的依賴檢查、PyInstaller sidecar build 與兩項 packaged runtime preflight；完整 Python 測試也已通過。工具鏈檢查顯示 VM 尚無可用的 Node/npm、Flutter、Rust/cargo 或 NSIS，背景 `winget` 安裝未完成，因此本輪不能在 VM 產生 Tauri/NSIS bundle。相機裝置只能證明 VM 的裝置列舉；Windows 的 installer、WebView2、主視窗、停止、資料目錄、解除安裝與 live camera metrics 仍標記未驗收。
- **未完成：** Android/iOS 真實相機權限與影格串流、MediaPipe/model inference、原生 app runner 建置簽署與裝置驗收；Phase 6 五平台 release gate。不得將 Android/iOS 標示為可運行。
- **目前問題：** Windows/Linux 原生驗收受限於目前工作主機沒有對應作業系統與硬體；macOS build 的 Flutter Wasm dry-run、MaterialIcons 與 notarization 會顯示非阻斷警告，正式 `.app/.dmg` 仍可建立並已通過 adhoc codesign verify。Android runner 的 plugin source-set 與 registration 已完成程式接線，但本機缺 Android SDK 與 Java runtime，`flutter build apk --debug` 因此無法進入 Gradle/Kotlin 編譯；尚未取得 APK build、模擬器或 Android 裝置驗收證據。iOS runner 尚未接線，Phase 4/5 runtime 仍以 `runtime_unavailable` 阻止誤啟動，不是 desktop fallback。
- **本輪實際驗證：** Phase 2 相關 Python 測試 `64 passed`，完整 Python 測試 `806 passed, 2 skipped`；Windows VM 重新執行完整 pytest，結果為 `806 passed, 2 skipped in 6.51s`。Flutter `43` 項測試通過、`flutter analyze` 無問題；受影響 scripts/gui/platforms 的 `compileall`、`pip check`、四份 bundle JSON parse、build/start shell syntax check 均通過；Tauri Rust `cargo test` 為 `13 passed`。macOS packaged smoke 通過 API version `2`、camera count `1`、`1280x720@30 FPS` raw camera pipeline select/configure/start/metrics/stop、data directory、engine shutdown、backend port release 與 shell exit code `0`；`codesign --verify --deep --strict` 與 `hdiutil imageinfo` 亦通過。source-engine raw 與 combined 相機 smoke 結果仍保存於 `docs/benchmarks/desktop-hardware-smoke-2026-10-04-macos-raw.json` 與 `docs/benchmarks/desktop-hardware-smoke-2026-10-04-macos-combined.json`。
- **本輪更新：** 重新執行 Phase 2 相關測試、完整 Python 測試、Flutter test/analyze、Rust tests、compileall、pip check、bundle JSON 與 shell syntax 檢查，並重新跑 macOS packaged smoke。另以 Flutter 3.47.2/Dart 3.13.2 正式產生 Android runner scaffold，接通 Phase 3 Kotlin channel stub 的 Gradle source set 與 engine plugin registry；Flutter analyze 無問題、43 項測試通過，但因缺 Android SDK/Java，APK build 未能驗證。沒有新增跨平台數值邏輯，也沒有開始 Phase 4；iOS 原生 runner、Android camera/inference 與行動裝置驗收仍未完成。
- **數值行為影響：** 本輪只更新驗收紀錄與文件，沒有修改分析公式、門檻、ROI、濾波、校準或 worker 數值路徑。

### 技術與文獻查證（2026-10-04）

本輪在更新驗收敘述前，以官方文件、原始論文與可追溯索引交叉核對；這些資料用來確認平台邊界與既有方法的適用範圍，沒有據此改動疲勞、rPPG、ROI、濾波、校準、門檻或融合權重。

- **臉部特徵與模型資源：** Google MediaPipe Face Landmarker 官方文件（<https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker>）確認桌面端可用 Tasks Vision 的 Face Landmarker 與模型資源；本專案採固定模型檔與 packaged preflight，未把模型載入成功誤當成相機或整體 UI 驗收。
- **相機 I/O：** OpenCV `VideoCapture` API（<https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html>）確認 backend-specific capture 與裝置列舉的界線；Windows policy 保留 DSHOW/MSMF，live metrics 仍須在目標硬體上驗證。
- **Windows media stack：** Microsoft Media Foundation architecture（<https://learn.microsoft.com/en-us/windows/win32/medfound/media-foundation-architecture>）確認 Windows camera pipeline 由 media source/transform/sink 組成；因此 VM 的 camera device enumeration 不足以代表完整 capture pipeline。
- **桌面 WebView 與封裝：** Microsoft WebView2 distribution（<https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution>）與 Tauri v2 Windows installer（<https://v2.tauri.app/distribute/windows-installer/>）確認 Evergreen/固定 runtime 與 NSIS 安裝器是獨立驗收面；本計畫保留 WebView2、NSIS、安裝/解除安裝 smoke 為 Windows 未完成項。
- **Sidecar 邊界：** PyInstaller operating modes（<https://pyinstaller.org/en/stable/operating-mode.html>）確認產物須在目標 OS/架構建立，故本輪記錄為 Windows ARM64 主機上的 x64 Python 相容層 build，不宣稱實體 x64 原生等價。
- **Flutter 平台邊界：** Flutter platform integration（<https://docs.flutter.dev/platform-integration>）支持以 platform channel/native adapter 分隔桌面與行動 runtime；Android/iOS 仍維持 `planned`/`runtime_unavailable`，不以桌面 sidecar 代替。
- **Android runner 接線：** Flutter `FlutterActivity.configureFlutterEngine` 與 `FlutterEngine` plugin registry API（<https://api.flutter.dev/javadoc/io/flutter/embedding/android/FlutterActivity.html>、<https://api.flutter.dev/javadoc/io/flutter/embedding/engine/FlutterEngine.html>、<https://api.flutter.dev/javadoc/io/flutter/embedding/engine/plugins/PluginRegistry.html>）確認 host activity 可在 engine 初始化時以 `has()` 防重複並註冊實作 `FlutterPlugin` 的 plugin；Android Gradle source set 官方文件（<https://developer.android.com/build/build-variants#sourcesets>）確認 app 可納入位於預設目錄以外的 Kotlin/Java source。Gradle Wrapper 官方文件（<https://docs.gradle.org/current/userguide/gradle_wrapper.html>）要求 wrapper files 納入版本控制，故納入 wrapper script/JAR 與指定 Gradle distribution。據此採用 Gradle `java.srcDir` 指向唯一 Kotlin stub，並由 `MainActivity` 註冊；目前因缺 SDK/Java 未完成原生編譯驗證。
- **rPPG 方法交叉核對：** de Haan & Jeanne 的 CHROM（DOI <https://doi.org/10.1109/TBME.2013.2266196>；IEEE <https://ieeexplore.ieee.org/document/6523142/>）、Wang et al. 的 POS（DOI <https://doi.org/10.1109/TBME.2016.2609282>；IEEE <https://ieeexplore.ieee.org/document/7565547/>）與 Chen & McDuff 的 DeepPhys（ECCV Workshops DOI <https://doi.org/10.1007/978-3-030-01216-8_22>；Springer <https://link.springer.com/chapter/10.1007/978-3-030-01216-8_22>）均將攝影機影像中的生理訊號抽取視為受光照、動作與資料品質影響的方法；本專案僅保留既有 POS/ROI/quality pipeline，沒有把論文結果直接當作本專案門檻保證。

**採用技術清單：** Tauri v2 + Flutter Web（桌面 UI）、Python 3.12 + PyInstaller onedir（engine sidecar）、MediaPipe Face Landmarker（臉部 landmarks/blendshapes）、OpenCV Video I/O（相機）、Windows DSHOW/MSMF policy、WebView2 distribution、NSIS installer、MethodChannel/EventChannel（行動 plugin contract）、Android Gradle Kotlin source set + Flutter `FlutterPlugin` registry 接線，以及既有 POS/CHROM 研究脈絡下的 rPPG pipeline。Android/iOS 的原生 inference、release signing 與實機驗收不在本輪宣稱完成範圍。

### Phase 2 後續工作順序（不延伸到行動平台）

1. 在 Windows 目標主機執行 NSIS 原生 build、安裝 smoke 與解除安裝驗收，記錄 OS/硬體/命令/結果。
2. 在 Ubuntu/Linux 目標主機執行 AppImage/deb 原生 build、安裝後啟停、相機與資料目錄 smoke，記錄 OS/硬體/命令/結果。
3. 依驗收矩陣補齊 macOS BLE、Overlay、休眠/喚醒與相機權限的硬體／OS 情境紀錄；上述外部驗收完成前，Phase 2 維持「實作完成、跨主機驗收待補」。
4. Phase 4 Android、Phase 5 iOS 與 Phase 6 五平台 release gate 不在本輪範圍，維持未開始／未完成標記。
