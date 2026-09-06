"""Things a plan can say that are impossible on their face.

A benchmark only sees the scenes it has, and a scene can be too easy to contain the failure:
the synthetic apartment is a closed box, so it passes with planner changes the seven-scene
bench measures at twice the area error.  A plan that contradicts *itself* does so on any
scene, needs no ground truth, and costs a subtraction.

One of these was found on the published U2 apartment the day they were written: rooms
sharing 0.44 m² of floor, which is real (four other plans overlap by exactly 0.0000 m²).  A
second alarm on the same sheet, a room with no door, was **the checker being wrong**: that
room is the open end of a corridor and you walk into it.  Both directions are tested here,
because a check that cannot be quiet is not a check.
"""

from __future__ import annotations

import math

import pytest

from levanta.plan.types import FloorPlan, Opening, Room, Wall


def _plan(rooms=(), walls=(), openings=()) -> FloorPlan:
    return FloorPlan(walls=list(walls), openings=list(openings), ceiling_height=2.5, rooms=list(rooms))


def _room(i, ring, name=None) -> Room:
    return Room(id=i, name=name or f"Room {i + 1}", polygon=list(ring))


SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4)]


def keys(plan: FloorPlan) -> set[str]:
    return {c["key"] for c in plan.quality("en")}


def test_a_clean_plan_claims_nothing_impossible():
    wall = Wall(id=0, a=(0.0, 0.0), b=(4.0, 0.0), thickness=0.1, height=2.5)
    door = Opening(id=0, wall_id=0, kind="door", t0=1.0, t1=1.8, z0=0.0, z1=2.05)
    plan = _plan([_room(0, SQUARE)], [wall], [door])
    assert not ({"rooms_overlap", "room_no_way_in", "opening_orphan", "impossible_geometry"} & keys(plan))


def _box_walls(x0=0.0, y0=0.0, x1=4.0, y1=4.0) -> list[Wall]:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [Wall(id=i, a=corners[i], b=corners[(i + 1) % 4], thickness=0.1, height=2.5) for i in range(4)]


def test_a_room_walled_all_round_with_no_opening_is_reported():
    """Enclosed on every side and no door anywhere: that is a room nobody can enter."""
    plan = _plan([_room(0, SQUARE)], _box_walls(), [])
    assert "room_no_way_in" in keys(plan)


def test_a_room_open_to_the_next_one_is_not_reported():
    """The check said the published U2 apartment had a room nobody could enter.  It did not:
    Room 5 is the open end of a corridor, 4 % of its outline on a wall and 21 % touching the
    room next door.  An open plan has no door because it needs none."""
    plan = _plan([_room(0, SQUARE)], _box_walls()[:1], [])
    assert "room_no_way_in" not in keys(plan)


def test_an_opening_on_a_wall_that_does_not_exist_is_reported():
    plan = _plan([_room(0, SQUARE)], [], [Opening(id=0, wall_id=7, kind="door", t0=1.0, t1=1.8, z0=0.0, z1=2.05)])
    assert "opening_orphan" in keys(plan)


def test_two_rooms_sharing_floor_are_reported():
    plan = _plan([_room(0, SQUARE), _room(1, [(3, 0), (7, 0), (7, 4), (3, 4)])])
    assert "rooms_overlap" in keys(plan)


def test_a_hand_sized_overlap_is_reported_too():
    """The threshold is a square millimetre, so 4 sq cm is not a rounding error: it is floor
    counted twice.  It used to be 0.05 sq m, which let this through."""
    plan = _plan([_room(0, SQUARE), _room(1, [(3.99, 0), (8, 0), (8, 4), (3.99, 4)])])
    assert "rooms_overlap" in keys(plan)


def test_float_noise_does_not_fire():
    """Two rooms sharing an edge and nothing else must stay quiet: measured over ten plans
    the excess is exactly 0.0 eight times and 1.4e-14 once."""
    plan = _plan([_room(0, SQUARE), _room(1, [(4, 0), (8, 0), (8, 4), (4, 4)])])
    assert "rooms_overlap" not in keys(plan)


@pytest.mark.parametrize(
    ("tag", "ring"),
    [
        ("a sliver with a huge perimeter for its area", [(0, 0), (60, 0), (60, 0.02), (0, 0.02)]),
        ("no area at all", [(0, 0), (4, 0), (4, 0), (0, 0)]),
    ],
)
def test_a_shape_that_contradicts_itself_is_reported(tag, ring):
    plan = _plan([_room(0, ring)])
    assert "impossible_geometry" in keys(plan), tag


def test_the_circle_is_the_floor_for_a_perimeter():
    """No shape of area A has a perimeter under the circle's, so the check must not fire on
    the tightest legal case."""
    r = 2.0
    ring = [(r * math.cos(a), r * math.sin(a)) for a in [i * math.tau / 256 for i in range(256)]]
    plan = _plan([_room(0, ring)])
    assert "impossible_geometry" not in keys(plan)
