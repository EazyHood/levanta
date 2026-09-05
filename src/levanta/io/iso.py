"""A 3-D preview of the model as a flat drawing (axonometric projection, painter's algorithm).

No OpenGL, no browser: walls, floors, doors and windows are turned into quads, projected
orthographically from above-front, sorted back to front and flat-shaded.  It is what the
HTML viewer shows when the interactive renderer cannot load, and what the README embeds.
"""

from __future__ import annotations

import numpy as np

from levanta.i18n import t
from levanta.io.draw import Drawing
from levanta.plan.model import wall_pieces
from levanta.plan.types import FloorPlan, Wall

BASE = {
    "wall": (226, 222, 214),
    "floor": (196, 176, 150),
    "door": (150, 110, 70),
    "window": (170, 205, 235),
    "ceiling": (240, 240, 240),
}


def _box_quads(wall: Wall, t0: float, t1: float, z0: float, z1: float, th: float | None = None):
    th = wall.thickness if th is None else th
    d = wall.direction
    n = wall.normal
    a = np.array([wall.a[0], wall.a[1], 0.0])
    D = np.array([d[0], d[1], 0.0])
    N = np.array([n[0], n[1], 0.0])
    Z = np.array([0.0, 0.0, 1.0])
    c = [a + D * tt + N * nn + Z * zz for tt in (t0, t1) for nn in (-th / 2, th / 2) for zz in (z0, z1)]
    # index: (t, n, z) -> c[t*4 + n*2 + z]
    def v(ti, ni, zi):
        return c[ti * 4 + ni * 2 + zi]

    return [
        [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)],  # top
        [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)],  # -n side
        [v(0, 1, 0), v(1, 1, 0), v(1, 1, 1), v(0, 1, 1)],  # +n side
        [v(0, 0, 0), v(0, 1, 0), v(0, 1, 1), v(0, 0, 1)],  # start cap
        [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)],  # end cap
    ]


def model_faces(plan: FloorPlan, include_ceiling: bool = False, floor_thickness: float = 0.05):
    """(points (k,3), base colour, holes) for every visible face of the model."""
    faces = []
    for w in plan.walls:
        ops = plan.openings_of(w.id)
        for t0, t1, z0, z1 in wall_pieces(w, ops):
            if t1 - t0 > 1e-4 and z1 - z0 > 1e-4:
                for q in _box_quads(w, t0, t1, z0, z1):
                    faces.append((np.array(q), BASE["wall"], []))
        for o in ops:
            if o.kind == "door":
                for q in _box_quads(w, o.t0, o.t1, 0.0, o.z1, th=0.04):
                    faces.append((np.array(q), BASE["door"], []))
            elif o.kind == "window":
                for q in _box_quads(w, o.t0, o.t1, o.z0, o.z1, th=0.02):
                    faces.append((np.array(q), BASE["window"], []))
    for r in plan.rooms:
        ring = [np.array([x, y, 0.0]) for x, y in r.polygon]
        holes = [[np.array([x, y, 0.0]) for x, y in h] for h in r.holes]
        faces.append((np.array(ring), BASE["floor"], [np.array(h) for h in holes]))
        # slab sides
        for a, b in zip(ring, ring[1:] + ring[:1], strict=False):
            q = [a - [0, 0, floor_thickness], b - [0, 0, floor_thickness], b, a]
            faces.append((np.array(q), BASE["floor"], []))
        if include_ceiling:
            top = [p + np.array([0, 0, plan.ceiling_height]) for p in ring]
            faces.append((np.array(top), BASE["ceiling"], []))
    return faces


def _hex(col) -> str:
    return "#" + "".join(f"{int(c):02x}" for c in col)


def project(pts: np.ndarray, azimuth_deg: float = -35.0, elevation_deg: float = 32.0) -> tuple[np.ndarray, np.ndarray]:
    """Orthographic view from azimuth/elevation.  Returns screen (x, y-up) and depth (far = large)."""
    az = np.deg2rad(azimuth_deg)
    el = np.deg2rad(elevation_deg)
    x, y, z = pts[..., 0], pts[..., 1], pts[..., 2]
    xr = x * np.cos(az) - y * np.sin(az)
    yr = x * np.sin(az) + y * np.cos(az)
    sx = xr
    sy = z * np.cos(el) + yr * np.sin(el)
    depth = yr * np.cos(el) - z * np.sin(el)
    return np.stack([sx, sy], axis=-1), depth


def isometric_drawing(
    plan: FloorPlan,
    scale: float = 46.0,
    margin: float = 40.0,
    lang: str = "en",
    include_ceiling: bool = False,
    azimuth_deg: float = -35.0,
    elevation_deg: float = 32.0,
    caption: bool = True,
) -> Drawing:
    faces = model_faces(plan, include_ceiling=include_ceiling)
    if not faces:
        return Drawing(400, 200)
    light = np.array([-0.4, -0.6, 1.0])
    light /= np.linalg.norm(light)
    items = []
    all_pts = []
    for pts, base, holes in faces:
        sp, depth = project(pts, azimuth_deg, elevation_deg)
        # normal for shading
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0]) if len(pts) >= 3 else np.array([0, 0, 1.0])
        nn = np.linalg.norm(n)
        n = n / nn if nn > 0 else np.array([0, 0, 1.0])
        # faces whose normal points away from the viewer are back faces; keep them
        # (painter's order handles it) but shade by |n . light| symmetric for stability
        shade = 0.62 + 0.38 * max(0.0, float(abs(n @ light)))
        col = tuple(int(min(255, c * shade)) for c in base)
        hp = [project(h, azimuth_deg, elevation_deg)[0] for h in holes]
        items.append((float(depth.mean()), sp, hp, col))
        all_pts.append(sp)
        all_pts.extend(hp)
    allp = np.concatenate(all_pts)
    lo = allp.min(axis=0)
    hi = allp.max(axis=0)
    W = (hi[0] - lo[0]) * scale + 2 * margin
    H = (hi[1] - lo[1]) * scale + 2 * margin + (28 if caption else 0)
    d = Drawing(W, H, background="#ffffff")

    def S(p):
        return [(margin + (x - lo[0]) * scale, margin + (hi[1] - y) * scale) for x, y in p]

    for _depth, sp, hp, col in sorted(items, key=lambda it: -it[0]):
        hexc = _hex(col)
        edge = _hex(tuple(int(c * 0.72) for c in col))
        d.polygon(S(sp), fill=hexc, stroke=edge, width=0.6, holes=[S(h) for h in hp], cls="face")
    if caption:
        d.text(margin, H - 10, f"{t(lang, 'view_3d')} · {t(lang, 'generated_by')}", size=10.5, anchor="start", color="#666")
    return d
