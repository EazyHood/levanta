"""Cleaning a raw detection into a presentable plan."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from levanta.plan.occupancy import Grid
from levanta.plan.tidy import (
    close_outline_gaps,
    drop_stubs,
    orthogonal_edges_ok,
    simplify_orthogonal,
    snap_edges_to_walls,
    tidy_walls,
)
from levanta.plan.types import FloorPlan, Opening, Room, Wall


def test_simplify_orthogonal_removes_furniture_bites():
    # a 4 x 3 room with a 0.6 m deep, 1.0 m wide bite in the bottom edge
    poly = Polygon([(0, 0), (1.5, 0), (1.5, 0.6), (2.5, 0.6), (2.5, 0), (4, 0), (4, 3), (0, 3)])
    out = simplify_orthogonal(poly, min_edge=0.9)
    assert orthogonal_edges_ok(out)
    assert len(out.exterior.coords) - 1 == 4 and abs(out.area - 12.0) < 1e-6


def test_simplify_keeps_real_l_shape():
    poly = Polygon([(0, 0), (4, 0), (4, 2), (2, 2), (2, 3), (0, 3)])  # a 2 m jog stays
    out = simplify_orthogonal(poly, min_edge=0.9)
    assert len(out.exterior.coords) - 1 == 6 and abs(out.area - poly.area) < 1e-9


def test_snap_edges_to_walls_reaches_the_wall_behind_a_desk():
    poly = Polygon([(0, 0.7), (4, 0.7), (4, 3), (0, 3)])  # floor seen only 0.7 m from the south wall
    walls = [(np.array([0.0, -0.1]), np.array([4.0, -0.1]), 0.2)]  # south wall, inner face at y = 0
    out = snap_edges_to_walls(poly, walls, max_dist=1.0)
    assert abs(out.bounds[1] - 0.0) < 1e-6 and abs(out.area - 12.0) < 1e-6
    # a wall too far away is ignored
    out2 = snap_edges_to_walls(poly, [(np.array([0.0, -2.0]), np.array([4.0, -2.0]), 0.2)], max_dist=1.0)
    assert abs(out2.area - poly.area) < 1e-9


def _room_plan() -> FloorPlan:
    room = Room(0, "R", [(0, 0), (4, 0), (4, 3), (0, 3)], closed=False)
    walls = [
        Wall(0, (0, -0.1), (4, -0.1), 0.2, 2.5),  # south, bounding
        Wall(1, (-0.1, 0), (-0.1, 1.2), 0.2, 2.5),  # west, lower piece
        Wall(2, (-0.1, 2.0), (-0.1, 3.0), 0.2, 2.5),  # west, upper piece (0.8 m gap = door)
        Wall(3, (6.0, 0), (6.0, 3), 0.2, 2.5),  # debris 2 m away
        Wall(4, (1.0, 1.0), (2.5, 1.0), 0.1, 2.5),  # desk front inside the room
        Wall(5, (0.4, 0.5), (0.4, 0.9), 0.1, 2.5),  # stub crossing nothing, touching nothing
        Wall(6, (4, -0.1), (9, -0.1), 0.2, 2.5),  # south wall continuing far to the east
    ]
    return FloorPlan(walls=walls, rooms=[room], openings=[Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05)], ceiling_height=2.5)


def test_tidy_walls_keeps_bounding_walls_and_sets_the_rest_aside():
    plan = tidy_walls(_room_plan(), attach_dist=0.2, trim_margin=0.1)
    kept = {(round(w.a[0], 1), round(w.a[1], 1), round(w.b[0], 1), round(w.b[1], 1)) for w in plan.walls}
    assert (0.0, -0.1, 4.0, -0.1) in kept  # south wall untouched
    assert all(w.b[0] <= 4.5 for w in plan.walls)  # the eastward continuation was trimmed
    assert not any(abs(w.a[1] - 1.0) < 1e-6 and abs(w.b[1] - 1.0) < 1e-6 for w in plan.walls)  # desk front gone
    assert not any(abs(w.a[0] - 6.0) < 1e-6 for w in plan.walls)  # debris gone
    assert len(plan.extra_walls) >= 2
    assert plan.openings and plan.openings[0].wall_id == 0 and abs(plan.openings[0].width - 0.9) < 1e-9


def test_drop_stubs_removes_unattached_short_pieces():
    plan = drop_stubs(_room_plan(), max_len=0.6)
    assert not any(abs(w.a[0] - 0.4) < 1e-6 for w in plan.walls)
    assert any(abs(w.a[1] + 0.1) < 1e-6 for w in plan.walls)


def test_close_outline_gaps_makes_a_door_where_the_camera_looked_through():
    plan = tidy_walls(_room_plan(), attach_dist=0.2, trim_margin=0.1)
    grid = Grid(-1.0, -1.0, 0.05, 120, 100)
    free = np.zeros(grid.shape, dtype=bool)
    ix, iy = grid.to_index(np.array([[x, y] for y in np.linspace(1.2, 2.0, 30) for x in (-0.08, -0.02, 0.02, 0.08)]))
    free[iy, ix] = True  # rays crossed the west gap
    plan = close_outline_gaps(plan, free, grid, door_range=(0.55, 1.3), free_min=0.35)
    doors = [o for o in plan.openings if o.kind == "door"]
    assert len(doors) == 2
    new = plan.walls[doors[-1].wall_id]
    assert abs(new.a[0] + 0.1) < 0.02 and abs(doors[-1].width - 0.8) < 0.15
    # without line of sight the same gap stays an unscanned side
    plan2 = close_outline_gaps(tidy_walls(_room_plan(), attach_dist=0.2, trim_margin=0.1), np.zeros(grid.shape, bool), grid)
    assert len([o for o in plan2.openings if o.kind == "door"]) == 1
