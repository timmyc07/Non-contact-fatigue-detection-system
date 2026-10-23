# 全系統優化追蹤

目標：針對這套程序，修復使用者尚未提出的優化問題。本次系統審查已完成 O01–O36 的修正、回歸及可取得的本機驗證。工作分支為 `codex/system-optimization`，驗證通過的提交亦須推至 `main`；前兩批為 `e7c4065`、`47072e1`。原先 ProMotion 與空白面板修正的證據另見[捲動審查](promotion_scroll_2026-10-23.md)。

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
| O16 | BLE 歷史成本 | WatchHrHub 不斷 append，每次 snapshot 複製全歷史，physio 僅用 90 秒 | 第二批已修；維持 90 秒有效窗、10000 筆上限及 latest／累計契約，異常時間另告警 |
| O17 | 無觀眾預覽 | 零 client 仍在主執行緒縮放／JPEG／base64 | 已修；零 client 不編碼、不更新節流時間，首 client 下一幀正常傳送 |
| O18 | 分析持續失敗 | MediaPipe 或整幀處理例外被無限略過，管線表面仍在運行 | 已修；連續 30 幀失敗退出並告警，成功幀重置計數 |
| O19 | heartbeat 重啟 | 舊 HTTP refresh 超過 join 期限後，新 start 清除共用 stop event，舊 thread 可復活 | 已修；每輪捕捉獨立停止事件 |
| O20 | FFmpeg 寫入堵塞 | encoder 不消費 stdin 時，request_stop 無法中斷 write／close | 已修；停止 watchdog 有界等待後只終止自身 encoder 並 reap，failed／finished 各一次 |
| O21 | 回放資源生命週期 | recorder／模型初始化在 try 外；close 逾時仍可能報 done；一個 cleanup 失敗會跳過其他資源 | 已修；初始化納入邊界、背景回放等待 writer 排空、各資源獨立釋放；7 項新回歸通過 |
| O22 | 影片停止等待 | Qt 控制指令仍可能 join video 2000ms，收尾慢時操作受阻 | 第二批已修；零等待輪詢，停止記錄不再停止監測，收尾期間拒絕新錄製 |
| O23 | 退出後備清理 | app.exec 返回後沒有 timer 再輪詢 pending writer／adapter；main 忽略清理失敗 | 第二批補齊 Web／BLE／全部 QThread 的同步 drain；逐項 best-effort，失敗回報 exit 1 |
| O24 | BLE 停止等待 | GUI 呼叫 stop_belt 最多同步等待背景 thread 5 秒 | 第二批已修；只取消一次、50ms 零等待輪詢，保留停止中 ownership 並禁止重啟 |
| O25 | Web server 的 File Browser ownership | 合成登入後停止 server，heartbeat thread 仍活著且仍保留登入；未觸碰外網 | 第二批已修；HTTP／Session／串流／所有 heartbeat 由背景 owner 釋放，失敗保留待重試資源 |
| O26 | 封裝啟動字型快取 | PyInstaller 6.22.2 runtime hook 每次建立臨時 MPLCONFIGDIR，packaged preflight 反覆建 cache | 第二批修正 frozen 啟動入口；持久 cache 寫入探測失敗才保留安全臨時 fallback，封裝實測見後文 |
| O27 | 相機搜尋阻塞／失敗清單 | 同步 OpenCV open／warmup_read 阻塞 Qt heartbeat；例外會清空先前兩台與選取 | 第二批已修；單飛 CameraScanWorker＋queued slot，取消／過期結果保護，失敗保留原清單 |
| O28 | Web 重啟／停止等待 | Qt 等待服務停止最多 5 秒；一次收尾失敗會一直等完成 | 第二批已修；request-stop＋50ms 輪詢、舊 owner 完成才重綁；有限重試並同步 drain 後備 owner |
| O29 | 一般回放產出遺漏 | recordings 僅列 root／utarldd_runs，replay_runs 的 DB／影片未出現 | 第二批已修；共用 run directories／marker，新增錄製自動刷新並可播放 |
| O30 | 上傳進度回壓 | 慢客戶端 10000 次進度使 Engine.IO queue 積 10000 筆／1008901 bytes | 第二批已修；進度亦用每 SID ACK／latest，HTTP 成功／失敗結果仍完整 |
| O31 | 相機／分析停止等待 | main_window 的 combined／rPPG／fatigue／相機停止仍有 3–5 秒 Qt wait | 第三批已修；非阻塞 transition／rollback、舊 queue 早 detach、stale 訊號過濾及全入口 pending guard |
| O32 | 診斷 live feed／遠端覆寫一致性 | 可選 feed 非原子寫入可讀到空窗、寫入錯誤向分析端傳播；成功覆寫仍返回舊 DB，且同站不同資料夾同名資源互相碰撞 | 第三批已修；atomic feed／容錯、完整資源路徑 cache identity、精確失效與共用 HTTP path 編碼 |
| O33 | 封裝首次路徑啟動 | 暖字型 cache 的新 engine 路徑第一次完整 readiness 曾 39.606 秒，超過 Rust 20 秒限期；第二次僅 1.205 秒 | 第三批已修過早終止；UI 先開並顯示載入，API 相容性以 90 秒總限期等待、各 socket 操作另有界；未宣稱首輪載入時間消失 |
| O34 | 安裝版首次相機清單 | OpenCV 的首次授權為非同步，未授權時先返回空清單；Qt requestPermission 又會錯查 source／sidecar 自身缺少的 bundle metadata | 第三批已修；單次背景 AVFoundation probe、Qt 狀態輪詢，授權且原 worker 釋放後自動完整搜尋；未修改系統授權 |
| O35 | 錄影時間軸 | 實機 DB 記錄 36.626 秒，但影片 726 frames／30 FPS，僅 24.2 秒；recorder 丟棄 timestamp、用固定相機 FPS 寫節流後分析預覽 | 第三批已修；依單調時間 sample-hold 補／丟幀、停止時 drain，實機跨模式錄影時間吻合；舊影片保持原檔 |
| O36 | Qt 收尾鎖反序 | 相機壓力測試重現主線程 QTimer 析構持 GIL 等 Qt mutex、背景 worker 析構持 mutex 等 GIL，僅加 Slot 仍於第七輪卡住 | 第三批已修共享收尾順序；真 QObject 保留至成功 join 後，由主線程析構，再通知 owner 釋放 |

