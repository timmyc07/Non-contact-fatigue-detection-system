from __future__ import annotations

from types import SimpleNamespace
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.fatigue_engine import _norm_blend  # noqa: E402
from rppg.rppg_worker import _face_quality_from_pose, _roi_weights_from_pose  # noqa: E402


def _fake_landmarks() -> list[SimpleNamespace]:
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[1] = SimpleNamespace(x=0.50, y=0.45)
    pts[10] = SimpleNamespace(x=0.50, y=0.20)
    pts[152] = SimpleNamespace(x=0.50, y=0.82)
    pts[234] = SimpleNamespace(x=0.34, y=0.52)
    pts[454] = SimpleNamespace(x=0.66, y=0.52)
    pts[33] = SimpleNamespace(x=0.38, y=0.36)
    pts[263] = SimpleNamespace(x=0.62, y=0.38)
    for idx in (338, 297, 332, 284, 251, 389, 356, 323, 361, 288, 397, 365, 379, 378, 400, 377, 148, 176, 149, 150, 136, 172, 58, 132, 93, 127, 162, 21, 54, 103, 67, 109):
        pts[idx] = SimpleNamespace(x=0.50, y=0.35)
    return pts


def test_roi_weights_are_normalised() -> None:
    lm = _fake_landmarks()
    weights = _roi_weights_from_pose(8.0, 12.0, 4.0, lm, 640, 480)

    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["L_cheek"] != weights["R_cheek"]


def test_quality_score_penalises_motion() -> None:
    base = _face_quality_from_pose(5.0, 5.0, 2.0, 0.12, 0.05, 1.0)
    moved = _face_quality_from_pose(5.0, 5.0, 2.0, 0.12, 1.20, 1.0)

    assert 0.0 <= moved < base <= 1.0


def test_blendshape_normalisation_uses_baseline() -> None:
    assert _norm_blend(0.65, 0.15) > _norm_blend(0.35, 0.15)
    assert _norm_blend(0.10, 0.15) == 0.0
