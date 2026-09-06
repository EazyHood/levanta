"""Rooms bounded by the walls, with the floor only voting on which side is inside.

The other builder (:func:`levanta.plan.rooms.build_rooms`) starts from the floor: the
interior is the seen floor plus the free space the camera looked through, and the walls
then cut it.  Measured on the Replica flat with a *perfect* cloud, that source is thinner
than it looks: floor points reach only 36 % of the real floor, because a camera at 1.5 m
sees furniture, and everything the camera saw *through* a doorway joins the interior.  One
room came out at 44.6 m² against a truth of 17.1 m², spanning all three rooms of the flat
and with 19 m² of it outside the building at either storey.

So this builder inverts the two.  Every detected wall line is extended to a full cut
across the plan; the cuts make a rectangular arrangement (the frame is Manhattan, so the
lines are axis aligned); each rectangle asks the floor whether it is interior; and two
neighbouring interior rectangles belong to the same room unless a wall body actually
stands between them.  A doorway is a gap in the wall body, so it joins two rectangles
without any bridging heuristic, and the outline of a room is closed and orthogonal because
it is a union of rectangles.

What it cannot do is invent a wall that was never detected: where the walls are missing
the rectangles simply run on to the next cut, so this builder trades the floor's leaks for
the walls' silences.  Which of the two wins is a measurement, not an opinion, and
``bench/planner_bench.py`` is where it is settled.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from levanta.plan.occupancy import Grid
from levanta.plan.walls import WallLine


def _cuts(values: list[float], lo: float, hi: float, merge: float) -> list[float]:
    """Sorted cut coordinates inside ``[lo, hi]``, with near-duplicates merged."""
    out: list[float] = []
    for v in sorted(v for v in values if lo < v < hi):
        if out and v - out[-1] < merge:
            out[-1] = 0.5 * (out[-1] + v)
        else:
            out.append(v)
    return [lo, *out, hi]


def _fraction(mask: np.ndarray, grid: Grid, x0: float, y0: float, x1: float, y1: float) -> float:
    """Fraction of a rectangle where ``mask`` is true, on the plan grid."""
    i0 = max(0, int((x0 - grid.x0) / grid.cell))
    i1 = min(grid.nx, int(np.ceil((x1 - grid.x0) / grid.cell)))
    j0 = max(0, int((y0 - grid.y0) / grid.cell))
    j1 = min(grid.ny, int(np.ceil((y1 - grid.y0) / grid.cell)))
    if i1 <= i0 or j1 <= j0:
        return 0.0
    sub = mask[j0:j1, i0:i1]
    return float(sub.mean())


def build_rooms_from_walls(
    lines: list[WallLine],
    inside: np.ndarray,
    floor: np.ndarray,
    grid: Grid,
    *,
    min_area: float = 1.5,
    min_evidence: float = 0.35,
    blocked_frac: float = 0.55,
    merge_cuts: float = 0.20,
    camera_xy: np.ndarray | None = None,
    stats: dict | None = None,
) -> list[tuple[Polygon, bool]]:
    """Rooms as groups of rectangles cut by the wall lines.

    ``inside`` votes on which rectangles are interior, ``floor`` is reported but not used
    to decide, and a rectangle joins its neighbour unless a wall body covers more than
    ``blocked_frac`` of the edge between them.  Returns ``(polygon, closed)`` pairs, where
    ``closed`` means every edge of the room has a wall behind it.
    """
    bodies = [
        LineString([ln.point(t0), ln.point(t1)]).buffer(ln.thickness / 2, cap_style="flat", join_style="mitre")
        for ln in lines
        for t0, t1 in ln.intervals
    ]
    counts = {"cells": 0, "interior": 0, "rooms": 0, "too_small": 0, "not_walked": 0}
    if stats is not None:
        stats.update(counts)
    if not bodies:
        return []
    solid = unary_union(bodies)
    minx, miny, maxx, maxy = solid.bounds
    minx, miny, maxx, maxy = minx - 0.3, miny - 0.3, maxx + 0.3, maxy + 0.3

    # a wall whose normal is along x is a cut of constant x, and vice versa
    xs = _cuts([ln.s for ln in lines if abs(np.cos(ln.alpha)) > 0.7], minx, maxx, merge_cuts)
    ys = _cuts([ln.s for ln in lines if abs(np.sin(ln.alpha)) > 0.7], miny, maxy, merge_cuts)
    nx, ny = len(xs) - 1, len(ys) - 1
    if nx < 1 or ny < 1:
        return []

    evidence = np.zeros((nx, ny))
    for i in range(nx):
        for j in range(ny):
            evidence[i, j] = _fraction(inside, grid, xs[i], ys[j], xs[i + 1], ys[j + 1])
    interior = evidence >= min_evidence
    counts["cells"] = nx * ny
    counts["interior"] = int(interior.sum())

    # union-find over interior rectangles, joined across an edge no wall body covers
    parent = list(range(nx * ny))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def open_edge(p: tuple[float, float], q: tuple[float, float]) -> bool:
        edge = LineString([p, q])
        if edge.length < 1e-9:
            return False
        return edge.intersection(solid).length < blocked_frac * edge.length

    for i in range(nx):
        for j in range(ny):
            if not interior[i, j]:
                continue
            if i + 1 < nx and interior[i + 1, j] and open_edge((xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1])):
                union(i * ny + j, (i + 1) * ny + j)
            if j + 1 < ny and interior[i, j + 1] and open_edge((xs[i], ys[j + 1]), (xs[i + 1], ys[j + 1])):
                union(i * ny + j, i * ny + j + 1)

    groups: dict[int, list[tuple[int, int]]] = {}
    for i in range(nx):
        for j in range(ny):
            if interior[i, j]:
                groups.setdefault(find(i * ny + j), []).append((i, j))

    rooms: list[tuple[Polygon, bool]] = []
    for cells in groups.values():
        poly = unary_union([box(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i, j in cells])
        if poly.geom_type != "Polygon" or poly.area < min_area:
            counts["too_small"] += 1
            continue
        if camera_xy is not None and len(camera_xy):
            from shapely import contains_xy

            if not contains_xy(poly.buffer(0.3), camera_xy[:, 0], camera_xy[:, 1]).any():
                counts["not_walked"] += 1  # a patch glimpsed through a doorway is not a room
                continue
        # closed when the whole outline has wall behind it; a room that runs off the end of
        # a wall is honest about it, and the sheet stamps it the same as any other open room
        edge = poly.exterior
        closed = edge.intersection(solid.buffer(0.05)).length > 0.85 * edge.length
        rooms.append((poly.simplify(0.01, preserve_topology=True), closed))

    counts["rooms"] = len(rooms)
    if stats is not None:
        stats.update(counts)
    rooms.sort(key=lambda r: -r[0].area)
    return rooms


def seen_floor_fraction(poly: Polygon, floor: np.ndarray, grid: Grid, reach: float = 0.10) -> float:
    """How much of a room's outline rests on floor that was actually seen.

    It is the share of the room's area whose ``reach``-sized square holds at least one
    floor point.  Read it as "how much of what is drawn was observed", not "how much of the
    real room was seen": the outline is drawn where the evidence is, so a room can score
    well and still be far too small.

    Three definitions were tried against a control that has to score ~100 %: the synthetic
    apartment, whose floor is modelled in full and sampled from a camera path with nothing
    to hide it.

    | rule | synthetic | Replica flat | ARKitScenes 47331964 |
    |---|---|---|---|
    | raw 2 cm cells with a point | 30 % | 30-33 % | 1-4 % |
    | a 10 cm square holds a point | **100 %** | 61-75 % | 3-23 % |
    | a 10 cm square is a quarter full | 59 % | 47-53 % | 0-11 % |

    Counting raw cells measures the 2 cm voxel spacing, not visibility.  Requiring a
    quarter of the square to be filled measures point *density*, which is why it fails the
    control.  Growing a 10 cm disc around every point was tried too and scored the Replica
    flat at 82 %, contradicting a direct measurement of that scene against its own mesh: one
    lone point became a hundred cells.  So: one point per 10 cm square, and no more.

    On a real walk the number stays low for a reason that is not an artefact.  Furniture
    hides the floor from a camera at eye height, and on the Replica flat, with exact depth
    and exact poses, floor points reach only about a third of the *real* floor even though
    the path passes within 2 m of 80-94 % of every room.
    """
    r = max(1, round(reach / grid.cell))
    ny, nx = floor.shape
    py, px = (-ny) % r, (-nx) % r
    blocks = np.pad(floor, ((0, py), (0, px))).reshape((ny + py) // r, r, (nx + px) // r, r).any(axis=(1, 3))
    floor = np.repeat(np.repeat(blocks, r, axis=0), r, axis=1)[:ny, :nx]
    x0, y0, x1, y1 = poly.bounds
    i0 = max(0, int((x0 - grid.x0) / grid.cell))
    i1 = min(grid.nx, int(np.ceil((x1 - grid.x0) / grid.cell)))
    j0 = max(0, int((y0 - grid.y0) / grid.cell))
    j1 = min(grid.ny, int(np.ceil((y1 - grid.y0) / grid.cell)))
    if i1 <= i0 or j1 <= j0:
        return 0.0
    ii, jj = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
    xs = grid.x0 + (ii.ravel() + 0.5) * grid.cell
    ys = grid.y0 + (jj.ravel() + 0.5) * grid.cell
    from shapely import contains_xy

    inpoly = contains_xy(poly, xs, ys)
    if not inpoly.any():
        return 0.0
    return float(floor[jj.ravel()[inpoly], ii.ravel()[inpoly]].mean())
