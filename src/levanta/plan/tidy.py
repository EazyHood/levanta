"""Turn a raw detection into a plan a person expects to see.

Three things make a raw plan look broken, and none of them is wrong data:

* **Debris**: walls seen through a doorway or a window belong to rooms that were never
  scanned.  They are real, but they are not part of any room on the plan.
* **Doubles**: a wardrobe or a desk front standing 0.5 m in front of a wall is detected
  as a second, parallel wall.
* **Notches**: a room whose outline follows the *seen floor* has bites where furniture
  hid the floor, and stops short of walls hidden behind desks.

The functions here fix each: outlines of open rooms lose short jogs and snap to the
walls next to them; walls that do not bound any room are moved aside (kept in
``FloorPlan.extra_walls`` for the curious, not drawn); walls are trimmed to the stretch
that bounds a room; walls left standing inside a room are dropped.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from levanta.plan.types import FloorPlan, Opening, Wall

WallSeg = tuple[np.ndarray, np.ndarray, float]  # (a, b, thickness)


# ----------------------------------------------------------------------------------------
# orthogonal outlines
# ----------------------------------------------------------------------------------------


def simplify_orthogonal(poly: Polygon, min_edge: float, min_area_frac: float = 0.6) -> Polygon:
    """Remove jogs shorter than ``min_edge`` from an axis-aligned polygon.

    The shortest edge is deleted by merging its two (parallel) neighbours onto the line
    of the longer one, until every edge is at least ``min_edge`` long or only a rectangle
    is left.  Gives up (returns the input) if the area would change by more than
    ``1 - min_area_frac``.
    """
    src = orient(poly, sign=1.0)
    pts = [np.array(p, dtype=float) for p in src.exterior.coords[:-1]]
    if len(pts) < 6:
        return poly
    pts = _dedupe(pts)
    for _ in range(200):
        n = len(pts)
        if n <= 4:
            break
        lengths = [float(np.linalg.norm(pts[(i + 1) % n] - pts[i])) for i in range(n)]
        i = int(np.argmin(lengths))
        if lengths[i] >= min_edge:
            break
        # edge i: pts[i] -> pts[i+1]; neighbours e_prev (pts[i-1]->pts[i]) and e_next (pts[i+1]->pts[i+2])
        ip, i1, i2 = (i - 1) % n, (i + 1) % n, (i + 2) % n
        e_prev = pts[i] - pts[ip]
        e_next = pts[i2] - pts[i1]
        horiz = abs(e_prev[0]) >= abs(e_prev[1])  # neighbours run along x
        axis = 1 if horiz else 0  # coordinate that the neighbours share
        keep_prev = np.linalg.norm(e_prev) >= np.linalg.norm(e_next)
        target = pts[i][axis] if keep_prev else pts[i1][axis]
        if keep_prev:
            # move e_next onto e_prev's line: pts[i2] gets the shared coordinate of e_prev
            pts[i2] = pts[i2].copy()
            pts[i2][axis] = target
        else:
            pts[ip] = pts[ip].copy()
            pts[ip][axis] = target
        # drop the two vertices of the short edge
        pts = [p for k, p in enumerate(pts) if k not in (i, i1)]
        pts = _dedupe(pts)
    out = Polygon([tuple(p) for p in pts]).buffer(0)
    if out.geom_type == "MultiPolygon":
        out = max(out.geoms, key=lambda g: g.area)
    if not out.is_valid or out.is_empty or out.area < min_area_frac * poly.area:
        return poly
    return out


def _dedupe(pts: list[np.ndarray], tol: float = 1e-6) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for p in pts:
        if not out or np.linalg.norm(p - out[-1]) > tol:
            out.append(p)
    if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) <= tol:
        out.pop()
    # remove collinear middle points
    if len(out) >= 3:
        cleaned = []
        n = len(out)
        for k in range(n):
            a, b, c = out[k - 1], out[k], out[(k + 1) % n]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) > 1e-9:
                cleaned.append(b)
        out = cleaned if len(cleaned) >= 3 else out
    return out


def snap_edges_to_walls(poly: Polygon, walls: list[WallSeg], max_dist: float = 2.5, min_overlap: float = 0.35, angle_tol_deg: float = 10.0) -> Polygon:
    """Move each edge of an orthogonal outline onto the inner face of the nearest parallel
    wall that runs alongside it (within ``max_dist``, covering ``min_overlap`` of the edge).

    This is what turns "the floor I could see" into "the room": a desk hides the floor
    next to a wall, but the wall itself was seen.  Measured on ARKitScenes, the seen
    floor stops one to two metres short of walls that were detected; hence the reach.
    """
    src = orient(poly, sign=1.0)  # counter-clockwise: outward normal of a->b is (dy, -dx)
    pts = [np.array(p, dtype=float) for p in src.exterior.coords[:-1]]
    n = len(pts)
    if n < 4 or not walls:
        return poly
    cos_tol = np.cos(np.deg2rad(angle_tol_deg))
    shifts = np.zeros(n)
    normals = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 1e-9:
            normals.append(np.zeros(2))
            continue
        d /= L
        nrm = np.array([d[1], -d[0]])
        normals.append(nrm)
        best = None
        for wa, wb, th in walls:
            wd = wb - wa
            wl = float(np.linalg.norm(wd))
            if wl < 0.3:
                continue
            wd /= wl
            if abs(float(wd @ d)) < cos_tol:
                continue
            # perpendicular offset of the wall centreline from this edge (positive = outside)
            off = float((wa - a) @ nrm)
            if off < -max_dist or off > max_dist:
                continue
            # along-edge overlap
            ta, tb = float((wa - a) @ d), float((wb - a) @ d)
            lo, hi = max(0.0, min(ta, tb)), min(L, max(ta, tb))
            overlap = hi - lo
            if overlap < min_overlap * L:
                continue
            inner_face = off - np.sign(off) * th / 2 if abs(off) > th / 2 else 0.0
            score = (-abs(off), overlap)  # the nearest wall that runs alongside wins; ties by overlap
            if best is None or score > best[0]:
                best = (score, inner_face)
        if best is not None:
            shifts[i] = best[1]
    if not np.any(shifts):
        return poly
    # apply: an edge moves along its normal; its two vertices move with it.  A vertex is
    # shared by two perpendicular edges, so each vertex gets one shift per axis.
    new_pts = [p.copy() for p in pts]
    for i in range(n):
        if shifts[i] == 0.0:
            continue
        delta = normals[i] * shifts[i]
        new_pts[i] = new_pts[i] + delta
        new_pts[(i + 1) % n] = new_pts[(i + 1) % n] + delta
    out = Polygon([tuple(p) for p in new_pts]).buffer(0)
    if out.geom_type == "MultiPolygon":
        out = max(out.geoms, key=lambda g: g.area)
    if not out.is_valid or out.is_empty or out.area < 0.5 * poly.area:
        return poly
    return out


def clip_to_walls(poly: Polygon, wall_bodies, min_area: float) -> Polygon:
    """Cut wall bodies out of an outline and keep the largest piece."""
    if wall_bodies is None or wall_bodies.is_empty:
        return poly
    cut = poly.difference(wall_bodies)
    if cut.is_empty:
        return poly
    pieces = list(cut.geoms) if hasattr(cut, "geoms") else [cut]
    best = max(pieces, key=lambda g: g.area)
    return best if best.area >= min_area else poly


# ----------------------------------------------------------------------------------------
# walls
# ----------------------------------------------------------------------------------------


def tidy_walls(plan: FloorPlan, attach_dist: float = 0.25, trim_margin: float = 0.15, min_len: float = 0.4, inside_margin: float = 0.1) -> FloorPlan:
    """Keep only the stretches of wall that bound a room; the rest goes to ``extra_walls``.

    Openings are carried over with their positions re-based on the trimmed wall.  When the
    plan has no rooms nothing is changed (there is nothing to judge against).
    """
    if not plan.rooms:
        return plan
    rooms_union = unary_union([r.shapely for r in plan.rooms])
    boundary = rooms_union.boundary
    eroded = rooms_union.buffer(-0.12)
    walls: list[Wall] = []
    openings: list[Opening] = []
    extra: list[Wall] = list(plan.extra_walls)
    for w in plan.walls:
        line = LineString([w.a, w.b])
        L = w.length
        # a wall bounds a room when its body touches the room outline
        near = rooms_union.buffer(attach_dist + w.thickness / 2)
        inter = line.intersection(near)
        parts = [] if inter.is_empty else (list(inter.geoms) if hasattr(inter, "geoms") else [inter])
        kept_any = False
        for seg in parts:
            if seg.geom_type != "LineString" or seg.length < 1e-6:
                continue
            t0 = float(line.project(Point(seg.coords[0])))
            t1 = float(line.project(Point(seg.coords[-1])))
            t0, t1 = sorted((t0, t1))
            t0 = max(0.0, t0 - trim_margin)
            t1 = min(L, t1 + trim_margin)
            if t1 - t0 < min_len:
                continue
            mid = Point(w.point_at((t0 + t1) / 2))
            if rooms_union.contains(mid) and boundary.distance(mid) > w.thickness / 2 + inside_margin:
                continue  # standing inside a room: furniture, not a wall
            # Pieces that run *into* the room (a desk front, a cabinet side, a jamb return)
            # rather than along its outline.  A short piece crossing the outline, or a
            # piece standing deep inside, goes; a piece parallel to the outline and hugging
            # it (a step in the wall the outline did not follow) stays.
            seg_line = LineString([w.point_at(t0), w.point_at(t1)])
            inside_len = seg_line.intersection(eroded).length
            outside_len = seg_line.difference(rooms_union.buffer(w.thickness / 2 + 0.05)).length
            seg_len = t1 - t0
            if inside_len > 0.05:
                if outside_len > 0.05 and seg_len < 1.0:
                    continue  # crosses the outline: a jamb or a cabinet side
                mid_pt = Point(seg_line.interpolate(0.5, normalized=True))
                to_boundary = boundary.distance(mid_pt)
                nearest = boundary.interpolate(boundary.project(mid_pt))
                v = np.array([nearest.x - mid_pt.x, nearest.y - mid_pt.y])
                parallel = to_boundary < 1e-6 or abs(float(w.direction @ (v / max(np.linalg.norm(v), 1e-9)))) < 0.3
                hugging = parallel and to_boundary <= 0.3
                if not hugging and inside_len > (0.05 if seg_len < 0.6 else max(0.2, 0.3 * seg_len)):
                    continue
            kept_any = True
            nw = Wall(
                id=len(walls),
                a=tuple(float(v) for v in w.point_at(t0)),
                b=tuple(float(v) for v in w.point_at(t1)),
                thickness=w.thickness,
                height=w.height,
                sides_seen=w.sides_seen,
                exterior=w.exterior,
                line_id=w.line_id,
            )
            walls.append(nw)
            for o in plan.openings_of(w.id):
                o0, o1 = max(o.t0, t0), min(o.t1, t1)
                if o1 - o0 < 0.3:
                    continue
                openings.append(Opening(id=len(openings), wall_id=nw.id, kind=o.kind, t0=o0 - t0, t1=o1 - t0, z0=o.z0, z1=o.z1))
        if not kept_any:
            extra.append(w)
    # which rooms does each opening connect?
    for o in openings:
        w = walls[o.wall_id]
        seg = LineString([w.point_at(o.t0), w.point_at(o.t1)]).buffer(w.thickness / 2 + 0.05, cap_style="flat")
        o.rooms = tuple(r.id for r in plan.rooms if r.shapely.intersects(seg))
    plan.walls = walls
    plan.openings = openings
    plan.extra_walls = extra
    plan.meta.setdefault("debug", {})["walls_set_aside"] = len(extra)
    return plan


def square_corners(plan: FloorPlan, reach: float = 0.35, min_len: float = 0.3) -> FloorPlan:
    """Make wall ends meet the wall they run into.

    An end that lies within ``reach`` of a crossing wall's centreline is moved along its
    own wall onto that wall's face: the *outer* face at an L-corner (so the corner closes
    square, with no stub poking out and no notch), the *near* face at a T-junction.  Ends
    away from any crossing wall are left alone.  Openings keep their absolute position.
    """
    walls = plan.walls
    for w in walls:
        d = w.direction
        for which in ("a", "b"):
            e = np.asarray(getattr(w, which), dtype=float)
            out_dir = d if which == "b" else -d  # pointing away from the wall's body
            best: tuple[float, float] | None = None  # (|t_line|, new t along out_dir)
            for c in walls:
                if c.id == w.id or abs(float(c.direction @ d)) > 0.5:
                    continue
                n = c.normal
                dn = float(out_dir @ n)
                if abs(dn) < 0.5:
                    continue
                t_line = float((np.asarray(c.a) - e) @ n) / dn  # along out_dir to c's centreline
                if abs(t_line) > reach:
                    continue
                proj = e + out_dir * t_line
                s_c = float((proj - np.asarray(c.a)) @ c.direction)
                if s_c < -reach or s_c > c.length + reach:
                    continue  # the lines cross, the walls do not (the other may still be short of the corner)
                corner = s_c < w.thickness + 0.05 or s_c > c.length - w.thickness - 0.05
                t_new = t_line + (c.thickness / 2 if corner else -c.thickness / 2)
                if best is None or abs(t_line) < best[0]:
                    best = (abs(t_line), t_new)
            if best is None or abs(best[1]) < 1e-3:
                continue
            new_e = e + out_dir * best[1]
            if which == "b":
                if float((new_e - np.asarray(w.a)) @ d) < min_len:
                    continue
                w.b = (float(new_e[0]), float(new_e[1]))
            else:
                if float((np.asarray(w.b) - new_e) @ d) < min_len:
                    continue
                shift = float((new_e - np.asarray(w.a)) @ d)  # > 0: the start moved forward
                w.a = (float(new_e[0]), float(new_e[1]))
                for o in plan.openings:
                    if o.wall_id == w.id:
                        o.t0 -= shift
                        o.t1 -= shift
    return plan


def drop_stubs(plan: FloorPlan, max_len: float = 0.6, connect_dist: float = 0.15) -> FloorPlan:
    """Short walls that touch no other wall at either end are jambs, cabinet sides or
    noise: set them aside."""
    if len(plan.walls) < 2:
        return plan
    bodies = {w.id: w.polygon() for w in plan.walls}
    keep: list[Wall] = []
    for w in plan.walls:
        if w.length >= max_len:
            keep.append(w)
            continue
        others = unary_union([b for i, b in bodies.items() if i != w.id])
        touches = others.distance(Point(w.a)) <= connect_dist or others.distance(Point(w.b)) <= connect_dist
        if touches:
            keep.append(w)
        else:
            plan.extra_walls.append(w)
    if len(keep) != len(plan.walls):
        remap = {w.id: i for i, w in enumerate(keep)}
        openings = []
        for o in plan.openings:
            if o.wall_id in remap:
                o.wall_id = remap[o.wall_id]
                o.id = len(openings)
                openings.append(o)
        for i, w in enumerate(keep):
            w.id = i
        plan.walls = keep
        plan.openings = openings
    return plan


def uncovered_portions(edge_a, edge_b, near) -> list[tuple[np.ndarray, np.ndarray]]:
    """Pieces of the segment a->b that lie outside the geometry ``near``."""
    seg = LineString([edge_a, edge_b])
    diff = seg.difference(near)
    if diff.is_empty:
        return []
    parts = list(diff.geoms) if hasattr(diff, "geoms") else [diff]
    out = []
    for p in parts:
        if p.geom_type == "LineString" and p.length > 0.05:
            c = np.asarray(p.coords)
            out.append((c[0], c[-1]))
    return out


def close_outline_gaps(
    plan: FloorPlan,
    free: np.ndarray,
    grid,
    door_range: tuple[float, float] = (0.55, 1.3),
    passage_max: float = 2.5,
    free_min: float = 0.35,
    default_thickness: float = 0.10,
    default_door_height: float = 2.05,
    wall_near: float = 0.12,
    end_tol: float = 0.18,
) -> FloorPlan:
    """A stretch of a room outline with no wall, bounded by walls on both sides, through
    which the camera looked, is a doorway: add the missing piece of wall with a door cut
    in it.  (The wall-line pass finds doors *within* a wall; this finds them *between*
    walls that were detected as separate pieces.)"""
    if not plan.rooms or not plan.walls:
        return plan
    bodies = unary_union([w.polygon() for w in plan.walls])
    near = bodies.buffer(wall_near)
    for r in plan.rooms:
        poly = orient(r.shapely, sign=1.0)
        coords = np.asarray(poly.exterior.coords)
        for (x0, y0), (x1, y1) in pairwise(coords):
            a, b = np.array([x0, y0]), np.array([x1, y1])
            L_edge = float(np.linalg.norm(b - a))
            if L_edge < door_range[0]:
                continue
            for pa, pb in uncovered_portions(a, b, near):
                # both ends must be walls (a gap between walls, not the end of the scan)
                if bodies.distance(Point(pa)) > end_tol or bodies.distance(Point(pb)) > end_tol:
                    continue
                # the wall bodies were padded by ``wall_near`` for the coverage test;
                # give that back to the gap so its width is the real jamb-to-jamb one
                d0 = (pb - pa) / max(float(np.linalg.norm(pb - pa)), 1e-9)
                pad = max(0.0, wall_near - 0.03)
                pa = pa - d0 * pad
                pb = pb + d0 * pad
                L = float(np.linalg.norm(pb - pa))
                if L < door_range[0] or L > passage_max:
                    continue
                ts = np.linspace(0.1, 0.9, 9)
                pts = pa[None, :] + (pb - pa)[None, :] * ts[:, None]
                inside = grid.inside(pts)
                if not inside.any():
                    continue
                frac = float(grid.sample(free, pts[inside]).mean())
                if frac < free_min:
                    continue
                d = (pb - pa) / L
                n_out = np.array([d[1], -d[0]])  # outward for a CCW ring
                # thickness from a collinear neighbour if there is one
                th = default_thickness
                for w in plan.walls:
                    if abs(float(w.direction @ d)) > 0.97 and LineString([w.a, w.b]).distance(Point(pa)) < 0.3:
                        th = w.thickness
                        break
                centre_a = pa + n_out * th / 2
                centre_b = pb + n_out * th / 2
                kind = "door" if L <= door_range[1] else "passage"
                nw = Wall(id=len(plan.walls), a=(float(centre_a[0]), float(centre_a[1])), b=(float(centre_b[0]), float(centre_b[1])), thickness=th, height=plan.ceiling_height, sides_seen=1, line_id=-1)
                plan.walls.append(nw)
                z1 = default_door_height if kind == "door" else plan.ceiling_height
                plan.openings.append(Opening(id=len(plan.openings), wall_id=nw.id, kind=kind, t0=0.0, t1=L, z0=0.0, z1=min(z1, plan.ceiling_height), rooms=(r.id,)))
    return plan


def orthogonal_edges_ok(poly: Polygon) -> bool:
    coords = np.asarray(poly.exterior.coords)
    return all(abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6 for (x0, y0), (x1, y1) in pairwise(coords))
