# REA 封裝分析與改善報告

日期：2026-10-22（Asia/Taipei）。本報告檢查本機已有的 Flutter Web 編譯產物與 macOS 封裝，再以原始碼交叉核對，將可重現的發現落實為小範圍修正。這是軟體交付與資源邊界檢查，沒有執行應用程式、啟動相機或量測疲勞判讀效能。

## 結論與完成範圍

已找到並處理三項實際交付問題：圖片退出版本控制後缺少重建入口、兩處模型下載使用未固定且未校驗的 `latest`、桌面前端雖攜帶 CanvasKit 卻仍使用 CDN 預設。另將已移除舊 dashboard 的根路由改為診斷 JSON，消除懸空的 template 相依。既有演算法、ROI、校準公式與疲勞閾值維持原樣。

本輪 REA **部分覆蓋**系統：已完成封裝身份、macOS 靜態 metadata／簽章及前端載入資源檢查；沒有完成 `main.dart.js` 的完整語意還原，也沒有反編譯 Python sidecar 或原生控制流程。舊 `.app` 不能作為本次修正已完成封裝驗收的證明。

| 調查問題 | 狀態 | 證據與界線 |
| --- | --- | --- |
| 現有產物是什麼版本、平台與身份？ | 已回答 | 舊產物檔案修改時間、SHA-256、Info.plist、Mach-O；修改時間不是可信建置證明 |
| 圖片／模型取消追蹤後是否仍能準備必要資源？ | 已回答 | 原始碼交叉核對；本機資產 helper 與隔離測試 |
| 桌面 CanvasKit 是否仍採 CDN 預設？ | 已回答並修正 | 舊 bootstrap、Flutter 官方實作、新 buildConfig 與本機 JS／WASM 檔案 |
| 桌面／engine 的控制與資料邊界是否存在？ | 部分回答 | 原始碼確認 localhost control、release sidecar、唯讀資源／可寫資料分離；沒有 runtime 流量或原生反編譯驗證 |
| 相機權限與 macOS 支援條件是否在包內？ | 靜態部分已回答 | arm64、最低 macOS 15.0、相機／Bluetooth 宣告；未測 OS 授權結果 |
| 整套產品完全離線、安裝簽章可信且演算法準確？ | 未驗證 | 無斷網啟動、Gatekeeper／notarization、真實攝影機、BLE 或數值效能量測 |

## 方法與產物身份

遵循 REA staged workflow：先建立問題清單、檢查目前 session 與既有 Evidence，再以 summary-first 分析選定產物，讀取必要 module／Mach-O 頁面，最後匯出證據並關閉原生目標。REA 為 `rea-agents 6.7.0`，技能版本 `42`；起始 session 無開啟目標、無既有 Evidence。Ghidra／Java 未配置，因此使用已提供的 macOS 靜態工具，未安裝其他反編譯引擎。

分析開始時 repository HEAD 為 `15c1f42`。既有 Web、shell、engine 的檔案修改時間為 **2026-10-05 11:17–11:19 +08:00**；本次新 Web build 為 **2026-10-22**。這些是本機產物，不是已核實發行版本；原 `.app` 未重建。

