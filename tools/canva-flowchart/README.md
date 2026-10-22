# rPPG Fatigue Flowchart Canva App

這個資料夾是用 Canva CLI 建立的 Canva App，目標是把「結合影像辨識與生理感測之疲勞偵測系統」流程圖插入 Canva 設計頁面。

流程圖節點使用系統用途描述，不以實際程式檔名命名。主要流程包含：

- 一般攝影機輸入
- 最新影格管理
- 共用臉部推論
- 行為疲勞分析
- rPPG 生理訊號估測
- 品質守門
- 融合評分
- 即時告警、記錄、Web 與回放

## App 資訊

- Canva App ID：`AAHAACArWJM`
- Developer Portal：https://www.canva.com/developers/app/AAHAACArWJM
- 主要 intent：Design editor

## 開發與預覽

```powershell
npm install
npm start
```

啟動後可透過 Canva Developer Portal 的 Preview 功能開啟 Canva 編輯器。也可以使用 Canva CLI：

```powershell
canva apps config status --lite
canva apps preview --lite --appId=AAHAACArWJM
```

在 App 中選擇本機 PNG 或 JPEG 流程圖，確認預覽後按「插入流程圖到 Canva」。未選擇有效圖片前無法插入；圖片會依實際長寬比置中縮放，也支援以游標位置插入的設計類型。選檔與預覽只在瀏覽器本機處理，按下插入後才會交給 Canva。圖片不需放入專案，也不會隨原始碼提交。

目前 Codex 內嵌終端不支援 Canva CLI 的互動式 intent 選擇 raw mode；若 preview 指令停在 intent 選擇，請在一般終端機執行同一個 preview 指令。

## 驗證

```powershell
npm run lint
npm run lint:types
npm test -- --runInBand
npm run build
canva apps doctor --ci
```

`dist/`、`node_modules/`、`.env` 與 `.ssl/` 不納入版本控制。
