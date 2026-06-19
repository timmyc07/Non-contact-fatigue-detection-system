"""rPPG BPM calibration sub-window (watch reference, version management)."""

from __future__ import annotations

import socket
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rppg.calibration import (
    CALIBRATION_SESSION_QUALITY_GATES,
    ORIGIN_VERSION_ID,
    CalibrationSessionAnalyzer,
    CalibrationVersionStore,
    read_live_feed,
    rppg_sample_quality_ok,
    set_live_feed_enabled,
)
from rppg.calibration_watch import WatchHrHub, WatchHrHttpServer


def _local_ip_hint() -> str:
    candidates = _local_ip_candidates()
    return candidates[0] if candidates else "127.0.0.1"


def _local_ip_candidates() -> list[str]:
    """Return likely LAN IPv4 addresses for the watch app (same order as UI hints)."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(ip: str) -> None:
        if ip and ip not in seen and not ip.startswith("127."):
            seen.add(ip)
            found.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            _add(str(sock.getsockname()[0]))
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(str(info[4][0]))
    except Exception:
        pass

    # Stable ordering: default-route IP first, then others.
    return found or ["127.0.0.1"]


_WINDOW_REASON_LABELS = {
    "no_watch": "此窗口無手錶資料",
    "no_rppg_samples": "此窗口無 rPPG 樣本（請確認相機與壓力/HRV 已開啟）",
    "no_quality_rppg": "rPPG 品質不足（臉部、SQI 或 ROI）",
    "ok": "有效",
}


class _WatchReceiveBridge(QObject):
    packet = Signal(int)
    request = Signal(str, int, str)  # client_ip, status_code, path


class RppgCalibrationDialog(QDialog):
    """Modeless calibration tool: watch HTTP receiver + rPPG live feed pairing."""

    version_changed = Signal(str, str)  # version_id, version_name

    def __init__(self, store: CalibrationVersionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._hub = WatchHrHub()
        self._receive_bridge = _WatchReceiveBridge(self)
        self._receive_bridge.packet.connect(self._on_watch_packet_received)
        self._receive_bridge.request.connect(self._on_watch_request)
        self._http = WatchHrHttpServer(
            self._hub,
            on_received=lambda bpm: self._receive_bridge.packet.emit(int(bpm)),
            on_request=lambda ip, code, path: self._receive_bridge.request.emit(ip, int(code), str(path)),
        )
        self._analyzer = CalibrationSessionAnalyzer()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._on_tick)

        self._session_running = False
        self._session_start = 0.0
        self._session_end = 0.0
        self._watch_added = 0
        self._session_posts_at_start = 0
        self._session_warned_slow = False
        self._drain_stats = {"zero_bpm": 0, "too_old": 0, "added": 0}
        self._last_watch_interval_ms = 0
        self._last_estimate: dict[str, Any] | None = None

        self.setWindowTitle("rPPG 心率校準器")
        self.setMinimumSize(640, 560)
        self._build_ui()
        self._refresh_versions()
        self._update_active_label()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(content)

        hint = QLabel(
            "開啟此視窗即會啟動手錶 HTTP 接收（不需先按開始校準）。"
            "請確認手錶 App 的 PC IP／埠與下方一致，且已關閉其他佔用 8080 的程式"
            "（例如 HeartBeatBT 的 test_server.py）。建議心率間隔 1 秒。"
            "按「開始校準」後才開手錶傳送，並保持至 session 結束"
            "（「Session POST」應約每 1 秒 +1）。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        root.addWidget(hint)

        net_box = QGroupBox("手錶連線")
        net_form = QFormLayout(net_box)
        self._lbl_endpoint = QLabel()
        self._spin_port = QSpinBox()
        self._spin_port.setRange(1024, 65535)
        self._spin_port.setValue(8080)
        self._spin_duration = QSpinBox()
        self._spin_duration.setRange(30, 900)
        self._spin_duration.setSuffix(" 秒")
        self._spin_duration.setValue(180)
        self._spin_window = QSpinBox()
        self._spin_window.setRange(10, 120)
        self._spin_window.setSuffix(" 秒")
        self._spin_window.setValue(30)
        self._spin_warmup = QSpinBox()
        self._spin_warmup.setRange(0, 120)
        self._spin_warmup.setSuffix(" 秒")
        self._spin_warmup.setValue(15)
        net_form.addRow("接收位址：", self._lbl_endpoint)
        self._lbl_all_ips = QLabel()
        self._lbl_all_ips.setWordWrap(True)
        self._lbl_all_ips.setObjectName("hintLabel")
        net_form.addRow("本機 IP 候選：", self._lbl_all_ips)
        net_form.addRow("埠：", self._spin_port)
        net_form.addRow("Session 時長：", self._spin_duration)
        net_form.addRow("配對窗口：", self._spin_window)
        net_form.addRow("暖機時間：", self._spin_warmup)
        root.addWidget(net_box)
        self._refresh_endpoint_label()

        live_box = QGroupBox("即時數值")
        live_grid = QFormLayout(live_box)
        self._lbl_watch_bpm = QLabel("—")
        self._lbl_rppg_bpm = QLabel("—")
        self._lbl_delta = QLabel("—")
        self._lbl_warmup = QLabel("—")
        self._lbl_feed_status = QLabel("—")
        self._lbl_watch_conn = QLabel("離線")
        self._lbl_receiver = QLabel("未啟動")
        self._lbl_received_count = QLabel("0")
        self._lbl_session_posts = QLabel("0")
        self._lbl_session_watch = QLabel("0")
        self._lbl_elapsed = QLabel("0 秒")
        self._lbl_active_version = QLabel("—")
        for lbl in (
            self._lbl_watch_bpm,
            self._lbl_rppg_bpm,
            self._lbl_delta,
        ):
            lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        live_grid.addRow("手錶 BPM：", self._lbl_watch_bpm)
        live_grid.addRow("rPPG BPM：", self._lbl_rppg_bpm)
        live_grid.addRow("差值 (手錶−rPPG)：", self._lbl_delta)
        live_grid.addRow("rPPG 暖機：", self._lbl_warmup)
        live_grid.addRow("rPPG 資料：", self._lbl_feed_status)
        live_grid.addRow("HTTP 接收器：", self._lbl_receiver)
        live_grid.addRow("手錶連線：", self._lbl_watch_conn)
        live_grid.addRow("累計 POST：", self._lbl_received_count)
        live_grid.addRow("Session POST：", self._lbl_session_posts)
        live_grid.addRow("Session 手錶樣本：", self._lbl_session_watch)
        live_grid.addRow("Session 進度：", self._lbl_elapsed)
        live_grid.addRow("使用中版本：", self._lbl_active_version)
        self._bar_progress = QProgressBar()
        self._bar_progress.setRange(0, 100)
        live_grid.addRow("", self._bar_progress)
        root.addWidget(live_box)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(140)
        root.addWidget(self._log)

        session_row = QHBoxLayout()
        self._btn_start = QPushButton("開始校準")
        self._btn_stop = QPushButton("停止")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._start_session)
        self._btn_stop.clicked.connect(self._stop_session)
        session_row.addWidget(self._btn_start)
        session_row.addWidget(self._btn_stop)
        self._btn_test_post = QPushButton("本機測試 POST")
        self._btn_test_post.setToolTip("從這台 PC 送一筆測試資料到 HTTP 接收器，確認程式本身正常")
        self._btn_test_post.clicked.connect(self._send_local_test_post)
        session_row.addWidget(self._btn_test_post)
        session_row.addStretch(1)
        root.addLayout(session_row)

        save_box = QGroupBox("儲存校準結果")
        save_form = QFormLayout(save_box)
        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("例如：室內白光坐姿")
        self._edit_note = QLineEdit()
        self._edit_note.setPlaceholderText("選填備註")
        self._lbl_result = QLabel("尚未完成校準 session")
        self._lbl_result.setWordWrap(True)
        self._btn_save = QPushButton("儲存並啟用此版本")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_version)
        save_form.addRow("版本名稱：", self._edit_name)
        save_form.addRow("備註：", self._edit_note)
        save_form.addRow("結果：", self._lbl_result)
        save_form.addRow("", self._btn_save)
        root.addWidget(save_box)

        ver_box = QGroupBox("校準版本")
        ver_layout = QVBoxLayout(ver_box)
        self._list_versions = QListWidget()
        self._list_versions.setMinimumHeight(120)
        ver_layout.addWidget(self._list_versions)
        ver_btn_row = QHBoxLayout()
        self._btn_use = QPushButton("使用選取版本")
        self._btn_delete = QPushButton("刪除選取版本")
        self._btn_refresh = QPushButton("重新整理")
        self._btn_use.clicked.connect(self._use_selected_version)
        self._btn_delete.clicked.connect(self._delete_selected_version)
        self._btn_refresh.clicked.connect(self._refresh_versions)
        ver_btn_row.addWidget(self._btn_use)
        ver_btn_row.addWidget(self._btn_delete)
        ver_btn_row.addWidget(self._btn_refresh)
        ver_btn_row.addStretch(1)
        ver_layout.addLayout(ver_btn_row)
        root.addWidget(ver_box)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.close)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

        self._spin_port.valueChanged.connect(self._on_port_changed)

    def _on_port_changed(self) -> None:
        self._refresh_endpoint_label()
        if self.isVisible():
            self._ensure_http_running(restart=True)

    def _on_watch_packet_received(self, bpm: int) -> None:
        if self._hub.total_received == 1:
            self._append_log(f"已收到首筆手錶 POST：{bpm} bpm")
        elif self._hub.total_received % 10 == 0:
            self._append_log(f"已累計收到 {self._hub.total_received} 筆手錶資料")
        if self._session_running:
            self._drain_watch_samples()

    def _on_watch_request(self, client_ip: str, status_code: int, path: str) -> None:
        if client_ip.startswith("127.") and self._hub.total_received > 0:
            return
        mark = "OK" if status_code == 200 else f"HTTP {status_code}"
        self._append_log(f"收到請求 {mark}：{client_ip} {path}")
        if status_code not in (200, 204) and client_ip not in ("127.0.0.1", "::1"):
            self._append_log(
                "若手錶顯示傳送中但這裡仍為 0，請檢查手錶設定的 IP 是否在本機候選列表內，"
                "且手錶與 PC 在同一 Wi‑Fi。"
            )

    def _drain_watch_samples(self) -> int:
        """將 hub 內尚未納入 analyzer 的手錶 POST 全部匯入（依索引，避免漏樣本）。"""
        added = 0
        samples = self._hub.snapshot()
        while self._watch_added < len(samples):
            sample = samples[self._watch_added]
            self._watch_added += 1
            if sample.bpm <= 0:
                self._drain_stats["zero_bpm"] += 1
                continue
            if sample.received_at < self._session_start - 0.5:
                self._drain_stats["too_old"] += 1
                continue
            self._analyzer.add_watch(sample.received_at, float(sample.bpm))
            self._last_watch_interval_ms = sample.interval_ms
            self._drain_stats["added"] += 1
            added += 1
        return added

    def _session_post_count(self) -> int:
        return max(0, self._hub.total_received - self._session_posts_at_start)

    def _ensure_http_running(self, *, restart: bool = False) -> bool:
        port = self._spin_port.value()
        if restart and self._http.running:
            self._http.stop()
        if self._http.running and self._http.port == port:
            self._update_receiver_label()
            return True
        if self._http.running:
            self._http.stop()
        try:
            self._http = WatchHrHttpServer(
                self._hub,
                port=port,
                on_received=lambda bpm: self._receive_bridge.packet.emit(int(bpm)),
                on_request=lambda ip, code, path: self._receive_bridge.request.emit(
                    ip, int(code), str(path)
                ),
            )
            self._http.start()
        except OSError as exc:
            self._http.last_error = str(exc)
            self._lbl_receiver.setText(f"啟動失敗：{exc}")
            self._lbl_receiver.setStyleSheet("color: #fa5252; font-weight: bold;")
            self._append_log(f"HTTP 接收啟動失敗（埠 {port}）：{exc}")
            QMessageBox.warning(
                self,
                "校準器",
                f"無法在埠 {port} 啟動 HTTP 接收。\n"
                f"請關閉佔用該埠的程式後重試。\n\n{exc}",
            )
            return False
        self._update_receiver_label()
        self._append_log(f"HTTP 接收已啟動：{self._lbl_endpoint.text()}")
        return True

    def _update_receiver_label(self) -> None:
        if self._http.running:
            self._lbl_receiver.setText(f"運行中（0.0.0.0:{self._http.port}）")
            self._lbl_receiver.setStyleSheet("color: #40c057; font-weight: bold;")
        else:
            self._lbl_receiver.setText("未啟動")
            self._lbl_receiver.setStyleSheet("color: #868e96;")

    def _stop_http(self) -> None:
        if self._http.running:
            self._http.stop()
        self._update_receiver_label()

    def _refresh_endpoint_label(self) -> None:
        ip = _local_ip_hint()
        port = self._spin_port.value()
        self._lbl_endpoint.setText(f"POST http://{ip}:{port}/hr")
        ips = _local_ip_candidates()
        if len(ips) <= 1:
            self._lbl_all_ips.setText(
                (ips[0] if ips else "—")
                + f"（手錶 App 請填此 IP；若仍收不到，請在 Windows 防火牆允許 TCP {port} 輸入）"
            )
        else:
            lines = [f"• {addr}:{port}/hr" for addr in ips]
            lines.append(
                f"手錶與 PC 須同一 Wi‑Fi；若不確定用哪個，逐一嘗試。"
                f"仍為 0 筆時請在防火牆允許 TCP {port} 輸入。"
            )
            self._lbl_all_ips.setText("\n".join(lines))

    def _send_local_test_post(self) -> None:
        if not self._ensure_http_running():
            return
        import json
        import urllib.error
        import urllib.request

        port = self._spin_port.value()
        before = self._hub.total_received
        url = f"http://127.0.0.1:{port}/hr"
        payload = json.dumps({"bpm": 88, "ts": 0, "interval_ms": 1000}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                code = int(resp.status)
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
        except Exception as exc:
            QMessageBox.warning(self, "校準器", f"本機測試 POST 失敗：{exc}")
            return

        after = self._hub.total_received
        if code == 200 and after > before:
            self._append_log("本機測試 POST 成功（接收器正常）。")
            QMessageBox.information(
                self,
                "校準器",
                "本機測試成功：HTTP 接收器運作正常。\n"
                "若手錶仍為 0 筆，問題在 Wi‑Fi／IP／防火牆，不是程式本身。",
            )
        else:
            QMessageBox.warning(
                self,
                "校準器",
                f"本機測試異常（HTTP {code}，筆數 {before}→{after}）。\n"
                "請確認沒有其他程式佔用此埠（例如 HeartBeatBT test_server.py）。",
            )

    def _append_log(self, text: str) -> None:
        self._log.append(text)

    def _update_active_label(self) -> None:
        self._store.reload()
        version = self._store.get_active_version()
        if version.is_identity:
            self._lbl_active_version.setText(f"{version.id}（未校準）")
        else:
            self._lbl_active_version.setText(
                f"{version.id} — {version.name}  (offset {version.params.bpm_offset:+.1f})"
            )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        set_live_feed_enabled(True)
        self._refresh_versions()
        self._update_active_label()
        self._refresh_endpoint_label()
        self._ensure_http_running()
        if not self._timer.isActive():
            self._timer.start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_session(silent=True)
        self._stop_http()
        self._timer.stop()
        set_live_feed_enabled(False)
        super().closeEvent(event)

    def _start_session(self) -> None:
        if self._session_running:
            return
        if not self._ensure_http_running():
            return

        feed = read_live_feed(max_age_sec=10.0)
        if feed is None:
            QMessageBox.warning(
                self,
                "校準器",
                "無法讀取 rPPG 即時資料（已過期或尚未寫入）。\n\n"
                "請確認：\n"
                "1. 主視窗已啟動相機管線\n"
                "2. 已勾選「壓力／HRV（心率估測）」\n"
                "3. 臉部在畫面中且 rPPG 有 BPM 數值\n"
                "4. 本校準視窗保持開啟（會啟用 live feed）",
            )
            return
        if not bool(feed.get("face_detected", False)):
            QMessageBox.warning(
                self,
                "校準器",
                "目前未偵測到臉部，無法收集 rPPG 樣本。\n請調整坐姿與光線後再開始校準。",
            )
            return
        warmup = float(feed.get("warmup_progress", 0.0) or 0.0)
        if warmup < 1.0:
            reply = QMessageBox.question(
                self,
                "校準器",
                f"rPPG 暖機尚未完成（目前 {warmup * 100:.0f}%）。\n"
                "建議等主視窗顯示暖機 100% 再開始，否則有效窗口可能不足。\n\n"
                "仍要現在開始嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if not self._hub.is_connected():
            QMessageBox.warning(
                self,
                "校準器",
                "手錶目前離線（最近數秒內沒有新的 POST）。\n\n"
                "請確認：\n"
                "1. 手錶 App 的 PC IP／埠與下方一致\n"
                "2. 「已收到筆數」在增加（代表 POST 有進來）\n"
                "3. 校準全程保持手錶傳送，不要只開一次",
            )
            return

        self._analyzer = CalibrationSessionAnalyzer(
            window_sec=float(self._spin_window.value()),
            warmup_sec=float(self._spin_warmup.value()),
            quality_gates=CALIBRATION_SESSION_QUALITY_GATES,
        )
        self._session_start = time.time()
        self._watch_added = len(self._hub.snapshot())
        self._session_posts_at_start = self._hub.total_received
        self._session_warned_slow = False
        self._drain_stats = {"zero_bpm": 0, "too_old": 0, "added": 0}
        self._last_watch_interval_ms = 0
        self._last_estimate = None
        self._session_running = True
        self._session_end = self._session_start + float(self._spin_duration.value())
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._lbl_result.setText("校準進行中…")
        self._log.clear()
        skipped_buf = self._watch_added
        duration = int(self._spin_duration.value())
        self._append_log(
            f"開始校準：{self._lbl_endpoint.text()}  時長 {duration}s"
        )
        self._append_log(
            f"僅納入從現在起的手錶 POST（略過先前緩衝 {skipped_buf} 筆）。"
        )
        self._append_log(
            f"請在手錶 App 按「開始傳送」，並保持至 {duration} 秒結束；"
            f"「Session POST」應約每 1 秒 +1（180 秒約 150–180）。"
        )
        set_live_feed_enabled(True)
        if not self._timer.isActive():
            self._timer.start()

    def _stop_session(self, *, silent: bool = False) -> None:
        if not self._session_running:
            return
        self._session_running = False
        if not silent:
            self._finalize_session()

        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _finalize_session(self) -> None:
        self._drain_watch_samples()
        end_ts = time.time()
        estimate = self._analyzer.estimate(self._session_start, end_ts)
        estimate["watch_interval_ms"] = self._last_watch_interval_ms
        estimate["windows"] = self._analyzer.windows
        self._last_estimate = estimate

        offset = float(estimate["offset_bpm"])
        used = int(estimate["windows_used"])
        rejected = int(estimate["windows_rejected"])
        self._append_log("—— 校準結束 ——")
        session_posts = max(0, self._hub.total_received - self._session_posts_at_start)
        wt0, wt1 = self._analyzer.watch_time_range()
        range_text = (
            f"（{int(wt0 - self._session_start)}–{int(wt1 - self._session_start)}s）"
            if wt0 is not None and wt1 is not None
            else ""
        )
        self._append_log(
            f"手錶 POST：session 內 {session_posts} 筆｜"
            f"納入分析 {self._analyzer.watch_sample_count} 筆{range_text}"
        )
        if self._drain_stats["zero_bpm"] > 0:
            self._append_log(f"略過 bpm≤0 的 POST：{self._drain_stats['zero_bpm']} 筆")
        if session_posts < 30:
            self._append_log(
                "Session 內 POST 過少：多數資料可能在校準開始前就收到，"
                "或手錶未在整段 session 持續傳送。"
            )
        self._append_log(f"有效窗口：{used} / {used + rejected}")
        self._append_log(f"建議 offset：{offset:+.2f} BPM")
        self._append_log(
            f"MAE 校準前：{estimate['mae_before_bpm']:.2f}  "
            f"MAE 校準後：{estimate['mae_after_bpm']:.2f} BPM"
        )
        for idx, window in enumerate(estimate["windows"], start=1):
            mark = "✓" if window.accepted else "✗"
            reason_text = _WINDOW_REASON_LABELS.get(window.reason or "ok", window.reason or "ok")
            self._append_log(
                f"[{mark}] 窗口 {idx}: watch={window.watch_median:.0f}  "
                f"rppg={window.rppg_median:.0f}  residual={window.residual:+.1f}  "
                f"{reason_text}"
            )

        if used >= 1:
            self._lbl_result.setText(
                f"offset {offset:+.2f} BPM｜MAE {estimate['mae_before_bpm']:.1f}"
                f" → {estimate['mae_after_bpm']:.1f}"
            )
            self._btn_save.setEnabled(True)
            if not self._edit_name.text().strip():
                self._edit_name.setText(
                    time.strftime("校準 %Y-%m-%d %H:%M")
                )
        else:
            reasons = [w.reason for w in estimate["windows"] if not w.accepted]
            hint_parts: list[str] = []
            if "no_watch" in reasons:
                hint_parts.append(
                    "Session POST 未覆蓋全部窗口"
                    "（請在按「開始校準」後才開手錶傳送，並保持至結束）"
                )
            if "no_rppg_samples" in reasons:
                hint_parts.append("主程式未寫入 rPPG live feed（確認相機＋壓力/HRV 已開）")
            if "no_quality_rppg" in reasons:
                hint_parts.append("rPPG 品質不足（光線、臉部穩定度、ROI）")
            if not estimate["windows"]:
                hint_parts.append(
                    f"session 太短：需至少 暖機 {self._spin_warmup.value()}s + 窗口 {self._spin_window.value()}s"
                )
            hint = "；".join(hint_parts) if hint_parts else "請延長 session 或改善環境"
            self._lbl_result.setText(f"有效窗口不足（{hint}）")
            self._btn_save.setEnabled(False)

    def _on_tick(self) -> None:
        now = time.time()
        feed_age_sec = 10.0 if self._session_running else 5.0
        feed = read_live_feed(max_age_sec=feed_age_sec)

        if self._session_running:
            self._drain_watch_samples()
            if feed is not None:
                ts = float(feed.get("timestamp", now) or now)
                self._analyzer.add_rppg(ts, feed)

            elapsed = int(now - self._session_start)
            total = max(1, int(self._session_end - self._session_start))
            session_posts = self._session_post_count()
            self._lbl_elapsed.setText(f"{elapsed} / {total} 秒")
            self._lbl_session_posts.setText(str(session_posts))
            self._lbl_session_watch.setText(str(self._analyzer.watch_sample_count))
            self._bar_progress.setValue(min(100, int(elapsed * 100 / total)))

            expected_posts = max(5, int(elapsed * 0.5))
            if (
                not self._session_warned_slow
                and elapsed >= 20
                and session_posts < expected_posts
            ):
                self._session_warned_slow = True
                self._append_log(
                    f"⚠ Session POST 僅 {session_posts} 筆（已 {elapsed}s）："
                    "手錶可能未持續傳送，請確認手錶 App 仍為傳送中。"
                )

            if now >= self._session_end:
                self._append_log("Session 時間到。")
                self._stop_session()

        latest_watch = self._hub.latest()
        watch_bpm = latest_watch.bpm if latest_watch else 0
        rppg_bpm = float(feed.get("bpm", 0.0) or 0.0) if feed else 0.0
        self._lbl_watch_bpm.setText(f"{watch_bpm}" if watch_bpm > 0 else "—")
        self._lbl_rppg_bpm.setText(f"{rppg_bpm:.0f}" if rppg_bpm > 0 else "—")
        if watch_bpm > 0 and rppg_bpm > 0:
            delta = watch_bpm - rppg_bpm
            self._lbl_delta.setText(f"{delta:+.0f}")
        else:
            self._lbl_delta.setText("—")

        if feed is not None:
            warmup_pct = float(feed.get("warmup_progress", 0.0) or 0.0) * 100.0
            self._lbl_warmup.setText(f"{warmup_pct:.0f}%")
            quality_ok = rppg_sample_quality_ok(feed, CALIBRATION_SESSION_QUALITY_GATES)
            sqi = float(feed.get("sqi", 0.0) or 0.0)
            qscore = float(feed.get("quality_score", 0.0) or 0.0)
            if not bool(feed.get("face_detected", False)):
                self._lbl_feed_status.setText("無臉部")
                self._lbl_feed_status.setStyleSheet("color: #fa5252;")
            elif quality_ok:
                self._lbl_feed_status.setText(f"正常（SQI {sqi:.2f}）")
                self._lbl_feed_status.setStyleSheet("color: #40c057;")
            else:
                self._lbl_feed_status.setText(f"品質偏低（SQI {sqi:.2f} / Q {qscore:.2f}）")
                self._lbl_feed_status.setStyleSheet("color: #fab005;")
        else:
            self._lbl_feed_status.setText("過期或未啟動（請開相機＋壓力/HRV）")
            self._lbl_feed_status.setStyleSheet("color: #fa5252;")
            if not self._session_running:
                self._lbl_warmup.setText("—")

        connected = self._http.running and self._hub.is_connected()
        if self._http.running and self._hub.total_received == 0:
            conn_text = "等待手錶 POST…"
            conn_style = "color: #fab005; font-weight: bold;"
        elif connected:
            conn_text = "已連線"
            conn_style = "color: #40c057; font-weight: bold;"
        else:
            conn_text = "離線"
            conn_style = "color: #868e96;"
        self._lbl_watch_conn.setText(conn_text)
        self._lbl_watch_conn.setStyleSheet(conn_style)
        self._lbl_received_count.setText(str(self._hub.total_received))
        if not self._session_running:
            self._lbl_session_posts.setText("—")
        self._update_receiver_label()

    def _save_version(self) -> None:
        if not self._last_estimate or int(self._last_estimate.get("windows_used", 0)) < 1:
            QMessageBox.warning(self, "校準器", "沒有可儲存的校準結果。")
            return
        name = self._edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "校準器", "請輸入版本名稱。")
            return
        estimate = self._last_estimate
        try:
            version = self._store.save_new_version(
                name=name,
                offset_bpm=float(estimate["offset_bpm"]),
                note=self._edit_note.text().strip(),
                session={
                    "duration_sec": self._spin_duration.value(),
                    "window_sec": self._spin_window.value(),
                    "warmup_sec": self._spin_warmup.value(),
                    "watch_interval_ms": estimate.get("watch_interval_ms", 0),
                    "windows_used": estimate["windows_used"],
                    "windows_rejected": estimate["windows_rejected"],
                },
                metrics={
                    "mae_before_bpm": estimate["mae_before_bpm"],
                    "mae_after_bpm": estimate["mae_after_bpm"],
                    "median_residual": estimate["median_residual"],
                },
            )
        except Exception as exc:
            QMessageBox.warning(self, "校準器", f"儲存失敗：{exc}")
            return

        self._append_log(f"已儲存並啟用：{version.id} ({version.name})")
        self._refresh_versions()
        self._update_active_label()
        self.version_changed.emit(version.id, version.name)
        QMessageBox.information(
            self,
            "校準器",
            f"已儲存並啟用版本：\n{version.id}\n{version.name}\n"
            f"offset {version.params.bpm_offset:+.2f} BPM",
        )

    def _refresh_versions(self) -> None:
        self._store.reload()
        active = self._store.get_active_version_id()
        self._list_versions.clear()
        for entry in self._store.list_versions():
            vid = str(entry.get("id", ""))
            name = str(entry.get("name", vid))
            try:
                version = self._store.get_version(vid)
                offset = version.params.bpm_offset
            except Exception:
                offset = 0.0
            prefix = "★ " if vid == active else "   "
            item = QListWidgetItem(f"{prefix}{vid}  {name}  (offset {offset:+.1f})")
            item.setData(Qt.ItemDataRole.UserRole, vid)
            self._list_versions.addItem(item)
        self._update_active_label()

    def _selected_version_id(self) -> str | None:
        item = self._list_versions.currentItem()
        if item is None:
            return None
        vid = item.data(Qt.ItemDataRole.UserRole)
        return str(vid) if vid else None

    def _use_selected_version(self) -> None:
        vid = self._selected_version_id()
        if not vid:
            QMessageBox.information(self, "校準器", "請先選取一個版本。")
            return
        try:
            version = self._store.set_active_version(vid)
        except Exception as exc:
            QMessageBox.warning(self, "校準器", f"切換失敗：{exc}")
            return
        self._refresh_versions()
        self.version_changed.emit(version.id, version.name)
        self._append_log(f"已切換至：{version.id} ({version.name})")

    def _delete_selected_version(self) -> None:
        vid = self._selected_version_id()
        if not vid:
            QMessageBox.information(self, "校準器", "請先選取一個版本。")
            return
        if vid == ORIGIN_VERSION_ID:
            QMessageBox.warning(self, "校準器", "不能刪除最初版本 v000_origin。")
            return
        answer = QMessageBox.question(
            self,
            "校準器",
            f"確定刪除版本 {vid}？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete_version(vid)
        except Exception as exc:
            QMessageBox.warning(self, "校準器", f"刪除失敗：{exc}")
            return
        self._refresh_versions()
        self._append_log(f"已刪除版本：{vid}")