| 對象 | SHA-256 | 說明 |
| --- | --- | --- |
| 原 Web 目錄 REA inventory identity | `93175fb52e6495ae1fba73bd84aad1e4fe0b030715bc479e13a3095e5e69a0bf` | 目錄 inventory 身份，不是單一檔案雜湊 |
| 原 `main.dart.js` | `788fc58ad9e1be1915f9998559226c3e1bf967d402aea5dcec292a99f7b06bf2` | 2,865,090 bytes |
| 原 `flutter_bootstrap.js` | `0761109653d99607c017e02e2cb703ce0d3c0b5446d7d0d7081cb1a6ceca2123` | 13,094 bytes |
| `.app/Contents/MacOS/fatigue-monitor-shell` | `47ce8f8847274b4a8476f70c7da51263e30577f736588d73097b449821b89b5a` | arm64，23,821,696 bytes |
| `.app/Contents/Resources/engine/ncfd-engine` | `7f22c683af62766a8aef0e6e9dead5a1fcda2aca3567780051d27c37af8f6b44` | 19,556,704 bytes；僅計算身份，沒有執行／反編譯 |
| `.app/Contents/Info.plist` | `a117e237cfd3511ca5aa9d7eebdea63b6aa42d22f92afa3ec605c65df0299ceb` | bundle 0.1.0、最低 macOS 15.0 |
| 包內 `face_landmarker.task` | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | 3,758,596 bytes；與固定下載版本的預期雜湊一致 |
| 包內與 checkout 的 `mediapipe_tuning.json` | `a67c1c255283f07c3d074fe62aba6102e4957fa6ccc07f705c4e6aa80883ab40` | 兩份 bytes 相同，不能由此推定整個 engine 與 source 等價 |
| 新 Web 目錄 REA inventory identity | `86880b346fc95cf938184914897009f3fa55b07ea4429003e6b57bb788ea3f61` | 本次以本機 CanvasKit 建置 |
| 新 `flutter_bootstrap.js` | `769a58fb284d5cbc7a65043354fbbfb9bc02b0b5a3a3dbe45d8261608bab9567` | buildConfig 的 `useLocalCanvasKit=true` |
| 新 `main.dart.js` | `3537f75a31413fcf6107d3b3c50054d7cdcb844bab0fd76133b462ed50d6760a` | 2,865,017 bytes；沒有重試完整語意分析 |

完整機器輸出僅存本機 `output/rea/`，不納入版本控制：

- `2026-10-22-before-evidence.json`：12 筆 REA records，3,708,762 bytes；SHA-256 `19388c6f3e617ac37724c64ea888ae06520076f72e5ab496edb98f3803df06e0`。
- `2026-10-22-evidence.json`：關閉原生 session 後的新 Web 分析，2 筆 records，3,214,058 bytes；SHA-256 `1f1b95684f894a5f6c717201631927b981312bae557c919b188017ff629b70ca`。
- `2026-10-22-selected-artifacts.json`、`2026-10-22-after-web-artifacts.json`：自行量測的選定檔案雜湊、修改時間與建置命令。這些是補充量測，並非 REA Evidence ID。

## Evidence ledger 與 coverage

| Evidence ID | Provider／操作 | 支持範圍與限制 |
| --- | --- | --- |
| `ev_51aa1a9fd178070517d11fcfd13be93d4c293dc72b74198cadc273e12c803f33` | `rea-javascript-application` v1／原 Web static analysis | 6 個選定路徑、14 個 relevant files；另 8 檔不在 source analysis 範圍。bootstrap／service worker 可解析；`main.dart.js` 超過約 1 GiB worker heap 而跳過。application／semantic graph 均 partial；9 個 application unknown、722 個 semantic unknown |
| `ev_934de0bd9a841f1f6164bd35ca770680a1144de76c69bc98c6e5c42ad866cf66` | `rea-analysis-view` v1／bootstrap source module | 原 bootstrap 的身份、雜湊、AST source range；靜態分析沒有執行 loader |
| `ev_7b3bd19a21577c02020e330678a366f8e1fca12f55db9d6224c48084405c6193` | `native-macos`／Mach-O | arm64、64-bit、13 個 dylib dependencies、30 個 load commands；imports 298、exports 2,128，符號並非 exhaustive。沒有函式反編譯或執行順序證據 |
| `ev_58c7102a0b43eee961eaa52701e1f97afc295dd31e71836dc5d70714b52772ac` | `rea-analysis-view` v1／Mach-O build metadata | 最低 macOS 15.0、SDK 26.5、LD 1267.0；只代表 metadata |
| `ev_d049605fa015af8c0142d7206c5e2f02edc8e92ea2355d62a545f06aa81d397e` | `native-macos`／plist | bundle identifier／version 與相機、Bluetooth 用途宣告；plist 另以自身 SHA-256 留存身份 |
| `ev_f3a11682422e36fa401f29f2dd17b77f07e08d363830def76977949b3312dd70` | `native-macos`／signature | signed、hardened runtime、camera／Bluetooth entitlement；無 team identifier、authority 或 timestamp。僅檢查已核對雜湊的 executable snapshot，未驗 filesystem trust 或 notarization |
| `ev_fd2d05479fae732a14f3b74e19520aa2593b773089179e7e7e956d0274086264` | `rust-auditable` v1／Rust metadata | 找不到 `.dep-v0`，不能宣稱沒有 Rust dependencies；compiler path 內 hash 只能作 inference |
| `ev_293b67c13cc280685deb9ba8adcc0afff61cff304ea8d71db820e15517c39301` | `rea-javascript-application` v1／新 Web static analysis | 5 個選定路徑，兩個 JS 皆解析成功；包含 main 在內的 9 個 inventoried sources 不在 source analysis 範圍，coverage 仍 partial。沒有以縮小範圍宣稱全 application 完整分析 |

