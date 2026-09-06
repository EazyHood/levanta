"""The same wall seen twice is drawn once.

The TUM sheet came back with M2 running parallel to M1 at 0.39 m: the west wall detected
twice, once from the wall surface and once from something against it. On a sheet that
reads as a phantom partition, which is the complaint that started the tidy pass.

A real partition is never a second wall 0.4 m from another one *seen from the same side*:
when a wall is seen from both faces the detector measures its thickness and emits one wall.

Thresholds written before the fix ran:
- of two parallel walls closer than GAP with more than OVERLAP of the shorter one covered,
  the longer survives and the shorter goes to `extra_walls`;
- walls further apart than GAP are both kept (a real corridor);
- a wall measured from both sides (`sides_seen == 2`) is never dropped.
"""

from __future__ import annotations

from levanta.plan.tidy import drop_duplicate_walls
from levanta.plan.types import FloorPlan, Wall

GAP = 0.5
OVERLAP = 0.6


def _plan(walls):
    return FloorPlan(walls=list(walls), rooms=[], openings=[], ceiling_height=2.5)


def test_the_shorter_of_two_parallel_walls_goes():
    long_wall = Wall(id=0, a=(0.0, 0.0), b=(0.0, 5.8), thickness=0.1, height=2.5)
    ghost = Wall(id=1, a=(0.39, 0.1), b=(0.39, 3.8), thickness=0.1, height=2.5)
    out = drop_duplicate_walls(_plan([long_wall, ghost]))
    assert [round(w.length, 2) for w in out.walls] == [5.8]
    assert [round(w.length, 2) for w in out.extra_walls] == [3.7]


def test_two_walls_a_metre_apart_are_both_real():
    a = Wall(id=0, a=(0.0, 0.0), b=(0.0, 5.0), thickness=0.1, height=2.5)
    b = Wall(id=1, a=(1.2, 0.0), b=(1.2, 4.0), thickness=0.1, height=2.5)
    out = drop_duplicate_walls(_plan([a, b]))
    assert len(out.walls) == 2


def test_a_wall_measured_from_both_sides_survives():
    thick = Wall(id=0, a=(0.0, 0.0), b=(0.0, 3.0), thickness=0.12, height=2.5, sides_seen=2)
    longer = Wall(id=1, a=(0.3, -0.5), b=(0.3, 5.0), thickness=0.1, height=2.5)
    out = drop_duplicate_walls(_plan([thick, longer]))
    assert len(out.walls) == 2


def test_walls_that_barely_overlap_are_both_kept():
    a = Wall(id=0, a=(0.0, 0.0), b=(0.0, 4.0), thickness=0.1, height=2.5)
    b = Wall(id=1, a=(0.35, 4.2), b=(0.35, 6.0), thickness=0.1, height=2.5)  # no overlap at all
    out = drop_duplicate_walls(_plan([a, b]))
    assert len(out.walls) == 2


def test_openings_move_with_the_wall_that_survives():
    from levanta.plan.types import Opening

    long_wall = Wall(id=0, a=(0.0, 0.0), b=(0.0, 5.0), thickness=0.1, height=2.5)
    ghost = Wall(id=1, a=(0.4, 0.5), b=(0.4, 3.5), thickness=0.1, height=2.5)
    plan = FloorPlan(walls=[long_wall, ghost], rooms=[], openings=[Opening(id=0, wall_id=0, kind="door", t0=1.0, t1=1.9, z0=0.0, z1=2.05)], ceiling_height=2.5)
    out = drop_duplicate_walls(plan)
    assert len(out.walls) == 1 and out.openings and out.openings[0].wall_id == out.walls[0].id
