"""HRV estimation from watch BPM time series (re-exports :mod:`watch_physio`)."""

from rppg.watch_physio import (
    WatchPhysioState as WatchHrvState,
    compute_watch_physio as compute_watch_hrv,
    ibis_from_watch_samples,
)

__all__ = ["WatchHrvState", "compute_watch_hrv", "ibis_from_watch_samples"]
