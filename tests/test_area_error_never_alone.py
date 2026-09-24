"""No bench prints an area error from a reconstruction without its scale beside it.

Four times in this project a respectable area figure was two errors of opposite sign; the
fourth, in the fps sweep of 2026-09-24, was a −15 % made of a plan 2.2 times too big and a
shape 83 % short.  The supervisor's ask was that no levanta report can print the area error
without its scale component, by construction, the way the planner bench no longer prints an
aggregate of the room count.  `bench/area_report.py` is the one place that formats it; this
file fails when any bench formats an area error anywhere else.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))
from area_report import (  # noqa: E402
    EXEMPT_REASON,
    area_shape,
    area_vs_reference,
    area_with_scale,
    shape_pct,
)

# benches whose clouds come from exact depth and exact poses: nothing was reconstructed
EXEMPT = {"coverage_sweep.py": EXEMPT_REASON, "ideal_input.py": EXEMPT_REASON}

AREA_KEY = re.compile(r"area\w*error\w*_pct|\berror_pct\b")
FORMATTED = re.compile(r":[+ ]?\d*\.\d+f\}")
THROUGH_THE_HELPER = ("area_with_scale(", "area_shape(", "area_vs_reference(", "_area(")


def _offending_lines(path: Path) -> list[str]:
    bad = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if AREA_KEY.search(line) and FORMATTED.search(line) and not any(h in line for h in THROUGH_THE_HELPER):
            bad.append(f"{path.name}:{n}: {line.strip()}")
    return bad


def test_no_bench_formats_an_area_error_on_its_own():
    offending = []
    for path in sorted(BENCH.glob("*.py")):
        if path.name == "area_report.py" or path.name in EXEMPT:
            continue
        offending += _offending_lines(path)
    assert not offending, "area error printed without its scale:\n" + "\n".join(offending)


def test_the_check_catches_the_line_that_started_this(tmp_path):
    """The fps sweep's own table before the fix: it has to be flagged, or the check is blind."""
    old = tmp_path / "old_fps_sweep.py"
    old.write_text("x = f\"| {_fmt(r['area_error_pct'], '{:+.0f} %')} | {_fmt(r['rooms'], '{:d}')} |\"\n"
                   "y = f\"{r['max_views']} | {r['area_total_error_pct']:+.0f} % |\"\n", encoding="utf-8")
    assert len(_offending_lines(old)) == 2


def test_a_wrapper_named_like_the_helper_really_uses_it():
    """`_area(` is accepted as a way through, so every bench that defines one must build it on
    `bench/area_report.py`, or the name alone would let a raw figure out."""
    for path in BENCH.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "def _area(" in src:
            body = src.split("def _area(", 1)[1].split("\ndef ", 1)[0]
            assert "from area_report import" in body, path.name


def test_the_fourth_case_decomposes_as_the_report_says():
    assert "shape -83 %" in area_with_scale(-15.4, 0.45)
    assert "scale 0.45" in area_with_scale(-15.4, 0.45)


def test_a_missing_scale_is_refused_not_hidden():
    with pytest.raises(ValueError):
        area_with_scale(-15.0, None)
    with pytest.raises(ValueError):
        area_shape(-15.0, None)
    assert area_with_scale(None, None) == "—"
    assert "same cloud" in area_vs_reference(2.0)


SWEEP = Path(__file__).resolve().parent.parent / "out" / "fps_sweep"


@pytest.mark.skipif(not (SWEEP / "fps_4" / "results.json").exists(), reason="the 2026-09 sweep is not on this machine")
def test_the_decomposition_matches_the_benchs_own_definition():
    """`arkitscenes.py` defines the scale-corrected area as levanta's area times s squared;
    the helper must agree with it on the real rows, not just on the example."""
    for fps in ("1", "2", "4", "8"):
        for r in json.loads((SWEEP / f"fps_{fps}" / "results.json").read_text(encoding="utf-8")):
            k = r["noK"]
            assert shape_pct(k["area_error_pct"], k["scale_factor"]) == pytest.approx(k["area_error_scaled_pct"], abs=1e-6), (fps, r["video_id"])


@pytest.mark.skipif(not (SWEEP / "fps_8" / "results.json").exists(), reason="the 2026-09 sweep is not on this machine")
def test_the_sweep_table_now_prints_the_scale_on_every_row():
    from fps_sweep import collect, table

    rows = [line for line in table(collect(SWEEP)).splitlines()[2:] if line.strip()]
    assert len(rows) == 8
    assert all("shape" in line and "scale" in line for line in rows)