## 第一批驗證與數值影響

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

## 第二批驗證與數值影響

第二批完成 O16、O22–O30，補齊背景停止與資料所有權；沒有升級依賴、改 `.env`、新增 schema 或改演算法公式。停止錄製會立即返回並保留待完成 writer／video；監測可繼續，新錄製須等兩種資源都收尾。BLE 多次零等待輪詢只送一次 cancellation，不能再次中斷 Bleak disconnect。Web Qt 輪詢對同一待收尾 owner 至多送一次顯式重試；事件迴圈外使用至多兩輪同步 drain，`stop()` 本身也會提出停止要求，所有當次 owner 都 join 後才返回。永久失敗仍保留錯誤，逐項繼續回收其他資源，最終回報失敗；不宣稱無限重試或永不失敗。

### 數值行為

正常時間順序的 BLE 生理計算維持 `[now-90, now]` 視窗，hub 的 latest／total_received 契約不變。直接載入舊版純模組，以兩小時 7200 樣本、四個檢查點比對，所有 dataclass 生理輸出完全相同。超過 10000 筆的異常通知頻率、未來／非有限時間戳、系統時鐘倒退會明確告警並排除無效資料或保留有效交集；這些異常情境不宣稱與舊無界歷史數值等價，也無法恢復已過期移除的樣本。未改疲勞、rPPG、HRV 公式或校準門檻。當地仍無 UTA-RLDD 資料集，未執行正式 golden replay。

### 實跑結果

