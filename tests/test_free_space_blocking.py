"""A sight line may be stopped by evidence it did not produce itself.

`free_space_raster` marks every cell a camera-to-point ray crosses.  A ray only knows where
*it* ended, so one aimed past the edge of a wall walks through that wall's cells and calls
them free, while another ray's points sit in exactly those cells.  Measured on the Replica
flat, that is how the interior leaves the building: of the crossing front, 61 % has a real
wall levanta did not draw, and 80 % of those cells have wall points within 0.25 m.

The `occupied` argument cuts each ray at the first cell it marks.  It is off by default
because the seven-scene bench says the crude version costs more than it saves (wall recall
31 % to 25 %, and the published TUM example breaks by 9 %), but the machinery is measured
and kept for a version that blocks on strong evidence only.
"""

from __future__ import annotations

import numpy as np

from levanta.plan.occupancy import Grid, free_space_raster


def _grid() -> Grid:
    return Grid(x0=0.0, y0=0.0, cell=0.1, nx=40, ny=20)


def test_an_unblocked_ray_marks_the_whole_line():
    grid = _grid()
    cams = np.array([[0.2, 1.0]])
    pts = np.array([[3.5, 1.0]])
    free = free_space_raster(grid, pts, cams, seed=0)
    ix, iy = grid.to_index(np.array([[1.0, 1.0], [3.0, 1.0]]))
    assert free[iy[0], ix[0]] and free[iy[1], ix[1]]


def test_a_wall_cell_stops_the_ray_there():
    grid = _grid()
    cams = np.array([[0.2, 1.0]])
    pts = np.array([[3.5, 1.0]])
    occupied = np.zeros(grid.shape, dtype=bool)
    wx, wy = grid.to_index(np.array([[2.0, 1.0]]))
    occupied[wy[0], wx[0]] = True
    free = free_space_raster(grid, pts, cams, seed=0, occupied=occupied)
    before = grid.to_index(np.array([[1.0, 1.0]]))
    after = grid.to_index(np.array([[3.0, 1.0]]))
    assert free[before[1][0], before[0][0]], "the near side of the wall is still free"
    assert not free[after[1][0], after[0][0]], "nothing beyond the wall is free"


def test_blocking_never_adds_free_space():
    """Whatever the occupancy, cutting rays can only remove cells, never invent them."""
    rng = np.random.default_rng(3)
    grid = _grid()
    cams = rng.uniform(0.2, 1.5, size=(50, 2))
    pts = cams + rng.uniform(0.5, 2.0, size=(50, 2))
    occupied = rng.random(grid.shape) < 0.05
    plain = free_space_raster(grid, pts, cams, seed=0)
    cut = free_space_raster(grid, pts, cams, seed=0, occupied=occupied)
    assert not (cut & ~plain).any()


def test_the_default_is_still_off():
    from levanta.plan.pipeline import PlanOptions

    assert PlanOptions().free_blocked_by_walls is False
