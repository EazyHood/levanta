"""Two rooms can share floor, and the sheet must not contradict itself about it.

On the U2 apartment example rooms 2 and 5 overlap by 0.44 m2.  The title block summed the
rooms (30.99 m2) while the area schedule beside it took the union (30.55 m2), so the same
sheet published two different floor areas.  The union is the honest one.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from levanta.plan.types import FloorPlan, Room


def _plan(*rings) -> FloorPlan:
    rooms = [Room(id=i, name=f"Room {i + 1}", polygon=list(r)) for i, r in enumerate(rings)]
    return FloorPlan(walls=[], openings=[], ceiling_height=2.5, rooms=rooms)


SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4)]


def test_rooms_that_do_not_touch_are_just_added():
    plan = _plan(SQUARE, [(10, 0), (12, 0), (12, 2), (10, 2)])
    assert plan.total_area == 20.0


def test_shared_floor_is_counted_once():
    plan = _plan(SQUARE, [(3, 0), (7, 0), (7, 4), (3, 4)])
    assert sum(r.area for r in plan.rooms) == 32.0
    assert plan.total_area == 28.0  # the 4 m2 they share, once


def test_the_overlap_is_reported_not_hidden():
    plan = _plan(SQUARE, [(3, 0), (7, 0), (7, 4), (3, 4)])
    check = next(c for c in plan.quality("en") if c["key"] == "rooms_overlap")
    assert "4.00" in check["text"] and check["level"] == "warn", check


def test_no_warning_when_nothing_is_shared():
    plan = _plan(SQUARE, [(10, 0), (12, 0), (12, 2), (10, 2)])
    assert "rooms_overlap" not in {c["key"] for c in plan.quality("en")}


def test_the_planner_does_not_hand_out_shared_floor():
    """`_unshare_floor` runs in the pipeline, so a plan should never reach the sheet with two
    rooms on one floor.  Measured when it was added: nine of ten plans had an overlap of
    zero and one had 2.29 m2, which was the whole difference between the bench's 17 % and
    19 % mean area error.  The old number was flattered by counting floor twice."""
    from levanta.plan.pipeline import _unshare_floor

    a = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    b = Polygon([(3, 0), (7, 0), (7, 4), (3, 4)])
    out = _unshare_floor([(a, True), (b, True)])
    areas = sorted(g.area for g, _ in out)
    assert areas == [12.0, 16.0], areas  # the smaller keeps its floor, the bigger gives it up
    assert out[0][0].intersection(out[1][0]).area < 1e-9


def test_unsharing_leaves_a_clean_plan_alone():
    from levanta.plan.pipeline import _unshare_floor

    a = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    b = Polygon([(10, 0), (12, 0), (12, 2), (10, 2)])
    out = _unshare_floor([(a, True), (b, True)])
    assert [round(g.area, 6) for g, _ in out] == [16.0, 4.0]
