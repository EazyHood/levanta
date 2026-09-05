"""The 2-D floor-plan drawing (architectural style), as a :class:`~levanta.io.draw.Drawing`.

One function builds the drawing; SVG and PNG come from the same primitives.
"""

from __future__ import annotations

import datetime as _dt
from itertools import pairwise

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from levanta.i18n import fmt_area, fmt_len, t
from levanta.io.draw import Drawing
from levanta.plan.types import FloorPlan, Opening, Wall

COLORS = {
    "room": "#f6f2ea",
    "room_open": "#f3f0ea",
    "wall": "#2b2b2b",
    "door": "#8a5a2b",
    "window": "#2b6cb0",
    "passage": "#2b2b2b",
    "open_edge": "#9a9a9a",
    "label": "#222222",
    "sub": "#555555",
    "dim": "#777777",
    "dim_text": "#444444",
    "title": "#111111",
    "meta": "#666666",
}


# ----------------------------------------------------------------------------------------
# geometry helpers shared with DXF export
# ----------------------------------------------------------------------------------------


def opening_rect(wall: Wall, o: Opening, extra: float = 0.0) -> Polygon:
    a = wall.point_at(o.t0)
    b = wall.point_at(o.t1)
    return LineString([a, b]).buffer(wall.thickness / 2 + extra, cap_style="flat", join_style="mitre")


def wall_body_polygons(plan: FloorPlan) -> list[Polygon]:
    """Wall rectangles with every opening cut out (what you see from above)."""
    out: list[Polygon] = []
    for w in plan.walls:
        body = w.polygon()
        cuts = [opening_rect(w, o, extra=0.002) for o in plan.openings_of(w.id)]
        if cuts:
            body = body.difference(unary_union(cuts))
        if body.is_empty:
            continue
        out.extend(list(body.geoms) if hasattr(body, "geoms") else [body])
    return out


def swing_side(plan: FloorPlan, wall: Wall, o: Opening) -> float:
    """+1 / -1: on which side of the wall (along its normal) the door opens."""
    mid = wall.point_at((o.t0 + o.t1) / 2)
    n = wall.normal
    probe = mid + n * (wall.thickness / 2 + 0.3)
    for r in plan.rooms:
        if r.shapely.contains(Point(probe)):
            return 1.0
    return -1.0


