"""Openings (doors, passages, windows) and room polygons.

Doors are *gaps* between two wall segments on the same wall line through which the
camera actually looked (free-space raster).  A gap nobody looked through is merged back
into the wall: the capture simply did not cover it.  Windows are stretches of a wall
that were seen below and above a band but never inside it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from levanta.plan.occupancy import Grid
from levanta.plan.walls import WallLine, line_intersection, refine_edges


@dataclass
class LineOpening:
    line_id: int
    kind: str
    t0: float
    t1: float
    z0: float
    z1: float
    measured: bool = False


def _free_fraction(line: WallLine, t0: float, t1: float, free: np.ndarray, grid: Grid, n: int = 12) -> float:
    ts = np.linspace(t0, t1, n)
    pts = np.stack([line.point(t) for t in ts])
    inside = grid.inside(pts)
    if not inside.any():
        return 0.0
    return float(grid.sample(free, pts[inside]).mean())


def _lintel_height(line: WallLine, t0: float, t1: float, default: float, z_min: float = 1.7) -> tuple[float, bool]:
    tz = line.samples(t0 + 0.05, t1 - 0.05)
    hi = tz[tz[:, 1] >= z_min, 1]
    if len(hi) >= 5:
        return float(np.percentile(hi, 5)), True
    return default, False


def _door_edges(line: WallLine, t0: float, t1: float, z1: float) -> tuple[float, float]:
    """Sharpen a doorway's jambs on the raw samples (the leaf zone 0.3 m .. z1 - 0.2 m)."""
    return refine_edges(line.samples(t0 - 0.3, t1 + 0.3), t0, t1, 0.3, max(0.6, z1 - 0.2))


def resolve_gaps(
    lines: list[WallLine],
    free: np.ndarray,
    grid: Grid,
    *,
    door_min: float,
    door_max: float,
    free_min: float,
    unseen_merge_max: float,
    default_door_height: float,
    ceiling_height: float,
) -> list[LineOpening]:
    """Turn the gaps between a wall line's intervals into doors / passages, or close them."""
    openings: list[LineOpening] = []
    for ln in lines:
        iv = sorted(ln.intervals)
        merged: list[list[float]] = [list(iv[0])] if iv else []
        for a, b in iv[1:]:
            gap = a - merged[-1][1]
            if gap < door_min:
                merged[-1][1] = max(merged[-1][1], b)
                continue
            frac = _free_fraction(ln, merged[-1][1], a, free, grid)
            if frac >= free_min:
                kind = "door" if gap <= door_max else "passage"
                z1, measured = _lintel_height(ln, merged[-1][1], a, default_door_height)
                if kind == "passage" and not measured:
                    z1 = ceiling_height
                z1 = min(z1, ceiling_height)
                ga, gb = _door_edges(ln, merged[-1][1], a, z1)
                merged[-1][1] = ga
                openings.append(LineOpening(ln.id, kind, ga, gb, 0.0, z1, measured))
                merged.append([gb, b])
            elif gap <= unseen_merge_max:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        ln.intervals = [(float(a), float(b)) for a, b in merged]
    return openings


def snap_corners(
    lines: list[WallLine],
    free: np.ndarray,
    grid: Grid,
    *,
    snap_dist: float,
    door_min: float,
    free_min: float,
    default_door_height: float,
    ceiling_height: float,
) -> list[LineOpening]:
    """Extend wall ends to meet the walls they run into (L corners and T junctions).

    An extension long enough to be a door, through which the camera looked, becomes a
    door instead of solid wall.
    """
    openings: list[LineOpening] = []
    for ia, a in enumerate(lines):
        for ib, b in enumerate(lines):
            if ib <= ia:
                continue
            x = line_intersection(a, b)
            if x is None:
                continue
            ta, tb = x
            _snap_pair(a, ta, b, tb, snap_dist, door_min, free, grid, free_min, default_door_height, ceiling_height, openings)
    return openings


def _near_end(line: WallLine, t: float, snap: float) -> tuple[int, int] | None:
    """(interval index, -1 for start / +1 for end) if ``t`` lies just outside an interval end."""
    for k, (t0, t1) in enumerate(line.intervals):
        if t0 - snap <= t < t0:
            return k, -1
        if t1 < t <= t1 + snap:
            return k, +1
    return None


def _within(line: WallLine, t: float, slack: float) -> bool:
    return any(t0 - slack <= t <= t1 + slack for t0, t1 in line.intervals)


