# 全系統優化追蹤

目標：針對這套程序，修復使用者尚未提出的優化問題。此目標仍在進行，不能以先前 ProMotion 修正或單一批測試宣稱全部完成。工作分支為 `codex/system-optimization`。

## 驗收原則

- 審查啟動／關閉、控制指令、相機與三種分析模式、BLE／校準、錄影與 SQLite、回放、HTTP／Socket.IO、Flutter 各頁／Overlay、原生視窗及封裝。
- 每項修改須有可重現案例或量測；先建立會失敗的回歸檢查，再修正並 read-back。
- 分析數值優化須證明原數值行為保持；涉及數值路徑時執行完整 pytest 與可取得的 golden／replay 比對，三軸審查。
- 保存使用者既有資料、機密、設定與未由代理造成的變更；`.env` 不納入提交。可選設定不塞進 `.env`。
- 驗證後逐批自動 commit／push。完成審查及所有已知缺陷的修正／必要實機驗證以前，目標保持 active。

## 已確認發現

| ID | 範圍 | 證據／影響 | 狀態 |
| --- | --- | --- | --- |
| O01 | Socket.IO 預覽回壓 | 1000 次 100KB 預覽使慢客戶端的無界 Engine.IO queue 累積約 100MB | 已修；各 SID／事件保留一筆待 ACK＋一筆最新 pending；可靠控制訊息保持 |
| O02 | SQLite 回放查詢 | GC 暫停時連續 100 次 full 查詢，FD 從 4 增至 104；transaction context 不會關閉連線 | 已修；同案例 FD 維持 4 |
| O03 | File Browser HTTP | 下載串流中途 OSError 後 response 未關閉 | 已修，失敗／成功均釋放 response |
| O04 | Metrics writer 初始化 | startup timeout 後晚到 writer 仍活著，stop_event 未設定 | 已修；逾時要求排空並退出 |
| O05 | 錄製收尾 | 主執行緒 close 可等待 15 秒，逾時仍清掉管理 reference，finalizing 狀態只看影片 | 已修資料庫非阻塞停止、保留 pending ownership、兩種完成順序推播 |
| O06 | FFmpeg 收尾 | wait 回傳非零未發 failed；timeout kill 後未 reap／告警 | 已修；真 FFmpeg 六幀錄製並讀回六幀 |
| O07 | 遠端快取隔離 | File Browser 僅按檔名取快取，切換站點後可回傳前站同名資料庫 | 已修，站點＋帳號雜湊隔離；切站／登出／下載互斥 |
| O08 | 無用指標歷史 | Socket 重連要求最多 301 筆歷史，但 Flutter 沒有消費 metrics_history | 已移除 Flutter 的無用請求，診斷事件仍保留 |
| O09 | Overlay 重複 HTTP | control state 已回覆，仍等待重複 metrics HTTP 才套用；最長延遲 12 秒 | 已移除重複 HTTP，沿用 socket／fallback 指標來源 |
| O10 | 隱藏 Overlay | 原生 hide 保留 WebView，計時器／socket／preview 訂閱仍工作 | 已修；明確原生 visibility 事件控制訂閱／timer／preview，真 native hide/show／無焦點驗證通過 |
| O11 | 原生冷啟動 | setup 同步等 Python readiness 最長 20 秒，阻塞原生事件迴圈 | 已修背景啟動與退出競態；Flutter 等 control API 成功再載 history，單飛與失敗重試 |
| O12 | 校準版本讀檔 | 同版本連續 300 次 getter 造成 300 次 JSON 讀檔 | 已修；變為 1 次，300 組合成指標與舊版相同 |
| O13 | ROI 候選歷史 | 相同 12 秒輸出，900 筆歷史約 0.188ms，100000 筆約 22.72ms | 已修順序資料尾端取窗；保留 100000 容量、任意長窗及亂序原遮罩 |
| O14 | 重複 GaussianBlur | 同幀四 ROI 重複 blur 約 1.747ms，共用約 1.008ms，初步逐 bit 相同 | 已修；相同全幀濾波重用，遮擋仍讀原圖，canonical 開／關對照相同 |
| O15 | 預覽標註時機 | 先標註才丟掉超過預覽更新率的影格；1080p 單次標註約 8.731ms | 已修；保留每幀 tracker 推進，只略過不輸出影格的像素標註 |
| O16 | BLE 歷史成本 | WatchHrHub 不斷 append，每次 snapshot 複製全歷史，physio 僅用 90 秒 | 待確認所有歷史消費契約後修正 |
| O17 | 無觀眾預覽 | 零 client 仍在主執行緒縮放／JPEG／base64 | 已修；零 client 不編碼、不更新節流時間，首 client 下一幀正常傳送 |
| O18 | 分析持續失敗 | MediaPipe 或整幀處理例外被無限略過，管線表面仍在運行 | 已修；連續 30 幀失敗退出並告警，成功幀重置計數 |
| O19 | heartbeat 重啟 | 舊 HTTP refresh 超過 join 期限後，新 start 清除共用 stop event，舊 thread 可復活 | 已修；每輪捕捉獨立停止事件 |
| O20 | FFmpeg 寫入堵塞 | encoder 不消費 stdin 時，request_stop 無法中斷 write／close | 已修；停止 watchdog 有界等待後只終止自身 encoder 並 reap，failed／finished 各一次 |
| O21 | 回放資源生命週期 | recorder／模型初始化在 try 外；close 逾時仍可能報 done；一個 cleanup 失敗會跳過其他資源 | 已修；初始化納入邊界、背景回放等待 writer 排空、各資源獨立釋放；7 項新回歸通過 |
| O22 | 影片停止等待 | Qt 控制指令仍可能 join video 2000ms，收尾慢時操作受阻 | 下一批；須同步調整原 fail-closed 停止契約 |
| O23 | 退出後備清理 | app.exec 返回後沒有 timer 再輪詢 pending metrics writer；main 忽略清理失敗 | 已修；事件迴圈外同步 drain 並回報不完整清理；其他 adapter 後備退出仍需檢查 |
| O24 | BLE 停止等待 | GUI 呼叫 stop_belt 最多同步等待背景 thread 5 秒 | 下一批；必須保留停止中 ownership 與禁止重啟的保護 |
| O25 | Web server 的 File Browser ownership | 合成登入後停止 server，heartbeat thread 仍活著且仍保留登入；未觸碰外網 | 下一批；server 背景收尾須明確釋放 FileBrowserClient，避免 Qt 等待 HTTP |
| O26 | 封裝啟動字型快取 | PyInstaller 6.22.2 runtime hook 每次建立臨時 MPLCONFIGDIR，兩次 packaged preflight 均重建 cache，耗時 8.359／7.931 秒 | 下一批對照並修正；本次皆 exit 0，未宣稱全部延遲都由字型快取造成 |

