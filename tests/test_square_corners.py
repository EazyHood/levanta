"""Wall ends meet the wall they run into: flush at corners, stopped at T-junctions.

Seen on the real TUM fr1/room sheet: the left wall (M1) ran 0.15 m past the outer face
of the top wall (M3) and drew a stub above the corner.

Thresholds written before the fix ran (metres):
- an end within REACH of a crossing wall is moved onto that wall's face, tolerance TOL;
- an L-corner ends on the *outer* face, a T-junction on the *near* face;
- openings keep their absolute position when the wall's start moves;
- in the synthetic three-room plan no wall end overshoots a crossing wall's outer face.
"""

from __future__ import annotations

import numpy as np

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.plan.tidy import square_corners
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from levanta.synthetic import sample_apartment, three_rooms

REACH = 0.35
TOL = 0.01


def _plan(walls, openings=()):
    p = FloorPlan(walls=list(walls), rooms=[], openings=list(openings), ceiling_height=2.5)
    p.rooms = [Room(id=0, name="r", polygon=[(0.05, 0.05), (3.95, 0.05), (3.95, 4.9), (0.05, 4.9)])]
    return p


def test_l_corner_overshoot_is_cut_to_the_outer_face():
    left = Wall(id=0, a=(0.0, 0.0), b=(0.0, 5.25), thickness=0.10, height=2.5)  # 0.15 past the top wall's outer face (5.10)
    top = Wall(id=1, a=(-0.05, 5.0), b=(4.0, 5.0), thickness=0.20, height=2.5)
    p = square_corners(_plan([left, top]), reach=REACH)
    assert abs(p.walls[0].b[1] - 5.10) < TOL
    assert abs(p.walls[1].a[0] - (-0.05)) < TOL  # already flush: untouched


def test_l_corner_short_end_is_extended_to_the_outer_face():
    left = Wall(id=0, a=(0.0, 0.0), b=(0.0, 4.80), thickness=0.10, height=2.5)  # stops 0.10 short of the near face
    top = Wall(id=1, a=(0.20, 5.0), b=(4.0, 5.0), thickness=0.20, height=2.5)  # and the top wall stops short of the left one
    p = square_corners(_plan([left, top]), reach=REACH)
    assert abs(p.walls[0].b[1] - 5.10) < TOL
    assert abs(p.walls[1].a[0] - (-0.05)) < TOL


def test_t_junction_stops_at_the_near_face_and_keeps_openings_in_place():
    top = Wall(id=0, a=(0.0, 5.0), b=(4.0, 5.0), thickness=0.20, height=2.5)
    part = Wall(id=1, a=(2.0, 5.08), b=(2.0, 0.0), thickness=0.10, height=2.5)  # starts inside the top wall
    door = Opening(id=0, wall_id=1, kind="door", t0=1.0, t1=1.8, z0=0.0, z1=2.05)
    y_door = part.point_at(1.0)[1]
    p = square_corners(_plan([top, part], [door]), reach=REACH)
    assert abs(p.walls[1].a[1] - 4.90) < TOL
    assert abs(p.walls[1].point_at(p.openings[0].t0)[1] - y_door) < TOL
    assert abs((p.openings[0].t1 - p.openings[0].t0) - 0.8) < 1e-9


def test_far_ends_are_left_alone():
    a = Wall(id=0, a=(0.0, 0.0), b=(0.0, 4.0), thickness=0.10, height=2.5)
    b = Wall(id=1, a=(0.0, 5.0), b=(4.0, 5.0), thickness=0.20, height=2.5)  # 1 m away: not a junction
    p = square_corners(_plan([a, b]), reach=REACH)
    assert p.walls[0].b == (0.0, 4.0)


def _overshoots(plan: FloorPlan) -> list[float]:
    out = []
    for w in plan.walls:
        for end, sign in ((w.a, -1.0), (w.b, 1.0)):
            e = np.asarray(end)
            d = w.direction * sign
            for c in plan.walls:
                if c.id == w.id or abs(float(c.direction @ w.direction)) > 0.5:
                    continue
                n = c.normal
                dn = float(d @ n)
                if abs(dn) < 0.5:
                    continue
                t_line = float((np.asarray(c.a) - e) @ n) / dn  # along d to c's centreline
                proj = e + d * t_line
                s = float((proj - np.asarray(c.a)) @ c.direction)
                if -c.thickness <= s <= c.length + c.thickness and abs(t_line) <= REACH:
                    out.append(-t_line - c.thickness / 2)  # > 0: the end is past c's outer face
    return out


def test_three_rooms_plan_has_no_overshooting_wall_ends():
    res = extract_floor_plan(sample_apartment(three_rooms(), seed=7), PlanOptions())
    over = _overshoots(res.plan)
    assert over and max(over) <= TOL, over