- 完整 Python `pytest -q -rs`：1022 passed、2 skipped（Windows rooted-relative 語意）；`compileall -q main.py gui rppg tests`、`pip check`、`git diff --check` 通過。新增回歸先重現阻塞、清單遺失、重試與 owner 提早釋放，再修正。
- Flutter 完整測試 88 passed、`flutter analyze` 無問題；Rust `cargo test --locked` 17 passed。完整 Flutter release、Python sidecar 及 Tauri `.app` 重建成功，source／packaged 一般及 Face Landmarker preflight 通過。既有非使用中的 Wasm dry-run／CupertinoIcons 提示仍存在，dart2js release 成功。
- BLE 長時 100000 筆／27.8 小時合成通知：舊 hub traced memory 從 239140 增至 23999612 bytes；新 hub 保持約 21272–21560 bytes、91 筆有效樣本；snapshot＋physio median 8.60→1.72ms。凍結時鐘的 100000 次輸入仍有 10000 筆上限；1001 次 stop poll median 0.00250ms、max 0.06621ms、cancel 只有一次。
- 慢上傳進度客戶端同樣 10000 次輸入：queue 10000 筆／1008901 bytes→1 筆／100 bytes，加一筆最新 pending；ACK 後可收到 100%。HTTP 成功與失敗測試均保留。
- 持久字型 cache：同環境舊封裝 preflight 10.202／8.797 秒且兩次重建；新隔離 cold 9.636 秒、warm 0.499 秒，暖開無重建且 cache SHA／mtime 完全不動。整個 engine 移至含空白的新路徑，首次 16.227 秒、再次 0.701 秒，無 cache 重建；1113 個 TTF metadata 不變、40 個 bundled relative entries 正確 rebased，真 FreeType 開啟搬移後字型成功。此結果不代表所有首次啟動負擔均消失，O33 另列。
- Source engine API ready 2602.67ms（camera_scanning=true）→3922.76ms 掃完並找到一台。新 frozen engine 暖開 offscreen：API 1205ms→2244ms 掃完；cocoa：API 2006ms→2967ms 掃完，均找到一台並正常 app.shutdown exit 0。沒有保存相機影像或錄製；不是實際分析吞吐量測。
- GC 停用下 100 輪建立／收尾、10000 筆資料落盤，FD 4→4、剩餘 writer thread 0。正常 live-feed 30 次寫入合計平均約 5.34ms／秒，沒有為低成本診斷通道新增背景執行緒的證據。
- `/Applications/疲勞監測操作台.app` 已更新並開啟；產物、暫存安裝目錄與最終安裝版均通過 `codesign --verify --deep --strict`。舊版保留於 `~/Library/Application Support/FatigueMonitorAppBackups/20261023-194002-before-background-cleanup.app`。UI 引擎已連線，捲動至底／返回、歷史頁與原有兩段記錄通過，未刪設定或記錄。安裝版起初相機清單空，稍後刷新恢復一台；未由代理修改授權。實機 combined 監測約 30 FPS，沿用使用者既有自動錄製偏好，新增約 36 秒／3279 筆測試記錄並保留；停止回應 196.92ms，最終 pipeline／recording／finalizing 均 false。歷史重新整理後共三段可見，DB integrity_check=ok；影片首幀可讀、10.3MB，但時間長度不符（O35），不可宣稱錄影同步通過。初次清單空的根因仍待 O34，實體 BLE 未測，不能以此宣稱醫療數值準確或全部硬體路徑完成。

### 三軸審查與依據

1. 官方版本／執行緒：核對 PySide6／Qt 6.11.2、Bleak 3.0.2，實際 QThread 無主事件迴圈的 join／worker 刪除與 queued slot 主執行緒自檢通過。對應初輪 260 項、含重試修正的 189 項通過。
2. 相鄰程式／部署：發現 Web failure 無重試與 postloop 新重試 owner 未 drain 風險，已修並補回歸；另補 `stop(None)` 等待實際 owner 退出及共用 timeout 總預算。transport／storage 92 項與跨模組 32 項通過。O31／O32 的既有問題保留後續批次，沒有當成已修復。
3. 慣例／文件：核對 additive `camera_scanning`、取消與 stale identity、禁重啟保護、source／bundled 邊界、無依賴／env 改動，測試探針只在暫存目錄。同步本追蹤；本機權威 `CLAUDE.md` 已同步過期描述，但它原被 gitignore 忽略，未強行加入 Git。

Context7 沒有 PyInstaller 6.22.2／Matplotlib 3.11.1／Bleak 3.0.2 的精確索引，已另核對實裝及官方版本原碼；不以 develop 文件冒充版本符合。延用上批版本，新增核對 Matplotlib 3.11.1、PyInstaller 6.22.2、Bleak 3.0.2。

