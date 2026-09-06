"""Tidying must not mistake a partition wall for furniture.

Measured on the apartment benchmark with a *perfect* cloud (exact depth, exact poses):
of the wall that is present in the cloud, the planner turned 29 % into walls, and turning
`tidy_walls` off raised the wall recall from 36 % to 48 % and the precision from 65 % to
75 %. The mechanism: when the rooms come out fused (one open room over the whole flat),
every partition inside that room looks like a piece standing "inside a room" — the test
for furniture — and is set aside. Fewer partitions then fuse the rooms further.

Thresholds written before the fix ran, on the shapes below:
- a 3 m partition that crosses a room from wall to wall is kept;
- a 0.9 m piece standing inside the room (a desk front) is still set aside;
- a partition that reaches only one wall and stops (a 2.5 m kitchen island back) is kept
  when it is long, dropped when it is short.
"""

from __future__ import annotations

from levanta.plan.tidy import tidy_walls
from levanta.plan.types import FloorPlan, Room, Wall


def _plan(walls):
    room = Room(id=0, name="open", polygon=[(0.0, 0.0), (8.0, 0.0), (8.0, 5.0), (0.0, 5.0)], closed=False)
    return FloorPlan(walls=list(walls), rooms=[room], openings=[], ceiling_height=2.5)


def _ids(plan):
    return {round(w.length, 2) for w in plan.walls}


def test_a_partition_across_the_room_survives():
    perimeter = [
        Wall(id=0, a=(0.0, 0.0), b=(8.0, 0.0), thickness=0.2, height=2.5),
        Wall(id=1, a=(8.0, 0.0), b=(8.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=2, a=(8.0, 5.0), b=(0.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=3, a=(0.0, 5.0), b=(0.0, 0.0), thickness=0.2, height=2.5),
    ]
    partition = Wall(id=4, a=(4.0, 0.1), b=(4.0, 3.1), thickness=0.1, height=2.5)  # 3 m, from the south wall inwards
    out = tidy_walls(_plan([*perimeter, partition]))
    kept = _ids(out)
    assert 3.0 in kept or any(abs(w.length - 3.0) < 0.4 for w in out.walls), sorted(kept)
    assert len(out.walls) >= 5


def test_a_short_piece_inside_the_room_is_still_set_aside():
    perimeter = [
        Wall(id=0, a=(0.0, 0.0), b=(8.0, 0.0), thickness=0.2, height=2.5),
        Wall(id=1, a=(8.0, 0.0), b=(8.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=2, a=(8.0, 5.0), b=(0.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=3, a=(0.0, 5.0), b=(0.0, 0.0), thickness=0.2, height=2.5),
    ]
    desk = Wall(id=4, a=(3.0, 2.5), b=(3.9, 2.5), thickness=0.1, height=2.5)  # 0.9 m, floating
    out = tidy_walls(_plan([*perimeter, desk]))
    assert all(abs(w.length - 0.9) > 0.2 for w in out.walls), [round(w.length, 2) for w in out.walls]
    assert any(abs(w.length - 0.9) < 0.2 for w in out.extra_walls)


def test_a_long_stub_from_a_wall_is_kept_a_short_one_is_not():
    perimeter = [
        Wall(id=0, a=(0.0, 0.0), b=(8.0, 0.0), thickness=0.2, height=2.5),
        Wall(id=1, a=(8.0, 0.0), b=(8.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=2, a=(8.0, 5.0), b=(0.0, 5.0), thickness=0.2, height=2.5),
        Wall(id=3, a=(0.0, 5.0), b=(0.0, 0.0), thickness=0.2, height=2.5),
    ]
    long_stub = Wall(id=4, a=(6.0, 4.9), b=(6.0, 2.4), thickness=0.1, height=2.5)  # 2.5 m from the north wall
    short_stub = Wall(id=5, a=(2.0, 4.9), b=(2.0, 4.3), thickness=0.1, height=2.5)  # 0.6 m
    out = tidy_walls(_plan([*perimeter, long_stub, short_stub]))
    assert any(abs(w.length - 2.5) < 0.4 for w in out.walls), [round(w.length, 2) for w in out.walls]
    assert all(abs(w.length - 0.6) > 0.2 for w in out.walls)
