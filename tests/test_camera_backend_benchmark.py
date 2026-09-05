from __future__ import annotations

from scripts.camera_backend_benchmark import _percentile


def test_percentile_is_stable_for_empty_and_unsorted_values() -> None:
    assert _percentile([], 0.95) == 0.0
    assert _percentile([3.0, 1.0, 2.0], 0.50) == 2.0