def _extend(line: WallLine, k: int, side: int, t: float, free, grid, door_min, free_min, dh, ch, openings) -> None:
    t0, t1 = line.intervals[k]
    if side < 0:
        ext = t0 - t
        if ext >= door_min and _free_fraction(line, t, t0, free, grid) >= free_min:
            z1, measured = _lintel_height(line, t, t0, dh)
            z1 = min(z1, ch)
            ga, gb = _door_edges(line, t, t0, z1)
            openings.append(LineOpening(line.id, "door", ga, gb, 0.0, z1, measured))
        line.intervals[k] = (t, t1)
    else:
        ext = t - t1
        if ext >= door_min and _free_fraction(line, t1, t, free, grid) >= free_min:
            z1, measured = _lintel_height(line, t1, t, dh)
            z1 = min(z1, ch)
            ga, gb = _door_edges(line, t1, t, z1)
            openings.append(LineOpening(line.id, "door", ga, gb, 0.0, z1, measured))
        line.intervals[k] = (t0, t)


def _snap_pair(a, ta, b, tb, snap, door_min, free, grid, free_min, dh, ch, openings) -> None:
    ea = _near_end(a, ta, snap)
    eb = _near_end(b, tb, snap)
    a_within = _within(a, ta, a.thickness / 2)
    b_within = _within(b, tb, b.thickness / 2)
    if ea is not None and (eb is not None or b_within):
        _extend(a, ea[0], ea[1], ta, free, grid, door_min, free_min, dh, ch, openings)
    if eb is not None and (ea is not None or a_within):
        _extend(b, eb[0], eb[1], tb, free, grid, door_min, free_min, dh, ch, openings)


def detect_windows(
    lines: list[WallLine],
    *,
    ceiling_height: float,
    t_bin: float = 0.05,
    min_width: float = 0.40,
    low_band: tuple[float, float] = (0.12, 0.75),
    mid_band: tuple[float, float] = (0.95, 1.80),
    high_min: float = 1.95,
) -> list[LineOpening]:
    """Windows: seen below and above a band, never inside it, over >= ``min_width``."""
    out: list[LineOpening] = []
    high_min = min(high_min, ceiling_height - 0.35)
    for ln in lines:
        for t0, t1 in ln.intervals:
            tz = ln.samples(t0, t1)
            if len(tz) < 20:
                continue
            nb = int(np.ceil((t1 - t0) / t_bin)) + 1
            idx = np.clip(((tz[:, 0] - t0) / t_bin).astype(int), 0, nb - 1)
            z = tz[:, 1]
            low = np.zeros(nb, bool)
            mid = np.zeros(nb, int)
            high = np.zeros(nb, bool)
            low[idx[(z >= low_band[0]) & (z <= low_band[1])]] = True
            np.add.at(mid, idx[(z >= mid_band[0]) & (z <= mid_band[1])], 1)
            high[idx[z >= high_min]] = True
            win = low & high & (mid <= 1)
            # runs
            k = 0
            while k < nb:
                if not win[k]:
                    k += 1
                    continue
                j = k
                while j < nb and win[j]:
                    j += 1
                width = (j - k) * t_bin
                if width >= min_width:
                    wt0, wt1 = t0 + k * t_bin, t0 + j * t_bin
                    sel = (tz[:, 0] >= wt0) & (tz[:, 0] <= wt1)
                    zl = z[sel & (z < mid_band[0])]
                    zh = z[sel & (z > mid_band[1])]
                    sill = float(np.percentile(zl, 95)) if len(zl) else low_band[1]
                    head = float(np.percentile(zh, 5)) if len(zh) else high_min
                    if head - sill >= 0.4:
                        wt0, wt1 = refine_edges(ln.samples(wt0 - 0.3, wt1 + 0.3), wt0, wt1, sill + 0.1, head - 0.1)
                        out.append(LineOpening(ln.id, "window", wt0, wt1, sill, head, True))
                k = j
    return out