- [Qt for Python 6.11 QThread](https://doc.qt.io/qtforpython-6.11/PySide6/QtCore/QThread.html) 與 [Signals／Slots](https://doc.qt.io/qtforpython-6.11/tutorials/basictutorial/signals_and_slots.html)：wait、quit、queued receiver 執行緒。
- [Bleak 3.0.2 client](https://github.com/hbldh/bleak/blob/v3.0.2/bleak/__init__.py)：`__aexit__`／disconnect 收尾。
- [PyInstaller 6.22.2 Matplotlib runtime hook](https://github.com/pyinstaller/pyinstaller/blob/v6.22.2/PyInstaller/hooks/rthooks/pyi_rth_mplconfig.py)：每輪臨時 MPLCONFIGDIR。
- [Matplotlib 3.11.1 font manager](https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/font_manager.py)：cache 讀寫及 bundled relative 字型路徑。

## 第三批驗證與數值影響

本批處理 O31–O36：互動控制改為先提出停止要求並保留 owner，背景釋放後再完成分析切換；可選診斷寫檔與遠端資源快取補齊一致性；原生啟動採有總期限的相容性等待；新錄影依單調時間建立固定 FPS 時間軸，並補齊相機授權及 QObject 收尾順序。未增加依賴、背景寫檔服務、可選環境參數或資料 schema。第二批已提交並推送至 `main` 的版本為 `47072e1`。

### O31：互動停止與分析切換

- 相機、combined、rPPG、fatigue 的互動停止不再於 Qt 主執行緒等待 3–5 秒。停止要求、零等待 join 與完成通知分開；adapter 完成前保留 reference，先解除舊 BGR queue，避免分析停止期間持續堆積新輸入。事件迴圈退出後仍由既有同步 drain 回收 owner。
- 分析切換由 controller 保留原模式、目標模式與啟動錯誤。舊 worker 釋放後才啟動目標；目標啟動失敗會先清理，再恢復原模式；恢復也失敗則保留 cleanup pending 並阻擋重啟。切換尚未完成時，各控制入口與 Flutter 對應操作保持一致的 busy 狀態，自動採集也沿用同一完成／回滾流程。
- queued metrics、preview、record frame、status、failure 以目前 worker 身分及停止／切換狀態篩選，晚到的舊 session 訊號不再更新新 session 或觸發停止。切換時清除舊指標並重建 worker 的暖機與基線蒐集，不能把新舊分析 session 的輸出混在一起。
- macOS 實體相機下兩次模式切換的控制回覆為 **16.35ms／17.34ms**；同次 control 查詢 **p50 16.47ms／p95 20.14ms**。這些數值量到控制回覆延遲，分析模型初始化、暖機與基線重建仍須後續影格完成，不能視為整段推論或切換初始化耗時。

### O32：診斷輸出與遠端資源一致性

- File Browser 的 cache root 由 `FileBrowserClient` 建構時單一持有，下載仍回傳單一本機 `Path`。快取身分包含站點、帳號與完整遠端 resource path；同站 `/a/same.db`、`/b/same.db` 不再互相命中。舊 basename 快取無法證明來源，直接不命中，未加入搬移或相容分支。
- 原始 resource path 共用一個正規化契約：leading `/` 與重複分隔符／`.` 統一，拒絕實際 `..`、backslash、NUL 與空路徑。快取使用正規路徑雜湊，HTTP 對同一路徑編碼一次；Unicode、空白、`%`、`?`、`#` 保持檔名字義，literal `%2F` 不會被額外解碼成路徑分隔符。下載、上傳、影片串流、刪除與一般下載的 resource URL 已逐一核對。
- 成功上傳才失效該站點／帳號／完整資源的快取，HTTP 失敗保留原快取；新 client 也能失效前一輪已存在的磁碟快取。409 override 重試、失效與切換站點共用互斥邊界，避免第一次要求與重試送至不同站點。
- 一般下載另補真 HTTP 信任邊界：原始 Unicode `Content-Disposition` 會使 Werkzeug 於 Latin-1 標頭輸出時失敗，僅用 Flask test client 看不出此問題。改用已安裝 **Werkzeug 3.1.8** 的 `dump_options_header` 輸出 RFC5987 `filename*=UTF-8''...`；真 loopback 驗證 Unicode、雙引號、literal percent、問號／井號及內嵌 CRLF，皆能完整下載並還原原檔名，標頭僅含 ASCII，沒有額外注入標頭。
- 可選 live feed 使用同目錄唯一暫存檔，關閉後原子 replace，失敗清理暫存並保留前一份有效快照。I/O 錯誤只告警並讓分析繼續；持續故障僅告警一次，成功恢復後才重置告警狀態。此通道是暫態診斷快照，未額外執行每幀 fsync，也未新增背景 writer。
- 真實檔案 I/O 並行驗證：**2000 次 atomic write，5887 次讀取中 0 次無效快照**，無暫存檔或讀取 thread 殘留。寫入 **p50 0.235ms／p95 0.377ms**，平均每秒 30 次寫入合計 **7.74ms／秒**。此數值是檔案輸出的成本，未據此宣稱影格率提升。
- 最終相鄰回歸 **142 項通過**，涵蓋成功／失敗上傳、跨站／帳號／完整路徑隔離、切站競態、真 wire 檔名與標頭、live feed 原子可見性及 I/O 故障下的實際 metrics record／publish；`compileall`、read-back 與 `git diff --check` 通過。

### O33：冷啟動期限與嚴格 readiness

- 新封裝路徑第一次完整 readiness 曾耗 **39.606 秒**，同一路徑暖開為 **1.205 秒**。第二批已解決重建字型 cache，這組量測仍證明首次完整啟動存在其他成本，原本 20 秒期限會過早中止健康 engine。
- 保留背景啟動與 Child ownership，原生 UI 先開啟，Flutter 顯示服務載入狀態；readiness 使用 **90 秒總期限**。延長等待是避免誤殺，沒有宣稱首次啟動已縮短到暖開時間。啟動期間退出仍取消、終止並 reap 當次 owned child。
- readiness 需 HTTP 成功、JSON `success=true` 與整數 `desktop_api_version=2`，不以開埠、字串版本或無關服務當作相容。單次 probe 最多 2 秒，connect 最多 500ms，write 與整段 read 另受剩餘期限限制；response 上限 **64KiB**。read 使用固定 deadline，逐 byte 慢送也不能重置等待而無限延長；所有 probe 共用啟動總預算。
- 對應回歸包含總期限、逐 byte 回應、oversized／失敗／版本不符回應與 readiness 競態下退出；Rust **22 項通過**，`cargo check` 通過。

### O35：錄影的實際時間軸

- 第二批實機紀錄保留原檔：DB 記錄 **36.626 秒**，影片 **726 frames／30 FPS＝24.2 秒**。影像可解碼只能證明檔案可讀；節流後的分析預覽被直接當成相機 FPS 寫入，會縮短錄影，該次不能算時間同步驗收通過。
- 新 recorder 在建構時建立 `perf_counter` 起點，依同一單調時鐘的入列 timestamp 決定固定 FPS 格點，以最近已見影像 sample-hold 補幀或丟棄過密中間幀。首張影像較晚時可補黑畫面，輸入間隔較長時保持前張影像；這些是新影片的明確像素與時間軸行為。
- 停止時先記錄停止時間，再排空已接受的 queue，忽略停止後影格並補齊停止時刻；非有限、倒退或不合理的未來 timestamp 會明確失敗。FFmpeg 中途退出保留已錄部分並告警，不再以 OpenCV 重開同一路徑覆寫。既有 stdin 堵塞 watchdog、正常 EOF、kill／reap 與恰一次 finished 收尾契約保留。
- 獨立錄影生命週期 **24 項測試通過**。補測 **1／5／20／30／60／120Hz** 合成輸入，3 秒輸出至 **29.97 FPS** 均為 **90 幀**；真 encoder 的 20Hz、2.5 秒輸入產生 75 幀，時長誤差小於一幀。1080p 停止至 drain 完成量得 **0.290 秒**。
- 本批實機跨模式錄影為 **360 幀／29.761964 FPS＝12.095976 秒**，落在控制操作量得的 **12.059439–12.122993 秒**實際區間，與舊片縮短問題的證據分開保存。既有影片、DB 與測試紀錄未重寫。

### O34／O36：相機授權與 Qt 物件收尾

- 核對 OpenCV 5.0.0 的 AVFoundation 原碼：授權未決時，背景 `VideoCapture` 提出非同步請求後立刻返回失敗；因此原先完整列舉可能在使用者回覆前先產生空清單。Qt 6.11.2 的 `requestPermission` 又要求程序自身 MainBundle 的 usage description，source Python 與目前 nested sidecar 不具備該 metadata，會在真正提出系統請求前合成 Denied。最終不使用此 Qt request 路徑，不注入 metadata、不重設 TCC、不新增套件。
- 沿用既有 OpenCV：`CameraScanWorker(permission_only=True)` 背景只做一次 AVFoundation open／release，Qt 主線程以 runtime-owned 100ms timer 讀取真實授權狀態。等待期間不覆寫既有清單；Granted 仍須等 permission worker 完成 join／release 才完整搜尋。Denied 單次通知，錯誤停止輪詢並提供可行動訊息；cleanup 取消等待並忽略晚到結果，不等待使用者關閉系統對話框。
- 真 source 整合先確認 OS 已 Granted，才僅將第一次 Qt 狀態讀值模擬為 Undetermined；實際執行 OpenCV probe、後續讀真 Qt 狀態及完整搜尋。probe／完整搜尋各 **1 次**，probe owner 仍在時 Qt heartbeat **107 次**，最大間隔 **15.90ms**，**1.651 秒**找到 1 台相機，pipeline／recording 均 false，完整收尾 exit 0。此驗證涵蓋實際續掃與提前 Granted 的競態，沒有重設權限或宣稱重現 OS 首次提示。
- 壓力測試另重現 QObject 背景析構與主線程 QTimer 析構的 Qt mutex／GIL 鎖反序。僅註冊 Slot 並未消除，於第七輪再次卡住。共享修正移除真 worker 的 `thread.finished -> worker.deleteLater`，保留物件至 `wait()` 成功，再由主線程明確析構，最後通知 adapter released。兩個實際 Qt 回歸先紅，涵蓋有／無主事件迴圈、join 前物件仍有效、析構執行緒與先析構後釋放順序。
- 最終四檔相關 **213 項通過**；以 30 秒硬期限的獨立子程序重跑 **10／10 輪、合計 2130 項**，每輪測試 2.84–2.96 秒，沒有 timeout、hang、segfault 或 stderr。不是對未修版本反覆重跑直到碰巧通過。
- 這條明確析構路徑只在成功 join 後執行，原執行緒已不再處理任何事件，符合 Qt 的安全例外；目前七種 worker 沒有 QObject timer／socket 子物件，且 native 資源在 finished 前已關閉。數值、停止要求、stale identity guard 與 postloop drain 契約保留。

來源：Context7 為 Qt 6 通用索引，另核對 [Qt 6.11.2 QObject 原碼](https://github.com/qt/qtbase/blob/v6.11.2/src/corelib/kernel/qobject.cpp)、[Qt 6.11 執行緒文件](https://doc.qt.io/qt-6.11/threads-qobject.html)、[OpenCV 5.0.0 AVFoundation 原碼](https://github.com/opencv/opencv/blob/5.0.0/modules/videoio/src/cap_avfoundation_mac.mm) 與 [Qt 6.11.2 Darwin permission 原碼](https://github.com/qt/qtbase/blob/v6.11.2/src/corelib/platform/darwin/qdarwinpermissionplugin.mm)。PySide6 6.11.2 的相機 permission plugin 靜態包含於已封裝的 `QtCore.abi3.so`，不需新增 plugin 收集規則。

### 數值行為、整合驗證與部署邊界

疲勞、rPPG、HRV、ROI、融合公式、門檻與已保存校準數值未改。模式轉換抑制 stale 輸出並重建 worker 暖機／基線，轉換期間的指標序列可能出現等待與重新暖機，不能宣稱跨 session 逐筆等價。新影片會補／丟幀並可能出現啟動黑畫面，因此新影片的時長與像素序列會改變；分析輸入與舊資料不因錄影時間軸修正而重算。

- 最終凍結 source 完整 Python `pytest -q -rs -o faulthandler_timeout=20`：**1119 passed、2 skipped**，12.47 秒；略過仍僅為 macOS 無法套用的 Windows rooted-relative 路徑語意。相鄰 O32 最後 142 項結果見前文。
- Flutter 完整測試 **97 項通過**、analyze 無問題；Rust **22 項通過**、`cargo check` 通過。
- O34／O36 的 source 與壓力驗證見前文；最終封裝及安裝驗證另列，不以 source 成功取代安裝版驗收。
- 本機未取得 UTA-RLDD 資料集，未執行正式 golden replay；實體 BLE、Windows 與 Linux 端到端未測。macOS 的局部實機量測不能代替這些驗證，也不能用來宣稱生理指標的醫療準確性。

本批沿用既有套件版本。Context7 的 Werkzeug 索引為 main，已另核對本機 **3.1.8** 與[官方 3.1.8 HTTP 原碼](https://github.com/pallets/werkzeug/blob/3.1.8/src/werkzeug/http.py)，確認 `dump_options_header` 對 `filename*` 不會再次加引號；國際檔名格式依據 [RFC6266 §4.3](https://www.rfc-editor.org/rfc/rfc6266#section-4.3)。暫存替換沿用專案既有同目錄標準做法，沒有新增相容解析層或依賴。

### 第三批封裝與安裝驗證

- 最終 Python sidecar 完整重建，source／packaged 一般及 Face Landmarker preflight 通過；Flutter release 與 Tauri `.app` 建置成功。`compileall`、`pip check`、`git diff --check` 通過。既有未使用的 Wasm dry-run／CupertinoIcons 提示仍在，dart2js release 成功，未為這些提示新增套件。
- 產物、暫存安裝目錄、最終 `/Applications/疲勞監測操作台.app` 均通過 `codesign --verify --deep --strict`；主程式與 engine SHA256 均與建置產物相同。原安裝版備份於 `~/Library/Application Support/FatigueMonitorAppBackups/20261023-205602-before-final-lifecycle-fixes.app`，使用者設定及記錄保留。
- 安裝版開啟後 API v2 及介面顯示已連線，相機自動列出 1 台，permission／scan／transition／cleanup 均非等待狀態，未出現需要代理批准的系統提示。主畫面完整，可捲動至底部並返回；歷史頁刷新後可見原三段及本次新增的第四段記錄，能開啟新記錄內容。
- 實際安裝版監測平均 **29.973 FPS**，沿用使用者原有自動記錄偏好，保存 **3501 筆**指標與新影片。停止錄製回應 **20.14ms**，當時 pipeline 仍 running；停止監測回應 **21.06ms**，最後 pipeline／recording／finalizing／cleanup 均 false。資料庫 `integrity_check=ok`，影片 **1195 幀／30 FPS＝39.833 秒**，首末幀均可解碼；未覆寫舊影片。指標首筆晚於錄影啟動，故其 **38.896 秒**跨度與影片總時長不是相同起點；嚴格時間軸區間驗收另見 O35 的 12 秒實機對照。
- 正式產物沒有測試探針、額外權限 API 或相容層；本機維持開啟於即時監測頁，監測及錄製停止，供使用者開始自己的工作階段。

## 審查覆蓋與驗證限制

三路審查涵蓋計算管線、傳輸／儲存、Flutter／原生視窗；主代理另檢查控制 broker、診斷／封裝 preflight、錄製、回放及啟動流程。三軸 read-back 核對官方精確版本與執行緒所有權、相鄰程式／部署、專案契約／文件；最後的共享 QObject 修改也完成獨立 API 與部署審查，沒有剩餘阻擋項。已取得的長時 BLE 合成、FD、慢客戶端佇列、數值對照、真 HTTP、真 encoder、實體相機及原生介面證據分列各批；未將單一測試通過當作所有範圍的驗證。

未取得 UTA-RLDD 資料集或實體 BLE 心跳帶，未做正式 golden、實體心跳帶、Windows／Linux 端到端驗收，也沒有重設 TCC 來測 OS 首次授權提示。未做攝影機／BLE 並行的長時間 GPU／電池或高速攝影逐幀呈現量測。這些限制保留，不能用目前 macOS 結果宣稱跨平台硬體或醫療準確性。
