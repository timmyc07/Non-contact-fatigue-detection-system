"""Regression tests for the PreviewOverlayWindow metrics visibility API."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

# Keep this focused widget test runnable in CI and developer shells without a
# display server.  Respect an explicitly selected Qt platform plugin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.preview_overlay_window import PreviewOverlayWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def test_metrics_toggle_hides_and_restores_active_panels(qapp: QApplication) -> None:
    window = PreviewOverlayWindow()
    window.show_rppg_panel(True)
    window.show_fatigue_panel(True)
    window.show_fused_panel(True)
    window.show()
    qapp.processEvents()

    panels = (window._rppg_panel, window._fatigue_panel, window._fused_panel)
    assert all(panel.isVisible() for panel in panels)

    window.set_metrics_visible(False)
    qapp.processEvents()
    assert all(not panel.isVisible() for panel in panels)

    window.set_metrics_visible(True)
    qapp.processEvents()
    assert all(panel.isVisible() for panel in panels)
    window.refresh_layout()
    assert window.height() > 0
    window.close()


def test_worker_panel_state_survives_global_metrics_toggle(qapp: QApplication) -> None:
    window = PreviewOverlayWindow()
    window.show()
    qapp.processEvents()

    window.set_metrics_visible(False)
    window.show_rppg_panel(True)
    window.show_fatigue_panel(False)
    window.show_fused_panel(True)
    qapp.processEvents()
    assert not window._rppg_panel.isVisible()
    assert not window._fatigue_panel.isVisible()
    assert not window._fused_panel.isVisible()

    window.set_metrics_visible(True)
    qapp.processEvents()
    assert window._rppg_panel.isVisible()
    assert not window._fatigue_panel.isVisible()
    assert window._fused_panel.isVisible()
    window.close()
