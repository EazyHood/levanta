"""The coverage number the sheet prints must not measure the point spacing.

`Room.floor_seen` says how much of a room's outline rests on floor that was actually seen.
The first two attempts measured the instrument instead: counting the 2 cm cells that hold a
point scored a fully visible floor at 30 % (the cloud is voxel-downsampled at 2 cm, so most
cells are empty by construction), and growing a 10 cm disc around every point scored a
sparse real scene at 82 % by turning one lone point into a hundred cells.

So the control comes first: the synthetic apartment's floor is modelled in full and sampled
from a camera path with no furniture to hide it, and it has to come out at ~100 %.
"""

from __future__ import annotations

import numpy as np
import pytest

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.plan.wall_rooms import seen_floor_fraction
from levanta.synthetic import sample_apartment, scenes


@pytest.fixture(scope="module")
def result():
    return extract_floor_plan(sample_apartment(scenes()["three_rooms"](), seed=7), PlanOptions())


def test_a_floor_that_was_fully_seen_scores_nearly_everything(result):
    seen = [r.floor_seen for r in result.plan.rooms]
    assert all(s is not None and s > 0.95 for s in seen), seen


def test_the_number_is_not_the_voxel_spacing(result):
    """The raw 2 cm cells cover under half of a floor that was seen completely, which is
    what makes the 10 cm square, and not the cell, the right unit."""
    grid, floor = result.grid, result.rasters["floor"]
    room = max(result.plan.rooms, key=lambda r: r.area).shapely
    raw = seen_floor_fraction(room, floor, grid, reach=grid.cell)
    binned = seen_floor_fraction(room, floor, grid, reach=0.10)
    assert raw < 0.5 < binned, (raw, binned)


def test_unseen_floor_pulls_it_down():
    """A room whose floor was never seen must not score like one that was."""
    res = extract_floor_plan(sample_apartment(scenes()["three_rooms"](), seed=7), PlanOptions())
    room = max(res.plan.rooms, key=lambda r: r.area).shapely
    empty = np.zeros_like(res.rasters["floor"])
    assert seen_floor_fraction(room, empty, res.grid) == 0.0


def test_it_reaches_the_sheet_and_the_checks(result):
    """The number is only useful where the reader is: on the plan and in the QA list."""
    from levanta.io.plan2d import room_label_specs

    assert all("floor_seen" in r.__dict__ for r in result.plan.rooms)
    specs = room_label_specs(result.plan, scale=40.0, lang="en", units="m", fs=1.0)
    assert specs, "rooms must still get labels"
    keys = {c["key"] for c in result.plan.quality("en")}
    assert "floor_seen" not in keys, "a fully seen floor must not raise the warning"


def test_the_warning_fires_when_the_outline_is_mostly_inferred():
    """The point of the number is the warning it raises; a plan where it never fires is a
    plan that hides the problem."""
    from levanta.plan.types import FloorPlan, Room

    thin = FloorPlan(walls=[], openings=[], ceiling_height=2.5, rooms=[Room(id=0, name="Room 1", polygon=[(0, 0), (3, 0), (3, 3), (0, 3)], floor_seen=0.2)])
    check = next(c for c in thin.quality("en") if c["key"] == "floor_seen")
    assert "20 %" in check["text"] and check["level"] == "warn", check