def build_rooms(
    lines: list[WallLine],
    openings: list[LineOpening],
    inside: np.ndarray,
    grid: Grid,
    *,
    min_area: float,
    min_inside_frac: float,
    simplify_tol: float = 0.01,
    inside_strict: np.ndarray | None = None,
    fallback: bool = True,
    camera_xy: np.ndarray | None = None,
    min_wall_frac: float = 0.2,
    close_r: float = 0.6,
    manhattan: bool = True,
    room_min_jog: float = 0.9,
    room_snap_dist: float = 1.0,
) -> list[tuple[Polygon, bool]]:
    """Rooms are the pockets between wall bodies (doors temporarily bricked up) that the
    capture actually looked into.

    Returns ``(polygon, closed)`` pairs.  A pocket that leaks to the outside (a wall was
    never seen, so the vector outline is not closed) falls back to the *seen floor*: the
    connected region of ``inside_strict`` bounded by whatever walls were found.  Those
    rooms are flagged ``closed = False`` and must be *walked* (contain a camera position)
    with at least ``min_wall_frac`` of their outline on detected walls, or have half of
    their outline on walls; that rejects a patch of ground glimpsed through a doorway.
    """
    bodies = []
    for ln in lines:
        for t0, t1 in ln.intervals:
            bodies.append(LineString([ln.point(t0), ln.point(t1)]).buffer(ln.thickness / 2, cap_style="flat", join_style="mitre"))
    closers = []
    by_id = {ln.id: ln for ln in lines}
    for o in openings:
        if o.kind in ("door", "passage"):
            ln = by_id[o.line_id]
            closers.append(LineString([ln.point(o.t0), ln.point(o.t1)]).buffer(ln.thickness / 2, cap_style="flat", join_style="mitre"))
    if not bodies:
        return []
    solid = unary_union(bodies + closers)
    minx, miny, maxx, maxy = solid.bounds
    domain = box(minx - 0.5, miny - 0.5, maxx + 0.5, maxy + 0.5)
    pockets = domain.difference(solid)
    polys = list(pockets.geoms) if hasattr(pockets, "geoms") else [pockets]
    rooms: list[tuple[Polygon, bool]] = []
    for p in polys:
        if p.area < min_area:
            continue
        if p.touches(domain.exterior) or p.intersects(domain.exterior):
            continue  # leaks to the outside world; handled by the raster fallback
        frac = _inside_fraction(p, inside, grid)
        if frac < min_inside_frac:
            continue
        q = p.simplify(simplify_tol, preserve_topology=True)
        if q.is_valid and q.area > 0:
            rooms.append((q, True))

    if fallback:
        strict = inside if inside_strict is None else inside_strict
        near_walls = solid.buffer(0.15)

        def plausible(poly: Polygon) -> bool:
            covered = unary_union([r for r, _ in rooms]) if rooms else None
            if covered is not None and poly.intersection(covered).area > 0.5 * poly.area:
                return False  # already represented
            wall_frac = poly.exterior.intersection(near_walls).length / max(poly.exterior.length, 1e-9)
            has_cam = camera_xy is not None and bool(shapely.contains_xy(poly, camera_xy[:, 0], camera_xy[:, 1]).any())
            return (has_cam and wall_frac >= min_wall_frac) or wall_frac >= 0.5

        # Stage 2: bridge gaps of up to 2 * close_r between wall pieces (an unseen bit of
        # wall, an undetected doorway) and take the pockets again.  Corners stay square
        # because the buffers use mitre joins.
        if close_r > 0:
            solid_c = solid.buffer(close_r, join_style="mitre").buffer(-close_r, join_style="mitre")
            pockets2 = domain.difference(solid_c)
            for p in list(pockets2.geoms) if hasattr(pockets2, "geoms") else [pockets2]:
                if p.area < min_area or p.intersects(domain.exterior):
                    continue
                if _inside_fraction(p, inside, grid) < min_inside_frac:
                    continue
                q = p.simplify(0.02, preserve_topology=True)
                if q.is_valid and q.area > 0 and plausible(q):
                    rooms.append((q, False))
        # Stage 3: whatever is still open follows the seen floor.  Its outline then
        # loses the bites furniture took out of it and snaps to the walls beside it.
        from levanta.plan.tidy import clip_to_walls, simplify_orthogonal, snap_edges_to_walls

        segs = [(np.asarray(ln.point(t0)), np.asarray(ln.point(t1)), ln.thickness) for ln in lines for t0, t1 in ln.intervals]
        for poly in _raster_rooms(solid, strict, grid, min_area=min_area):
            if manhattan:
                poly = rectilinearize(poly)
                poly = simplify_orthogonal(poly, min_edge=room_min_jog)
                poly = snap_edges_to_walls(poly, segs, max_dist=room_snap_dist)
                poly = clip_to_walls(poly, unary_union(bodies), min_area)
                poly = simplify_orthogonal(poly.simplify(0.02, preserve_topology=True), min_edge=room_min_jog)
            if plausible(poly):
                rooms.append((poly, False))
    rooms.sort(key=lambda r: -r[0].area)
    return rooms