`inspect_analysis_view` 的 `complete-within-view` 只代表該頁／summary 的投影已交付，不代表 application、符號、控制流程或執行行為完整。匯出 bundle 的 `unknowns` ledger 與 graph 內的 unknown 計數不同，不能混用。

## 發現、修正與證據層次

### 1. 本機資產必須有可重現的準備流程

**Source corroboration：**Tauri config 列出 PNG、ICNS、ICO，Android manifest 依賴 launcher 圖示；PyInstaller 明確需要 model 與 tuning。原本直接依賴 tracked 圖片／模型的檔案存在，取消追蹤後新 checkout 無法自行補齊。

**已落實：**`scripts/prepare_local_assets.py` 以已安裝 Pillow 補齊本機桌面 6 個與 Android 5 個圖示，只建立缺檔並保留既有自訂圖；初次手動準備時需明確指定 `--download-model` 才下載模型。sidecar build 先準備圖示，缺模型時回報缺失資源路徑，首頁提供準備命令；測試改在臨時目錄建立圖示，避免將測試綁定本機忽略檔。圖像、模型、個人設定與產出物均留在本機，公開文件保留導覽與重建命令。

**限制：**helper 不會補回已移除的歷史截圖，也不覆寫既有自訂資產；重新產生的預設圖示不是原設計圖的像素還原。

### 2. 模型下載來源與完整性應固定

**Source corroboration：**原 `rppg/rppg_worker.py` 與 `rppg/demo_rppg_live.py` 均從 `float16/latest` 直接 `urlretrieve` 到正式檔案，既有判定僅檢查檔案大小。這無法固定未來下載的 bytes，傳輸中斷也可能留下不完整檔案。

**Artifact observation：**舊 `.app` 的模型雜湊為 `64184e…c9ff`，與此次選定的官方 `float16/1` 預期雜湊一致；包內 metadata 宣告 MediaPipe 0.10.35 與 opencv-contrib-python 5.0.0.93。metadata 宣告本身不等於執行時載入驗證。

**已落實：**集中到 `gui/model_assets.py`：固定官方版本、30 秒 timeout、新下載內容 SHA-256 驗證，完整寫入同目錄 temporary file、`fsync` 後再 `os.replace`。worker、demo 與手動資產準備共用此路徑；失敗保留舊檔並清除暫存。worker 原有「模型缺失時下載」的 runtime fallback 保留，沒有新增啟動時自動更新模型的行為。

**數值行為：**新下載固定到與既有封裝相同的模型 bytes；既有足夠大小的自訂模型仍保留原行為，沒有強制覆寫或改變分析公式。這不是對任意既有模型的完整性稽核。

### 3. 攜帶的 CanvasKit 應由本機載入

**Artifact observation：**原 bootstrap 的 buildConfig 未設定 `useLocalCanvasKit`，但 `canvaskit/` 的 JS／WASM 已存在。直接讀取原 loader 與本機 Flutter 官方原始碼，發現它會在有 engine revision 且未要求 local CanvasKit 時選擇 Google CDN。這是靜態分支觀察，沒有捕捉實際下載流量。

**已落實：**在 `src-tauri/tauri.conf.json` 與 `tauri.macos.conf.json` 的兩個正式 Web build 入口加入 Flutter 既有旗標 `--no-web-resources-cdn`。其餘平台 scripts 透過 Tauri build 使用這兩個入口，因此無需額外 bootstrap、包裝層或依賴。

**新產物驗證：**Flutter 3.47.2 release build 成功；解析新 bootstrap 的 buildConfig，確認 `useLocalCanvasKit=true`；一般與 Chromium CanvasKit 的 JS／WASM 均為非空本機檔案。新產物另存獨立 REA Evidence，未與原 `.app` 混為同一版本。

