from __future__ import annotations

from scripts.desktop_engine_benchmark import _benchmark_synthetic_preview, _distribution


def test_distribution_reports_expected_percentiles() -> None:
    result = _distribution([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result == {"min": 1.0, "p50": 3.0, "p95": 5.0, "max": 5.0, "mean": 3.0}


def test_synthetic_preview_benchmark_delivers_every_frame(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    result = _benchmark_synthetic_preview(warmup=1, samples=3)
    assert result["kind"] == "synthetic_in_process"
    assert result["samples"] == 3
    assert result["dispatch_delivered"] == 3
    assert result["base64_bytes"] > result["jpeg_bytes"] > 0
    assert result["encode_latency_ms"]["p95"] > 0
    assert result["dispatch_frames_per_second"] > 0
