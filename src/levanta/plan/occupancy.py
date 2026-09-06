"""2-D rasters of the gravity-aligned cloud.

Three rasters drive the planner:

``coverage``  per cell, how many distinct height bands contain wall points.  A real wall
              spans most of the floor-to-ceiling range; a sofa or a shelf spans a few
              bands only.  This separates architecture from furniture without learning.
``floor``     cells that contain floor points (normal up, z ~ 0): definitely inside.
``free``      cells crossed by a line of sight from a camera to a point it observed.
              A gap in a wall that rays passed through is a doorway; a gap no ray
              crossed is just unseen wall.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Grid:
    x0: float
    y0: float
    cell: float
    nx: int
    ny: int

    @classmethod
    def from_points(cls, xy: np.ndarray, cell: float, margin: float = 0.5) -> Grid:
        lo = xy.min(axis=0) - margin
        hi = xy.max(axis=0) + margin
        nx = int(np.ceil((hi[0] - lo[0]) / cell)) + 1
        ny = int(np.ceil((hi[1] - lo[1]) / cell)) + 1
        return cls(x0=float(lo[0]), y0=float(lo[1]), cell=cell, nx=nx, ny=ny)

    def to_index(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Column (ix) and row (iy) indices; out-of-range values are clipped."""
        ix = np.floor((xy[:, 0] - self.x0) / self.cell).astype(np.int64)
        iy = np.floor((xy[:, 1] - self.y0) / self.cell).astype(np.int64)
        return np.clip(ix, 0, self.nx - 1), np.clip(iy, 0, self.ny - 1)

    def inside(self, xy: np.ndarray) -> np.ndarray:
        ix = (xy[:, 0] - self.x0) / self.cell
        iy = (xy[:, 1] - self.y0) / self.cell
        return (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)

    def cell_center(self, ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
        return np.stack([self.x0 + (ix + 0.5) * self.cell, self.y0 + (iy + 0.5) * self.cell], axis=-1)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    def sample(self, raster: np.ndarray, xy: np.ndarray) -> np.ndarray:
        """Raster values at points (nearest cell)."""
        ix, iy = self.to_index(xy)
        return raster[iy, ix]


def coverage_raster(grid: Grid, xy: np.ndarray, z: np.ndarray, z_band: float, z_max: float) -> np.ndarray:
    """Number of distinct ``z_band``-tall height bands (0..z_max) hit by points, per cell."""
    ix, iy = grid.to_index(xy)
    band = np.clip(np.floor(z / z_band).astype(np.int64), 0, max(0, int(np.ceil(z_max / z_band)) - 1))
    n_bands = int(band.max()) + 1 if len(band) else 1
    key = (iy * grid.nx + ix) * n_bands + band
    uniq = np.unique(key)
    cell_ids = uniq // n_bands
    out = np.zeros(grid.nx * grid.ny, dtype=np.int32)
    np.add.at(out, cell_ids, 1)
    return out.reshape(grid.ny, grid.nx)


def count_raster(grid: Grid, xy: np.ndarray) -> np.ndarray:
    ix, iy = grid.to_index(xy)
    out = np.zeros(grid.nx * grid.ny, dtype=np.int32)
    np.add.at(out, iy * grid.nx + ix, 1)
    return out.reshape(grid.ny, grid.nx)


def free_space_raster(
    grid: Grid,
    xy_points: np.ndarray,
    xy_cams: np.ndarray,
    max_rays: int = 150_000,
    stop_short: float = 0.06,
    seed: int = 0,
    occupied: np.ndarray | None = None,
) -> np.ndarray:
    """Boolean raster of cells crossed by camera->point sight lines (points themselves excluded).

    ``stop_short`` metres are trimmed from the far end of every ray so that the wall
    surface a ray ends on is not marked free.

    ``occupied`` stops each ray at the first cell it marks, instead of letting it run to its
    own endpoint.  Without it a ray aimed past the edge of a wall walks straight through
    that wall's cells, because each ray only knows where *it* ended.  Measured on the
    Replica flat: where the interior leaves the building, 61 % of the crossing front has a
    real wall levanta did not draw, and 80 % of those cells have wall points within 0.25 m.
    The evidence was there and the tracing went through it.
    """
    free = np.zeros(grid.shape, dtype=bool)
    n = len(xy_points)
    if n == 0:
        return free
    rng = np.random.default_rng(seed)
    if n > max_rays:
        sel = rng.choice(n, size=max_rays, replace=False)
        xy_points = xy_points[sel]
        xy_cams = xy_cams[sel]
    d = xy_points - xy_cams
    length = np.linalg.norm(d, axis=1)
    ok = length > stop_short + grid.cell
    xy_points, xy_cams, d, length = xy_points[ok], xy_cams[ok], d[ok], length[ok]
    if len(length) == 0:
        return free
    length_eff = length - stop_short
    n_steps = np.ceil(length_eff / (grid.cell * 0.7)).astype(np.int64) + 1
    flat = np.zeros(grid.nx * grid.ny, dtype=bool)
    chunk = 20_000
    for s in range(0, len(length), chunk):
        e = min(s + chunk, len(length))
        k_max = int(n_steps[s:e].max())
        t = np.linspace(0.0, 1.0, k_max)[None, :]  # (1, K)
        frac = (length_eff[s:e] / length[s:e])[:, None]
        pts = xy_cams[s:e, None, :] + d[s:e, None, :] * (t * frac)[..., None]  # (B, K, 2)
        valid = t <= 1.0  # all, but keep shape logic explicit
        valid = np.broadcast_to(valid, pts.shape[:2]) & (t * (k_max - 1) <= n_steps[s:e][:, None])
        shape = pts.shape[:2]
        p = pts.reshape(-1, 2)
        inside = grid.inside(p).reshape(shape)
        ix, iy = grid.to_index(p)
        ix, iy = ix.reshape(shape), iy.reshape(shape)
        keep = valid & inside
        if occupied is not None:
            # the first occupied cell ends the ray: everything at or beyond it is unknown,
            # not free.  cumsum along the ray is what makes "first" mean first.
            keep &= np.cumsum(occupied[iy, ix] & inside, axis=1) == 0
        flat[iy[keep] * grid.nx + ix[keep]] = True
    return flat.reshape(grid.ny, grid.nx)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a square of radius ``r`` cells (no scipy.ndimage import needed elsewhere)."""
    if r <= 0:
        return mask
    from scipy.ndimage import binary_dilation

    return binary_dilation(mask, structure=np.ones((2 * r + 1, 2 * r + 1), dtype=bool))
