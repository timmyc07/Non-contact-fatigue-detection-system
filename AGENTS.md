# AGENTS.md

## Autonomous execution

- For future requests, the agent owns technical decisions, sequencing, implementation, and verification without waiting for routine approval.
- Proceed with the safest reversible option that preserves existing behavior and contracts.
- Ask the user only when a decision cannot be inferred and would create material data loss, security exposure, legal risk, or an irreversible product commitment.
- On ordinary blockers, investigate alternatives, implement the best compatible fallback, and report the limitation.

本專案的代理工作規則與架構說明統一維護於 [`CLAUDE.md`](CLAUDE.md)，請以該檔為權威來源。以下是每次任務都必須執行的入口工作流；若與 `CLAUDE.md` 或全域規則衝突，以較高層規則為準。

## 每次任務工作流

1. **讀取上下文**
   - 先讀本檔、`CLAUDE.md`，再讀 `C:\Users\USER\.claude\rules\` 中與任務相關的規則。
   - 讀取涉及的入口、模組與測試；不要用遞迴列檔把 `.venv`、快取或產出物灌入上下文。
   - 先執行 `git status --short`，辨識並保留既有使用者變更。

2. **任務分級**
   - **輕量**：文件、註解、README、文字或 typo。
   - **中量**：單一子系統、GUI/Web UI、資料庫介面或不改數值行為的流程變更。
   - **重量**：演算法、校準、ROI、分數閾值、跨子系統流程、schema 或依賴升級。
   - 分級決定驗證範圍；不因檔案行數少就降低涉及數值行為的等級。

3. **最小範圍實作**
   - 先確認現有模式與相鄰 API，再用 `apply_patch` 做最小差異修改。
   - 預設 ASCII；只在檔案既有字元集且確有需要時加入非 ASCII。
   - 不執行 `git reset --hard`、`git checkout --`、寬範圍刪除或未授權的外部操作。

4. **按分級驗證**
   - 輕量：對受影響的程式檔執行 `compileall`；對設定/JSON 做解析檢查。
   - 中量：執行相關 pytest、`compileall`、`pip check`（若涉及依賴），並完成一次自我審查。
   - 重量：執行完整 `pytest -q`、`compileall`、必要的 golden/replay 檢查與三重審查；明確記錄數值行為影響。
   - 每個驗證都要實際執行並回報結果，不以「應該通過」代替。

5. **完成前 read-back**
   - 重新讀取修改區段，確認規則、路徑、測試與實作沒有互相矛盾。
   - 執行 `git diff --check`，檢查未引入 TODO、暫存除錯碼、編碼或格式問題。
   - 回報修改檔案、驗證命令與結果、未完成項目及剩餘風險。

6. **版本控制邊界**
   - 代理造成的任何變更在驗證通過、read-back 完成後，必須自動 `git add`、建立 commit 並 push 到目前分支的上游遠端。
   - 不要納入未由代理造成的既有變更；若工作樹混有無法辨識的變更，先停下並回報。
   - 測試失敗、沒有上游遠端、認證/網路錯誤或 push 發生衝突時，不得假裝完成；保留本地 commit 並回報確切阻礙。
