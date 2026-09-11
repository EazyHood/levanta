"""A run that left nothing behind is not a run, and the sweep must say so.

On 2026-09-06 the fps sweep wrote "sweep complete" over four children that had each died
in 21-25 ms, less than Python takes to start, with zero bytes in their logs and no results.
The watcher wrote "done" on return whatever had happened.  `fps_sweep.verify` is the check
that was missing, and this file starts it against that exact case: the state those four
directories were left in has to come back as a failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
from fps_sweep import MIN_SECONDS, verify

THAT_NIGHT = Path(__file__).resolve().parent.parent / "out" / "fps_sweep_2026-09-06_empty" / "fps_1"


HEALTHY_ROWS = [{"video_id": "41069021", "noK": {"ok": True}}, {"video_id": "42897526", "noK": {"ok": True}}]


def _run(tmp_path: Path, *, rc=0, seconds=42.0, log="loaded truths\nwrote results\n", results=True, record_rc=True, rows=None, eval_only=False) -> Path:
    d = tmp_path / "fps_1"
    d.mkdir()
    rec = {"fps": 1.0, "seconds": seconds, "eval_only": eval_only}
    if record_rc:
        rec["rc"] = rc
    (d / "timing.json").write_text(json.dumps(rec), encoding="utf-8")
    (d / "sweep.log").write_text(log, encoding="utf-8")
    if results:
        (d / "results.json").write_text(json.dumps(HEALTHY_ROWS if rows is None else rows), encoding="utf-8")
    return d


def test_levanta_falling_over_inside_the_bench_is_a_failure(tmp_path):
    """The bench writes results.json even when levanta itself crashed, with the scene marked
    not ok.  That is the next way the sweep could say "done" over nothing."""
    rows = [{"video_id": "41069021", "noK": {"ok": True}}, {"video_id": "42897526", "noK": {"ok": False}}]
    assert verify(_run(tmp_path, rows=rows)) is not None


def test_a_rehearsal_is_allowed_to_evaluate_nothing(tmp_path):
    """--eval-only never runs levanta, so its rows are not ok by design and must still pass:
    the rehearsal is about the launch, not the plan."""
    rows = [{"video_id": "41069021", "noK": {"run": "noK", "ok": False}}]
    assert verify(_run(tmp_path, rows=rows, eval_only=True)) is None


def test_the_case_that_motivated_it(tmp_path):
    """Exactly what the four directories held: fps and 25 ms, nothing else."""
    d = _run(tmp_path, seconds=0.025, log="", results=False, record_rc=False)
    assert verify(d) is not None


@pytest.mark.skipif(not THAT_NIGHT.exists(), reason="the 2026-09-06 directories are not on this machine")
def test_the_real_directories_from_that_night_are_flagged():
    """The instrument is started against the known bad answer, on disk, not on a copy."""
    problem = verify(THAT_NIGHT)
    assert problem is not None, "the empty sweep of 2026-09-06 came back as a good run"


def test_a_nonzero_return_code_is_a_failure(tmp_path):
    assert verify(_run(tmp_path, rc=2)) is not None


def test_an_empty_log_is_a_failure(tmp_path):
    assert verify(_run(tmp_path, log="")) is not None


def test_a_run_shorter_than_python_startup_is_a_failure(tmp_path):
    assert verify(_run(tmp_path, seconds=MIN_SECONDS / 2)) is not None


def test_missing_results_is_a_failure(tmp_path):
    assert verify(_run(tmp_path, results=False)) is not None


def test_a_missing_return_code_is_a_failure(tmp_path):
    """The old record format cannot tell a run from nothing, so it must not pass."""
    assert verify(_run(tmp_path, record_rc=False)) is not None


def test_a_real_run_passes(tmp_path):
    """The check has to be able to say yes, or it is not a check."""
    assert verify(_run(tmp_path)) is None


def test_nothing_launched_is_a_failure(tmp_path):
    assert verify(tmp_path / "fps_1") is not None
