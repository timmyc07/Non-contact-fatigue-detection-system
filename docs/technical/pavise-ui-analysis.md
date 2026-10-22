# Pavise UI 靜態分析

## 證據與限制

`Pavise.exe`（1,413,632 bytes，32-bit PE，Subsystem 2）未簽章，檔案版本資訊顯示為 Synaptics Pointing Device Driver，但可見字串同時包含 `PaviseApp`、`PaviseCore`、`PanelForm` 與 Windows game resource scheduling utility。Windows Computer Use 目前無法連線，因此本次沒有執行或截取該程式畫面；以下結論只採用 PE 標頭、資源目錄與可讀字串，避免把未驗證的畫面細節當成事實。

## 可驗證的 UI 結構

執行檔字串揭示了以頁面註冊和面板生成為核心的 UI 組成：

- `BuildUi` / `RegisterPages` / `ShowPage` / `MakePage`：單一主視窗管理多個頁面，導覽切換不重建整個應用程式。
- `BuildOverviewPage`、`BuildPolicyPage`、`BuildAntiCheatPage`、`BuildEnvironmentPage`、`BuildGraphicsPage`、`BuildLibraryPage`、`BuildReportsPage`、`BuildSettingsPage`、`BuildAboutPage`：頁面按工作域分組。
- `RoundPanel`、`ModePickerPanel`、`DBPanel`、`EmptyStatePanel`、`MakeConsolePanel`：重複使用的面板元件，用來承載狀態、選項、資料庫內容和空狀態。
- `PageHeader`、`UiClock`、`DrawCircuitRing`、`Squircle`：頁面標題、時間/狀態、環形狀態圖與圓角幾何是共用視覺語彙。
- `System.Windows.Forms`、`System.Drawing`、`System.Drawing.Drawing2D`：原生 Windows Forms + GDI+/自訂繪製，而非瀏覽器或 Qt。

## 本次改造

Web dashboard 保留所有既有資料欄位、Socket.IO 事件與 `switchTab`/回放行為，只將外殼改成 Pavise 式操作台：

1. 固定左側導覽，將即時監測和歷史回放視為工作區頁面。
2. 右側保留原本的即時預覽、眼部、姿態、rPPG、融合分析和波形面板。
3. 使用深灰中性色底、青綠主色、琥珀警示色；面板改為 8px 圓角、細邊框與密集資訊層級。
4. 窄視窗時左欄縮成圖示列，手機寬度改為頂部導覽，維持既有面板可讀性。

PySide6 桌面主視窗原本已具備左側導覽和 `QStackedWidget`，因此同步調整 dark QSS token：深灰工作區、青綠 accent、琥珀 warning、8px 面板/控制項圓角。light theme 保持原樣，使用者仍可切換既有主題。

這種改法只改變呈現層，避免 UI 重構影響疲勞演算法或串流協定。
