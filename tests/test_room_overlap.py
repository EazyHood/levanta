"""Two rooms can share floor, and the sheet must not contradict itself about it.

On the U2 apartment example rooms 2 and 5 overlap by 0.44 m2.  The title block summed the
rooms (30.99 m2) while the area schedule beside it took the union (30.55 m2), so the same
sheet published two different floor areas.  The union is the honest one.
"""

from __future__ import annotations

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
