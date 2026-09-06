"""An open room's outline reaches the walls that were seen, not only the floor that was.

On ARKitScenes (real iPhone scans made to capture objects, not walls) levanta's rooms came
out 22-44 % smaller than the LiDAR floor at the right scale: the seen floor stops a metre
or two short of a wall that *was* detected, and the outline stopped with it because edges
only snapped to walls within 1.0 m and the farthest-overlapping wall won over the nearest.

Thresholds written before the fix ran (metres):
- an edge snaps to a parallel wall up to REACH away when the wall covers at least
  MIN_OVERLAP of the edge;
- among candidates the wall that covers most of the edge wins, ties by distance;
- a short stub covering less than MIN_OVERLAP is ignored.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from levanta.plan.tidy import snap_edges_to_walls

REACH = 2.5
MIN_OVERLAP = 0.35
TOL = 0.01


def _seg(a, b, th=0.1):
    return (np.array(a, float), np.array(b, float), th)


def test_edge_reaches_a_wall_two_metres_out():
    seen = Polygon([(0, 0), (4, 0), (4, 3), (0, 3)])
    wall = _seg((6.0, -0.5), (6.0, 2.5))  # 2.0 m right of the right edge, covers 2.5 of 3.0 m
    out = snap_edges_to_walls(seen, [wall], max_dist=REACH, min_overlap=MIN_OVERLAP)
    assert abs(out.bounds[2] - 5.95) < TOL  # inner face of the wall (centreline 6.0, thickness 0.1)
    assert abs(out.bounds[0] - 0.0) < TOL and abs(out.bounds[3] - 3.0) < TOL


def test_the_wall_that_covers_most_of_the_edge_wins():
    """Measured on seven scenes (bench/planner_sweep.py): preferring the nearest wall is
    worse or equal on every one of them, and it shrank the TUM room by 2 m2 and its walls
    by 2 m."""
    seen = Polygon([(0, 0), (4, 0), (4, 3), (0, 3)])
    near = _seg((5.0, 0.5), (5.0, 2.0))  # 1.0 m out, covers 1.5 / 3.0 = 50 %
    far = _seg((6.5, -1.0), (6.5, 4.0))  # 2.5 m out, covers 100 %
    out = snap_edges_to_walls(seen, [near, far], max_dist=REACH, min_overlap=MIN_OVERLAP)
    assert abs(out.bounds[2] - 6.45) < TOL


def test_a_stub_is_ignored_and_walls_behind_the_reach_too():
    seen = Polygon([(0, 0), (4, 0), (4, 3), (0, 3)])
    stub = _seg((5.0, 1.0), (5.0, 1.6))  # 20 % of the edge
    beyond = _seg((7.0, -1.0), (7.0, 4.0))  # 3.0 m out
    out = snap_edges_to_walls(seen, [stub, beyond], max_dist=REACH, min_overlap=MIN_OVERLAP)
    assert abs(out.bounds[2] - 4.0) < TOL
