# 2026-05-28 靜態分析修復紀錄

## 摘要

- 修正 `gui/fatigue_engine.py` 中 `_clamp` 呼叫缺少上下界參數，讓疲勞品質分數明確限制在 `0.0` 到 `1.0`。
- 修正 `gui/main_window.py` 的 Windows 全域快捷鍵註冊程式碼，使 `ctypes.WinDLL` 與 `ctypes.get_last_error` 在 Linux 型別檢查環境下不再被誤判為屬性錯誤。
- 修正 `scripts/build_rppg_pdf.py` 的 Matplotlib Axes 型別註記。

## 驗證

- `npx --yes pyright`
- `.venv/bin/python -m compileall -q main.py gui rppg tests`
- `.venv/bin/python -m pytest -q`