## 本批驗證與數值影響

本批為跨子系統重量級修改，已完成下列回歸、三軸審查與 macOS 安裝驗證；全系統目標仍在進行。已為資料庫／下載／writer 啟動／cache／heartbeat／encoder／回放失敗路徑建立可重現回歸，確認舊行為失敗後再修正。主要資料庫收尾整合測試 167 項通過；回放與 launcher 相關 32 項通過。

正常分析的濾波、疲勞／rPPG／HRV 公式、校準參數、門檻、時間戳及記錄欄位不變。持續異常新增 fail-closed 行為：連續 30 幀錯誤會通知並停止，短暫錯誤可恢復。校準 getter 以 path／mtime_ns／size 判斷檔案變化並快取單一解析結果，每次回傳 deep copy 保留可變物件隔離。預覽回壓會合併尚未送出的中間畫面／指標，保留最新值，記錄來源不經這條傳輸佇列。

本機未找到 UTA-RLDD 資料集，不能執行正式 golden replay；合成數值對照與單元回歸不能取代硬體／資料集驗收。未修改 `.env` 或升級依賴。

### 整合回歸與量測

- 完整 Python：`pytest -q -rs`，958 通過、2 項因 Windows rooted-relative 路徑語意在 macOS 略過；`compileall`、`pip check` 通過。
- 真 Engine.IO 4.14.0 慢客戶端：相同 1000 × 100KB 輸入，原 queue 1000 筆／100032890 bytes；修正後 queue 1 筆／100032 bytes，加上最新 pending 100003 bytes，callback slot 為 1。其他快客戶端與可靠上傳進度照常通過；disconnect 釋放狀態並拒絕晚 ACK。
- 真 loopback client 覆蓋首次 snapshot、後續 metrics／preview、request_metrics 的 history／latest。Flask-SocketIO test_client 不實作 server-to-client ACK，不能以它的 get_received 假裝完成流控驗證；效能腳本已改真 loopback polling 與 ACK，相關說明與測試同步。
- `desktop_engine_benchmark --port 5067 --samples 30 --warmup 5`：source API ready 2468.552ms、ready RSS 328.266MiB、state.get p50 20.138ms／p95 21.728ms；640×360 合成 JPEG p50 0.832ms／p95 1.159ms、9115 bytes；真 loopback ACK 30／30 送達，dispatch 663.214 次／秒。此值不包括相機、WebView decode 或 Flutter 呈現，不能當螢幕 FPS。量測程序與 port 已確認釋放。
- 計算前後對照直接載入 HEAD 舊版純 Python worker，固定假 MediaPipe 推論、真實引擎／標註、720p 120 幀：Fatigue 1005.51→389.19ms、Combined 1360.24→791.67ms、rPPG 530.48→453.74ms。各模式 120 筆指標（Combined 共 360 筆含 fused）字典全等，各 41 張預覽 SHA256 全等；不是相機吞吐或推論速度量測。
- 四 ROI 的 12 秒候選窗，100000 筆歷史 89.7963→0.1895ms、900 筆 0.2018→0.1901ms；回傳陣列全等。四 ROI collection：720p 2.8395→2.3890ms、1080p 5.6949→5.0105ms，sample／weights 全等。canonical 開／關與略過像素標註情境另跑 360 幀，跨 BPM spectrum 計算後指標與後續 ROI 逐 bit 相同。
- O10 真 Tauri＋本輪 Flutter release，以無 engine 的獨立 loopback stub 驗證：初始 hidden socket 0／control 0；visible 但無 focus socket 1，control 1→2、metric／frame ACK 1→6；hide 1500ms 後 socket 0、control 保持 2、ACK 保持 6；show 立即 control 3、socket 1、ACK 7。整段重複 metrics HTTP 為 0。未碰攝影機／錄影，測試探針不在正式產物。
- `state.get` 新增 additive `recording_finalizing`，前端在資料庫／影片任一仍收尾時禁用新錄製並顯示收尾中。控制 API readiness 獨立於 metrics 連線狀態；背景成功更新只清對應連線／history 錯誤，保留使用者操作錯誤。
- 完整 Flutter `flutter test`：87 項通過；`flutter analyze` 無問題。Rust `cargo check --locked`、`cargo test --locked`：17 項通過。`git diff --check` 通過。
- Python sidecar 已完整重建，source 與 packaged runtime／Face Landmarker preflight 皆通過；正式 Tauri `.app` release 建置成功，產物及安裝版 `codesign --verify --deep --strict` 通過。未升級依賴。既有 socket_io_common Wasm dry-run 與 CupertinoIcons 提示仍存在，現行 dart2js release 成功；不以關閉提示當成修復。
- 已保留舊 `.app` 備份並更新 `/Applications/疲勞監測操作台.app`。原生操作確認主畫面完整、可捲動至底部並返回、歷史頁讀到既有兩段記錄，冷啟動連線錯誤在 engine ready 後自動消失，API v2 與 UI 都顯示引擎已連線；保留開啟於即時監測頁。使用者設定／記錄未刪除。當次攝影機清單為空，未啟動實體相機／錄影／BLE，因此這次安裝驗證不能宣稱硬體端到端通過。

