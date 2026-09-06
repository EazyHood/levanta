"""General notes stay inside their column.

The notes block wrapped by counting characters (72 per line) while every other block on
the sheet measures Helvetica widths.  "No window detected. Windows need the wall under
and above them scanned." is 71 characters, so it never wrapped, and at 8.5 pt it is
302 px wide in a 260 px column: on `examples/tum_fr1_room/plan.png` it ran off the sheet
and was cut at "...above them sca".

What is checked, on the real 5-room plan (`tests/data/video_real_plan.json`) and on a note
built to be too long on purpose:
- no notes line, the block title included, reaches past the right edge of the schedule
  tables it shares its column with (tables beside the plan), past the sheet margin
  (tables below), or past the paper on a printed A4/A3 sheet;
- a wide sheet keeps the measure readable instead of setting one line per note;
- a single word wider than the whole column is broken, not left to overflow;
- the wrap loses no word, and a broken word can be read back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from levanta.io.export import fit_print_scale
from levanta.io.pdf import text_width
from levanta.io.plan2d import NOTES_MEASURE, _note_lines, floor_plan_drawing, general_notes
from levanta.plan.types import FloorPlan

DATA = Path(__file__).parent / "data" / "video_real_plan.json"
PAD = 24.0  # floor_plan_drawing's default margin at font_scale 1
SLACK = 0.5  # px: rounding in the width tables, not room to spill
COLUMN = 260.0  # the notes column beside the plan
LONG = "The plan was drawn from a single walkthrough and no side of the flat was measured twice, so every dimension on this sheet is a reconstruction and not a survey."
LONG_WORD = "supercalifragilisticexpialidocious" * 4


@pytest.fixture(scope="module")
def plan():
    return FloorPlan.from_json(DATA)


def _notes(d):
    """(left, right) px of every text drawn in the notes block."""
    return [(p.x, p.x + text_width(p.text, p.size, p.weight == "bold")) for p in d.prims if p.kind == "text" and p.cls == "notes"]


def _tables_right(d):
    """The right edge of the schedule tables: the notes share their column."""
    return max(max(x for x, _y in p.pts) for p in d.prims if p.kind in ("polyline", "polygon") and p.cls == "table")


@pytest.mark.parametrize("tables", ["right", "below"])
def test_no_note_runs_past_its_column(plan, tables):
    d = floor_plan_drawing(plan, scale=60.0, tables=tables, notes=[LONG])
    lines = _notes(d)
    assert len(lines) > len(general_notes(plan, "en", "m")) + 2  # the title, a line per note, and then some: they wrapped
    right = _tables_right(d) if tables == "right" else d.width - PAD
    for x0, x1 in lines:
        assert x1 <= right + SLACK, (x0, x1, right)
        assert x0 >= PAD - SLACK, (x0, x1)


def test_a_wide_sheet_does_not_run_a_note_across_the_page(plan):
    """Room in the column is not a reason to set a note 300 characters wide."""
    d = floor_plan_drawing(plan, scale=140.0, tables="below", notes=[LONG])
    for x0, x1 in _notes(d):
        assert x1 - x0 <= NOTES_MEASURE + SLACK, (x0, x1)


def test_no_note_runs_off_the_printed_page(plan):
    """Both papers, both languages: what fit_print_scale returns is what gets printed."""
    for paper in ("A4", "A3"):
        for lang in ("en", "es"):
            d, *_rest = fit_print_scale(plan, paper, "landscape", lang=lang, notes=[LONG])
            for _x0, x1 in _notes(d):
                assert x1 <= d.width, (paper, lang, x1, d.width)


def test_a_word_wider_than_the_column_is_broken_not_overflowed(plan):
    d = floor_plan_drawing(plan, scale=60.0, notes=[LONG_WORD])
    right = _tables_right(d)
    for _x0, x1 in _notes(d):
        assert x1 <= right + SLACK, (x1, right)


def test_the_wrap_loses_no_word():
    (dx, first), *rest = _note_lines([LONG], COLUMN, 1.0)
    assert dx == 0.0 and first.startswith("1. ")
    assert len(rest) >= 1
    assert " ".join([first[3:], *(ln for _dx, ln in rest)]) == LONG


def test_a_broken_word_can_be_read_back():
    lines = [ln for _dx, ln in _note_lines([LONG_WORD], COLUMN, 1.0)]
    assert len(lines) > 1
    joined = "".join(ln[:-1] if ln.endswith("-") else ln for ln in lines)
    assert joined.removeprefix("1. ") == LONG_WORD