def open_edges(plan: FloorPlan, tol: float = 0.15) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Room outline edges that do not lie on a detected wall: the unscanned sides."""
    if not plan.walls:
        return []
    near = unary_union([w.polygon() for w in plan.walls]).buffer(tol)
    out = []
    for r in plan.rooms:
        if r.closed:
            continue
        ring = [*r.polygon, r.polygon[0]]
        for a, b in pairwise(ring):
            seg = LineString([a, b])
            if seg.length < 0.05:
                continue
            uncovered = seg.difference(near)
            if uncovered.length > 0.5 * seg.length:
                out.append((a, b))
    return out


def door_arc(hinge: np.ndarray, tip: np.ndarray, jamb: np.ndarray, n_pts: int = 14) -> list[tuple[float, float]]:
    """Quarter-circle from the leaf tip to the far jamb about the hinge (plan coordinates)."""
    r = float(np.linalg.norm(tip - hinge))
    a0 = float(np.arctan2(tip[1] - hinge[1], tip[0] - hinge[0]))
    a1 = float(np.arctan2(jamb[1] - hinge[1], jamb[0] - hinge[0]))
    da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi  # shortest way
    return [(float(hinge[0] + r * np.cos(a0 + da * k / n_pts)), float(hinge[1] + r * np.sin(a0 + da * k / n_pts))) for k in range(n_pts + 1)]


# ----------------------------------------------------------------------------------------
# the drawing
# ----------------------------------------------------------------------------------------


def floor_plan_drawing(
    plan: FloorPlan,
    scale: float = 80.0,
    margin: float = 90.0,
    lang: str = "en",
    units: str = "m",
    title: str | None = None,
    show_dimensions: bool = True,
    show_labels: bool = True,
    show_title_block: bool = True,
) -> Drawing:
    """Build the plan drawing.  ``scale`` is pixels per metre."""
    xmin, ymin, xmax, ymax = plan.bounds
    if xmax - xmin < 1e-6:
        xmin, xmax = xmin - 1, xmax + 1
    if ymax - ymin < 1e-6:
        ymin, ymax = ymin - 1, ymax + 1
    W = (xmax - xmin) * scale + 2 * margin
    H = (ymax - ymin) * scale + 2 * margin + (40 if show_title_block else 0)
    d = Drawing(W, H)

    def X(x: float) -> float:
        return margin + (x - xmin) * scale

    def Y(y: float) -> float:
        return margin + (ymax - y) * scale

    def P(pts) -> list[tuple[float, float]]:
        return [(X(x), Y(y)) for x, y in pts]

    # rooms
    for r in plan.rooms:
        d.polygon(P(r.polygon), fill=COLORS["room"] if r.closed else COLORS["room_open"], holes=[P(h) for h in r.holes], cls="room")
    # unscanned sides
    for a, b in open_edges(plan):
        d.line((X(a[0]), Y(a[1])), (X(b[0]), Y(b[1])), stroke=COLORS["open_edge"], width=1.2, dash=(6, 5), cls="open-edge")
    # walls (openings cut)
    for poly in wall_body_polygons(plan):
        d.polygon(P(list(poly.exterior.coords)), fill=COLORS["wall"], holes=[P(list(ring.coords)) for ring in poly.interiors], cls="wall")
    # openings
    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a = w.point_at(o.t0)
        b = w.point_at(o.t1)
        n = w.normal
        if o.kind == "door":
            side = swing_side(plan, w, o)
            tip = a + n * side * o.width
            d.line((X(a[0]), Y(a[1])), (X(tip[0]), Y(tip[1])), stroke=COLORS["door"], width=1.4, cls="door")
            d.polyline(P(door_arc(a, tip, b)), stroke=COLORS["door"], width=1.2, cls="door")
        elif o.kind == "window":
            for k in (-0.5, 0.0, 0.5):
                off = n * k * w.thickness * 0.6
                d.line((X(a[0] + off[0]), Y(a[1] + off[1])), (X(b[0] + off[0]), Y(b[1] + off[1])), stroke=COLORS["window"], width=1.2, cls="window")
        else:
            d.line((X(a[0]), Y(a[1])), (X(b[0]), Y(b[1])), stroke=COLORS["passage"], width=1.0, dash=(4, 4), cls="passage")
    # labels
    if show_labels:
        for r in plan.rooms:
            cx, cy = r.centroid
            bx0, by0, bx1, by1 = r.shapely.bounds
            name = r.name if r.closed else f"{r.name} ({t(lang, 'incomplete')})"
            d.text(X(cx), Y(cy) - 4, name, size=13, weight="bold", color=COLORS["label"], cls="label")
            d.text(X(cx), Y(cy) + 11, f"{fmt_area(r.area, units)} · {fmt_len(bx1 - bx0, units)} × {fmt_len(by1 - by0, units)}", size=11, color=COLORS["sub"], cls="label")
    # overall dimensions
    if show_dimensions:
        off = 28
        yb = Y(ymin) + off
        d.line((X(xmin), Y(ymin) + 6), (X(xmin), yb + 5), stroke=COLORS["dim"], width=0.8, cls="dim")
        d.line((X(xmax), Y(ymin) + 6), (X(xmax), yb + 5), stroke=COLORS["dim"], width=0.8, cls="dim")
        d.line((X(xmin), yb), (X(xmax), yb), stroke=COLORS["dim"], width=0.8, cls="dim")
        _tick(d, X(xmin), yb)
        _tick(d, X(xmax), yb)
        d.text((X(xmin) + X(xmax)) / 2, yb - 4, fmt_len(xmax - xmin, units), size=11, color=COLORS["dim_text"], cls="dim")
        xl = X(xmin) - off
        d.line((X(xmin) - 6, Y(ymin)), (xl - 5, Y(ymin)), stroke=COLORS["dim"], width=0.8, cls="dim")
        d.line((X(xmin) - 6, Y(ymax)), (xl - 5, Y(ymax)), stroke=COLORS["dim"], width=0.8, cls="dim")
        d.line((xl, Y(ymin)), (xl, Y(ymax)), stroke=COLORS["dim"], width=0.8, cls="dim")
        _tick(d, xl, Y(ymin))
        _tick(d, xl, Y(ymax))
        d.text(xl - 4, (Y(ymin) + Y(ymax)) / 2, fmt_len(ymax - ymin, units), size=11, color=COLORS["dim_text"], rotate=90, cls="dim")
    # title block + scale bar
    if show_title_block:
        ttl = title or t(lang, "floor_plan")
        ceil = f"{t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)} ({t(lang, 'measured') if plan.ceiling_measured else t(lang, 'default')})"
        d.text(margin, H - 34, ttl, size=14, weight="bold", anchor="start", color=COLORS["title"], cls="title")
        d.text(margin, H - 18, f"{t(lang, 'generated_by')} · {len(plan.rooms)} {t(lang, 'rooms')} · {fmt_area(plan.total_area, units)} · {ceil} · {_dt.date.today().isoformat()}", size=10.5, anchor="start", color=COLORS["meta"], cls="meta")
        sx = W - margin - scale
        sy = H - 26
        d.polygon([(sx, sy), (sx + scale / 2, sy), (sx + scale / 2, sy + 6), (sx, sy + 6)], fill="#222")
        d.polygon([(sx + scale / 2, sy), (sx + scale, sy), (sx + scale, sy + 6), (sx + scale / 2, sy + 6)], fill=None, stroke="#222", width=0.8)
        d.text(sx, sy - 4, "0", size=10.5, anchor="start", color=COLORS["meta"])
        d.text(sx + scale, sy - 4, "1 m" if units == "m" else "3'3\"", size=10.5, anchor="end", color=COLORS["meta"])
    return d


def _tick(d: Drawing, x: float, y: float) -> None:
    d.line((x - 3, y + 3), (x + 3, y - 3), stroke=COLORS["dim"], width=0.8, cls="dim")
