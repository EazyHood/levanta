"""Diagnostic rendering of a :class:`~levanta.plan.pipeline.PlanResult` as a PNG.

Shows, on one image: the line-of-sight/floor raster (grey), the wall points that
survived the coverage filter (black), the detected wall lines (colour by family), the
final room polygons (green outline) and openings (orange doors, blue windows).  It is
the first thing to look at when a plan comes out wrong.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from levanta.plan.pipeline import PlanResult


def render_debug(result: PlanResult, scale: float = 60.0, path: str | Path | None = None) -> Image.Image:
    plan = result.plan
    cloud = result.cloud
    xy = cloud.xyz[:, :2]
    lo = xy.min(axis=0) - 0.5
    hi = xy.max(axis=0) + 0.5
    W = int((hi[0] - lo[0]) * scale) + 1
    H = int((hi[1] - lo[1]) * scale) + 1
    img = Image.new("RGB", (W, H), (255, 255, 255))
    px = img.load()

    def P(x: float, y: float) -> tuple[float, float]:
        return ((x - lo[0]) * scale, (hi[1] - y) * scale)

    # inside raster
    grid = result.grid
    inside = result.rasters["inside"]
    iy, ix = np.nonzero(inside)
    cxy = grid.cell_center(ix, iy)
    for x, y in cxy[:: max(1, len(cxy) // 200_000)]:
        u, v = P(x, y)
        if 0 <= u < W and 0 <= v < H:
            px[int(u), int(v)] = (225, 225, 225)

    draw = ImageDraw.Draw(img, "RGBA")
    # wall points (all horizontal-normal points, thinned)
    z = cloud.xyz[:, 2]
    m = (np.abs(cloud.normals[:, 2]) < 0.35) & (z > 0.1)
    wp = xy[m]
    for x, y in wp[:: max(1, len(wp) // 60_000)]:
        u, v = P(x, y)
        if 0 <= u < W and 0 <= v < H:
            px[int(u), int(v)] = (40, 40, 40)
    # cameras
    if cloud.cameras is not None:
        for c in cloud.camera_centers:
            u, v = P(c[0], c[1])
            draw.ellipse([u - 2, v - 2, u + 2, v + 2], fill=(200, 0, 200, 255))
    # rooms
    for r in plan.rooms:
        pts = [P(x, y) for x, y in r.polygon]
        draw.polygon(pts, outline=(0, 150, 0, 255), fill=(0, 200, 0, 25))
    # walls
    for w in plan.walls:
        poly = w.polygon()
        pts = [P(x, y) for x, y in poly.exterior.coords]
        col = (200, 40, 40, 255) if w.line_id % 2 == 0 else (40, 40, 220, 255)
        draw.polygon(pts, outline=col)
    # openings
    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a, b = w.point_at(o.t0), w.point_at(o.t1)
        col = (255, 140, 0, 255) if o.kind in ("door", "passage") else (0, 120, 255, 255)
        draw.line([P(*a), P(*b)], fill=col, width=4)
    if path is not None:
        img.save(path)
    return img