**限制：**未實測 Webview 斷網啟動；fallback 字型、首次安裝、模型準備與其他選用網路功能仍須各自確認，因此沒有宣稱整個產品完全離線，也沒有移除仍有用途的 CSP 字型來源。

官方交叉核對：[Flutter build_web.dart](https://github.com/flutter/flutter/blob/master/packages/flutter_tools/lib/src/commands/build_web.dart)、[Flutter CanvasKit URL 選擇](https://github.com/flutter/flutter/blob/master/engine/src/flutter/lib/web_ui/flutter_js/src/utils.js)、[Flutter Web 初始化文件](https://docs.flutter.dev/platform-integration/web/initialization)。本機 CLI help 與實際 build 同時確認旗標可用，未只依賴上游 master 的版本推定。

### 4. 移除可見舊頁後，同步清除懸空入口

**Source corroboration：**`gui/web_ui/templates/dashboard.html` 已刪除，但 Flask `/` 原本仍 `render_template`，會使本機或 LAN 診斷入口要求不存在的檔案。

**已落實：**`gui/web_server.py` 的根路由回傳 engine 診斷 JSON，標示正式介面為 Tauri + Flutter 並提供 metrics API 路徑；移除 render_template 相依與空 templates 資源路徑，保留 API、LAN token 檢查及 Socket.IO。沒有重建已淘汰的可見 dashboard。

### 5. 已存在的控制邊界與交付限制

**Source corroboration：**`spawn_backend` 保持 debug 使用 checkout、release 使用 bundled engine；`gui/runtime_paths.py` 分離 resource/data roots 並阻擋絕對路徑、`..` 與 symlink 逃逸；`/api/control/*` 檢查本機來源，Tauri 使用 API version readiness 判定；外部 shell 動作由 Tauri 驗證後派送。沒有為整理檔案而改動這些控制邊界。

**Observed／inference 分界：**Mach-O 顯示 AppKit／WebKit 相依，與 Tauri shell 設計一致；它沒有證明每個 source handler 都存在於舊包或在執行時可達。簽章內 camera／Bluetooth entitlement 與 source 設定一致；無 authority、team、timestamp，加上 source 的 `signingIdentity: "-"`，支持其為本機 ad-hoc 建置的判讀，不能當作公證或 Developer ID 發行證明。

**Unknown：**沒有完整 Rust dependency SBOM；沒有 Python sidecar 反編譯；沒有重新打包／驗收 Windows、Linux 或 macOS installer。這些保留為後續發行工作，沒有藉此擴充依賴或改寫偵測演算法。

## 版本庫整理與審查

圖片（含 SVG、桌面與 Android 圖示）、`AGENTS.md`、`CLAUDE.md`、模型與產生的 PDF／Office 文件已取消追蹤；仍存在的本機素材保留，缺失的必要圖示與模型可由準備工具補齊。更新 `.gitignore`，並新增 `scripts/check_repository_hygiene.py` 與 GitHub Actions，拒絕將被忽略的本機檔案強制納入 index。檢查只列檔名，不輸出機密內容。這次移除的是最新版本的檔案，沒有重寫舊 commit 歷史。

追蹤清單由 336 檔整理為 307 檔，移除 20 個圖片路徑；公開版本快照約由 9.12 MB 減為 3.45 MB。此為當前檔案內容大小，並非 Git 歷史或 clone 大小縮減的聲明。

產品首頁與詳細操作手冊分離；技術報告、歷史紀錄、規劃與審查分層，Canva 輔助工具移至 `tools/canva-flowchart/`。文件交叉路徑與 PDF 產生器同步更新，輸出留在本機 `docs/exports/`。Canva 工具改為由使用者選取本機圖片，不再在原始碼中匯入已取消追蹤的固定 PNG。

重量級變更的三個審查軸分別完成：官方工具／版本核對確認既有 Pillow 可寫入 ICNS 且 Tauri 圖示規格可重建；程式與部署審查找到模型下載、CDN 與已移除頁面入口的問題並修復；文件審查修正平台成熟度、舊 UI 措辭與 `pos_pulse` 的方法描述。沒有因此修改疲勞或 rPPG 數值公式。

## 驗證紀錄與剩餘限制

| 實際執行 | 結果 |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 823 passed、2 skipped；兩項略過為目前 macOS 不適用的 Windows rooted-relative 路徑測試 |
| 將暫存 tree 匯出至乾淨臨時 Git 副本再跑完整 pytest | 823 passed、2 skipped；事前確認沒有模型、圖示、AGENTS.md 或 CLAUDE.md，驗證不依賴本機忽略資產 |
| `.venv/bin/python -m compileall -q main.py gui rppg scripts tests`、`pip check`、`scripts.runtime_preflight` | 通過 |
| Flutter `test`、`analyze` | 43 項測試通過；analyze 無問題 |
| Canva `lint`、`lint:types`、production `build` | 通過；未新增依賴或真實上傳圖片 |
| `BROWSERSLIST_IGNORE_OLD_DATA=true npm test -- --runInBand`（Canva） | 2 suites、10 tests、1 snapshot 通過；原 server test 會將舊 Browserslist 資料的 stderr 警告當成失敗，故明確抑制該警告 |
| `scripts.check_repository_hygiene`、一般 token／private-key 樣式掃描、文件路徑及 JSON 解析 | 通過；樣式掃描不等於完整機密稽核，未輸出內容 |
| `cargo check --locked --manifest-path src-tauri/Cargo.toml` | 被既有 `dist/ncfd-engine/_internal/QtQmlModels` 失效連結阻擋；舊 sidecar 需重建才可作完整封裝驗收 |
| `TAURI_CONFIG='{"bundle":{"resources":[]}}' cargo check --locked --manifest-path src-tauri/Cargo.toml` | 通過；暫時排除舊 sidecar 僅確認 Rust shell／設定可編譯，沒有驗證 release 資源封裝 |
| `.venv/bin/python -m pytest tests/test_desktop_shell_config.py -q` | 17 passed |
| `.venv/bin/python -m compileall -q tests/test_desktop_shell_config.py` | 通過 |
| 資產／模型／sidecar／桌面 config／packaged consumers／Socket.IO 相關 6 個測試檔 | 57 passed；涵蓋錯誤 hash、下載中斷、發布失敗保留舊檔、自訂模型保留、圖示重建、無 template 診斷 JSON 與 LAN token |
| 上述變更的 Python `compileall`、sidecar JavaScript `node --check` | 通過 |
| Flutter `build web --help` 與本機官方 SDK source 檢查 | 確認 `--no-web-resources-cdn` 轉為 local CanvasKit buildConfig |
| `flutter build web --release --no-web-resources-cdn --dart-define=NCFD_BACKEND_URL=http://127.0.0.1:5055` | exit 0，13.3 秒，產生新 Web build |
| 新 bootstrap JSON／本機 CanvasKit JS 與 WASM assert | 通過，`useLocalCanvasKit=true` |
| REA 新 Web summary-first 靜態分析 | 兩個選定 JS 解析成功；有意保留部分 application coverage |
| 兩份 Tauri JSON、修改區段 read-back、`git diff --check` | 通過 |

Flutter build 同時回報既有 `socket_io_common` 的 WASM dry-run 相容性與 CupertinoIcons 字型警告；本次仍使用既有 dart2js target 並成功建置，沒有為消除警告修改依賴或聲稱 WASM target 可用。既有 sidecar 的失效連結不以建立假檔或修改正式資源設定掩蓋；完整原生安裝包需在重建 sidecar 後另作驗收。

Canva production build 仍有既有 webpack 體積警告（`app.js` 約 1.09 MiB）與 localhost backend 設定提示；未為本次資料整理調整依賴版本或發布設定。

數值行為影響聲明：未修改 rPPG、疲勞融合、濾波、ROI 權重、校準公式或閾值。模型變更限新下載的來源固定與安全發布，所選 bytes 與既有包內模型相同；前端修正為 CanvasKit 資源來源、診斷文案與 Canva 本機選圖。未啟動 app／相機／BLE；本機常用資料集位置無 UTA-RLDD，未執行 golden；亦未作斷網 runtime 驗收，因此不提供新的數值精度、硬體相容性或全離線保證。
