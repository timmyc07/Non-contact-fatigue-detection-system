"""Background watch HTTP receiver for main-window watch fatigue mode."""

from __future__ import annotations

from typing import Callable

from rppg.calibration_watch import WatchHrHub, WatchHrHttpServer
from rppg.rppg_worker import RppgMetrics
from rppg.watch_adapter import build_watch_rppg_metrics
from rppg.watch_metrics import WatchMetrics, metrics_from_hub


class WatchRuntime:
    """Owns hub + HTTP server used when fatigue fusion runs in watch mode."""

    DEFAULT_PORT = 8080

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.hub = WatchHrHub()
        self._http = WatchHrHttpServer(self.hub, port=int(port))
        self.port = int(port)

    @property
    def running(self) -> bool:
        return self._http.running

    def start(self) -> str:
        if self.running:
            return ""
        try:
            self._http.start()
            return ""
        except OSError as exc:
            return str(exc)

    def stop(self) -> None:
        self._http.stop()

    def latest_metrics(self) -> WatchMetrics:
        return metrics_from_hub(self.hub)

    def latest_rppg_metrics(
        self,
        calibration_loader: Callable[[], object] | None = None,
    ) -> RppgMetrics:
        version = None
        if calibration_loader is not None:
            try:
                version = calibration_loader()
            except Exception:
                version = None
        return build_watch_rppg_metrics(self.hub, calibration_version=version)