### 三軸審查

1. 官方 API／版本與執行緒所有權：核對 lockfile 及精確實裝來源，涵蓋 Tauri AppHandle／dialog／startup Child、Dart ACK 形態、Overlay event 權限、unlisten Promise、校準 cache 與 ROI 濾波重用，無本批阻擋項。另重現既有 O25 heartbeat ownership 與 O26 反覆字型快取，保留後續修復。
2. 程式與部署錯誤：找到 app.exec 返回後 writer 無法再輪詢，以及影片較晚完成未推播 finalizing=False，均已修正並新增回歸；重查 ACK token／disconnect、取消／join／Child reap、replay 初始化及獨立收尾後無新增阻擋項。獨立生命週期／傳輸／儲存 269 項、計算 306 項、Flutter 相關 24 項及 Rust 17 項通過。
3. 專案慣例／文件：核對不改 env／依賴／schema、source／bundled engine 邊界、既有 6 秒最後強制終止保護、native child helper 僅 cfg(test)、探針只在暫存資料夾，不混入 production。同步過期 weighted_mix docstring、benchmark 範圍與本報告。無本批阻擋項。

### 版本與文件依據

本輪沿用 lockfile／本機套件：Python 3.12.14、PySide6 6.11.2、NumPy 2.5.2、SciPy 1.18.1、OpenCV-contrib 5.0.0.93、MediaPipe 0.10.35、Flask 3.1.3、Flask-SocketIO 5.6.1、python-socketio 5.16.4、Engine.IO 4.14.0、Requests 2.34.2、Flutter 3.47.2／Dart 3.13.2、socket_io_client 3.1.6、http 1.6.0、Tauri 2.11.5。

開始前已搜尋 GitHub 上游技術，沿用現有 Socket.IO ACK／標準資源收尾機制，未加依賴。Context7 用於套件 API，精確版本未建立索引時另核對安裝來源／版本 tag，不以索引更新日期代表相容性。

- [Python 3.12 SQLite 文件](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-the-connection-context-manager)：transaction context 不關閉 connection。
- [Requests 串流回應](https://requests.readthedocs.io/en/latest/user/advanced/#body-content-workflow)：回應需消費完或 close；另核對本機 2.34.2。
- [Socket.IO server 文件](https://python-socketio.readthedocs.io/en/stable/server.html#event-callbacks)：定向傳送的 ACK；另核對本機 5.16.4／Engine.IO 4.14.0。
- [Qt for Python QThread 文件](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)：wait／finished 的不同收尾用途。Context7 索引為 Qt 6，另核對本機 PySide6 6.11.2；本批事件迴圈外的資料庫 drain 使用 Python thread.join，互動停止採非阻塞輪詢。

## 審查覆蓋與未完工作

第一輪已讀取各主要資料流與相鄰測試，已分派傳輸／儲存、計算管線、Flutter／原生視窗三路審查。主代理另追查控制 broker、錄製 lifecycle、回放與啟動流程。尚未將掃描檔名或既有測試全綠當作全面審查完成的證據。

接續仍需檢查：診斷／封裝工具、錯誤與取消路徑、長時記憶體／CPU／FD、有界佇列、回放與校準數值比對、各平台契約，以及修正後的本機安裝版。未完成項目保留在本表，不會以縮小目標或未驗證的效能宣稱結案。
