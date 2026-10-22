from __future__ import annotations

from scripts.desktop_engine_benchmark import (
    _benchmark_synthetic_preview,
    _distribution,
    _expand_process_tree,
)
from scripts import desktop_engine_benchmark as benchmark


def test_distribution_reports_expected_percentiles() -> None:
    result = _distribution([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result == {"min": 1.0, "p50": 3.0, "p95": 5.0, "max": 5.0, "mean": 3.0}


def test_expand_process_tree_follows_nested_children_once() -> None:
    assert _expand_process_tree(10, {11: 10, 12: 11, 13: 99, 14: 12}) == [10, 11, 12, 14]


def test_macos_memory_measurement_includes_children_and_converts_kib(monkeypatch):
    monkeypatch.setattr(benchmark.sys, "platform", "darwin")

    def ps(command, **kwargs):
        if command[1] == "-axo":
            return "10 1\n11 10\n12 11\n13 1\n"
        return {"10": "100\n", "11": "200\n", "12": "300\n"}[command[-1]]

    monkeypatch.setattr(benchmark.subprocess, "check_output", ps)
    assert benchmark._process_tree_rss_bytes(10) == ([10, 11, 12], 600 * 1024)


def test_synthetic_preview_benchmark_delivers_every_frame(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    result = _benchmark_synthetic_preview(warmup=1, samples=3)
    assert result["kind"] == "synthetic_in_process"
    assert result["samples"] == 3
    assert result["dispatch_delivered"] == 3
    assert result["base64_bytes"] > result["jpeg_bytes"] > 0
    assert result["encode_latency_ms"]["p95"] > 0
    assert result["dispatch_frames_per_second"] > 0
