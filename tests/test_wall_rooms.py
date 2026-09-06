"""The wall-first room builder: measured, kept behind a flag, not the default.

Round 8 asked the obvious question after round 7 found that a walked flat shows floor over
only about a third of its real area: if the floor is that thin a source, let the *walls*
define the room and let the floor only vote on which side is inside.
:mod:`levanta.plan.wall_rooms` does exactly that, and the seven-scene bench then said no.

| over the six scenes levanta stands behind | mean total error | mean per-room error | rooms matched |
|---|---|---|---|
| floor first (the default) | 19.9 % | **52.7 %** | 7 of 8 |
| walls first | **19.5 %** | 78.2 % | 6 of 8 |
| walls first, edges blocked at 25 % | 21.3 % | 61.8 % | 7 of 8 |

It ties on the total and loses room by room, which is the trap round 7 was about: on
47331964 it turns −21 % into +11 % while the one room it finds goes from −28 % to +72 %.
So the default does not move.

It stays in the tree, off by default, because the reason it loses is not a bug: it cannot
invent a wall that was never detected, and wall recall is 14-48 %. When that improves this
is the builder to re-measure, and re-deriving it would cost a round. These tests are what
keep it from rotting in the meantime.
"""

from __future__ import annotations

import pytest

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.synthetic import sample_apartment, scenes


@pytest.fixture(scope="module")
def cloud():
    return sample_apartment(scenes()["three_rooms"](), seed=7)


@pytest.fixture(scope="module")
def walls_plan(cloud):
    return extract_floor_plan(cloud, PlanOptions(rooms_from="walls")).plan


def test_it_finds_the_three_rooms_when_the_walls_are_all_there(walls_plan):
    assert len(walls_plan.rooms) == 3, [round(r.area, 1) for r in walls_plan.rooms]


def test_every_outline_is_closed_and_orthogonal(walls_plan):
    """A room is a union of rectangles cut by the wall lines, so it cannot come out open
    or with a diagonal edge; that is the whole point of building it this way."""
    for r in walls_plan.rooms:
        pts = r.polygon
        for (x0, y0), (x1, y1) in zip(pts, [*pts[1:], pts[0]], strict=True):
            assert abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6, (r.name, (x0, y0), (x1, y1))


def test_it_reports_how_it_worked(walls_plan):
    stats = walls_plan.meta.get("debug", {}).get("rooms", {})
    assert {"cells", "interior", "rooms"} <= set(stats), stats
    assert stats["interior"] <= stats["cells"]


def test_the_default_is_still_the_floor_builder(cloud):
    assert PlanOptions().rooms_from == "floor"
    plan = extract_floor_plan(cloud, PlanOptions()).plan
    assert "pockets" in plan.meta.get("debug", {}).get("rooms", {})