def rectilinearize(poly: Polygon, tol: float = 0.12, max_area_change: float = 0.35) -> Polygon:
    """Turn a rough outline into an orthogonal (axis-aligned) polygon.

    Edges are classified horizontal / vertical, runs of the same class are merged into
    one line at their length-weighted mean coordinate, and consecutive lines are
    intersected.  Falls back to the input when the result is invalid or changes the
    area by more than ``max_area_change``.
    """
    src = poly.simplify(tol, preserve_topology=True)
    pts = np.asarray(src.exterior.coords)[:-1]
    if len(pts) < 4:
        return poly
    # classify edges
    edges = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        horiz = abs(b[0] - a[0]) >= abs(b[1] - a[1])
        edges.append((horiz, a, b))
    # merge runs of equal orientation (circularly)
    runs: list[list] = []
    for e in edges:
        if runs and runs[-1][0] == e[0]:
            runs[-1][1].append(e)
        else:
            runs.append([e[0], [e]])
    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        runs[0][1] = runs[-1][1] + runs[0][1]
        runs.pop()
    if len(runs) < 4 or len(runs) % 2:
        return poly
    lines = []
    for horiz, es in runs:
        w = np.array([np.hypot(b[0] - a[0], b[1] - a[1]) for _, a, b in es])
        coord = np.array([(a[1] + b[1]) / 2 if horiz else (a[0] + b[0]) / 2 for _, a, b in es])
        c = float(np.average(coord, weights=w)) if w.sum() > 0 else float(coord.mean())
        lines.append((horiz, c))
    verts = []
    for i in range(len(lines)):
        h1, c1 = lines[i]
        h2, c2 = lines[(i + 1) % len(lines)]
        if h1 == h2:
            return poly
        x = c2 if h1 else c1
        y = c1 if h1 else c2
        verts.append((x, y))
    out = Polygon(verts).buffer(0)
    if out.geom_type == "MultiPolygon":
        out = max(out.geoms, key=lambda g: g.area)
    if not out.is_valid or out.is_empty:
        return poly
    if abs(out.area - poly.area) > max_area_change * poly.area:
        return poly
    return out


def _raster_rooms(solid, inside: np.ndarray, grid: Grid, min_area: float, simplify_tol: float = 0.05, close_m: float = 1.0, open_m: float = 0.3) -> list[Polygon]:
    """Connected regions of ``inside`` not covered by wall bodies, traced to polygons.

    Holes and bays shallower than ``close_m`` (furniture standing against a wall hides
    the floor behind it) are filled, then protrusions thinner than ``open_m`` removed,
    before tracing.  Walls are subtracted *after* the closing, so it never bridges a
    detected wall.
    """
    import cv2

    ny, nx = inside.shape
    wall = np.zeros((ny, nx), dtype=np.uint8)
    geoms = list(solid.geoms) if hasattr(solid, "geoms") else [solid]
    for g in geoms:
        if g.is_empty:
            continue
        rings = [np.asarray(g.exterior.coords)] + [np.asarray(r.coords) for r in g.interiors]
        cells = [np.round((r - [grid.x0, grid.y0]) / grid.cell - 0.5).astype(np.int32) for r in rings]
        cv2.fillPoly(wall, cells, 1)
    wall = cv2.dilate(wall, np.ones((3, 3), np.uint8))
    kc = max(3, 2 * round(close_m / grid.cell / 2) + 1)
    ko = max(3, 2 * round(open_m / grid.cell / 2) + 1)
    cand = cv2.morphologyEx(inside.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    cand = (cand.astype(bool) & (wall == 0)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((ko, ko), np.uint8))
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=4)
    out: list[Polygon] = []
    min_cells = min_area / (grid.cell**2)
    for lab in range(1, n_lab):
        if stats[lab, cv2.CC_STAT_AREA] < min_cells:
            continue
        comp = (labels == lab).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if len(c) < 4:
                continue
            ext = grid.cell_center(c[:, 0, 0], c[:, 0, 1])
            poly = Polygon(ext).buffer(0)
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
            poly = poly.simplify(simplify_tol, preserve_topology=True)
            if poly.is_valid and poly.area >= min_area:
                out.append(poly)
    return out


def _inside_fraction(poly: Polygon, inside: np.ndarray, grid: Grid) -> float:
    minx, miny, maxx, maxy = poly.bounds
    ix0, iy0 = grid.to_index(np.array([[minx, miny]]))
    ix1, iy1 = grid.to_index(np.array([[maxx, maxy]]))
    ixs = np.arange(int(ix0[0]), int(ix1[0]) + 1)
    iys = np.arange(int(iy0[0]), int(iy1[0]) + 1)
    if len(ixs) * len(iys) > 400_000:  # coarsen for huge polygons
        ixs = ixs[:: max(1, len(ixs) // 600)]
        iys = iys[:: max(1, len(iys) // 600)]
    gx, gy = np.meshgrid(ixs, iys)
    centers = grid.cell_center(gx.ravel(), gy.ravel())
    within = shapely.contains_xy(poly, centers[:, 0], centers[:, 1])
    if not within.any():
        return 0.0
    return float(inside[gy.ravel()[within], gx.ravel()[within]].mean())
