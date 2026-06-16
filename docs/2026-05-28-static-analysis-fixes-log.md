# 2026-05-28 靜態分析修復紀錄

## 摘要

- 修正 `gui/fatigue_engine.py` 中 `_clamp` 呼叫缺少上下界參數，讓疲勞品質分數明確限制在 `0.0` 到 `1.0`。
- 修正 `gui/main_window.py` 的 Windows 全域快捷鍵註冊程式碼，使 `ctypes.WinDLL` 與 `ctypes.get_last_error` 在 Linux 型別檢查環境下不再被誤判為屬性錯誤。
- 修正 `scripts/build_rppg_pdf.py` 的 Matplotlib Axes 型別註記。

## 驗證

- `npx --yes pyright`
- `.venv/bin/python -m compileall -q main.py gui rppg tests`
- `.venv/bin/python -m pytest -q`

## 2026-06-16 追加修復

- 修正 `gui/camera_devices.py` 的平台專用 API 型別問題：`os.O_NONBLOCK`、`fcntl.ioctl` 與 `cv2.VideoWriter_fourcc` 改用 `getattr` 與 callable guard，保留 Linux V4L2 與 OpenCV MJPG 協商行為。
- 修正 `gui/alarm_player.py` 的 Qt beep fallback 型別問題，避免 Pylance 將 `QApplication.instance()` 視為不具備 `beep()`。
- 修正 `gui/fatigue_engine.py` 校準起點可能為 `None` 的靜態分析警示；正式 `step()` 流程仍會先建立校準起點。
- 修正 `gui/utarldd_replay.py` 可視化報表聚合時的 CSV 欄位轉 float 型別問題。
- 修正 `gui/web_server.py` 與 `tests/test_web_socketio_dashboard.py` 的 Socket.IO payload 型別註記。
- 移除 `gui/__init__.py` 中造成 pyright warning 的 lazy export `__all__`。

追加驗證：

- `npx pyright`
- `.venv\Scripts\python.exe -m pytest -q`
- `.venv\Scripts\python.exe -m compileall -q main.py gui rppg tests`
- `.venv\Scripts\python.exe -m pip check`
- `node --check gui\web_ui\static\dashboard.js`
