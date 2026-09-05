"""The 2-D floor-plan drawing, drafted the way an architect expects it.

Layers, from the bottom up: rooms, unscanned sides (dashed), walls (openings cut),
openings with tags, room labels, dimension chains on the perimeter walls (corner –
opening – opening – corner), overall dimensions, reference axes (A, B, C across the
top; 1, 2, 3 down the right), north arrow, area schedule and door/window schedule,
title block.  One function builds it; SVG, PNG and PDF come from the same primitives.
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
    "wall_int": "#3a3a3a",
    "door": "#8a5a2b",
    "window": "#2b6cb0",
    "passage": "#2b2b2b",
    "open_edge": "#9a9a9a",
    "label": "#222222",
    "sub": "#555555",
    "dim": "#777777",
    "dim_text": "#333333",
    "axis": "#b04a4a",
    "title": "#111111",
    "meta": "#666666",
    "table": "#333333",
    "rule": "#cfcac2",
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


def wall_sides(plan: FloorPlan, wall: Wall, probe: float = 0.3) -> tuple[bool, bool]:
    """(room on the +normal side, room on the -normal side)."""
    mid = wall.point_at(wall.length / 2)
    n = wall.normal
    d = wall.thickness / 2 + probe
    plus = Point(mid + n * d)
    minus = Point(mid - n * d)
    rooms = [r.shapely for r in plan.rooms]
    return any(r.contains(plus) for r in rooms), any(r.contains(minus) for r in rooms)


def open_edges(plan: FloorPlan, tol: float = 0.15) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Portions of room outlines that lie on no detected wall: the unscanned sides."""
    if not plan.walls:
        return [(a, b) for r in plan.rooms if not r.closed for a, b in pairwise([*r.polygon, r.polygon[0]])]
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
            diff = seg.difference(near)
            if diff.is_empty:
                continue
            parts = list(diff.geoms) if hasattr(diff, "geoms") else [diff]
            for p in parts:
                if p.geom_type == "LineString" and p.length > 0.2:
                    c = list(p.coords)
                    out.append(((float(c[0][0]), float(c[0][1])), (float(c[-1][0]), float(c[-1][1]))))
    return out


def door_arc(hinge: np.ndarray, tip: np.ndarray, jamb: np.ndarray, n_pts: int = 14) -> list[tuple[float, float]]:
    """Quarter-circle from the leaf tip to the far jamb about the hinge (plan coordinates)."""
    r = float(np.linalg.norm(tip - hinge))
    a0 = float(np.arctan2(tip[1] - hinge[1], tip[0] - hinge[0]))
    a1 = float(np.arctan2(jamb[1] - hinge[1], jamb[0] - hinge[0]))
    da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi  # shortest way
    return [(float(hinge[0] + r * np.cos(a0 + da * k / n_pts)), float(hinge[1] + r * np.sin(a0 + da * k / n_pts))) for k in range(n_pts + 1)]


def dimension_chains(plan: FloorPlan, min_len: float = 1.0) -> list[dict]:
    """Chains of dimensions along perimeter walls: ``{wall, side, stations}`` where
    ``side`` is +1/-1 (which side of the wall to draw on: the one with no room) and
    ``stations`` the sorted breakpoints along the wall (ends and opening jambs)."""
    chains = []
    for w in plan.walls:
        if w.length < min_len:
            continue
        plus, minus = wall_sides(plan, w)
        if plus and minus:
            continue  # interior partition: dimensioned through the room sizes
        if not plus and not minus:
            continue  # bounds nothing
        side = 1.0 if not plus else -1.0
        stations = {0.0, w.length}
        for o in plan.openings_of(w.id):
            stations.add(max(0.0, o.t0))
            stations.add(min(w.length, o.t1))
        chains.append({"wall": w, "side": side, "stations": sorted(stations)})
    return chains


def reference_axes(plan: FloorPlan, merge_tol: float = 0.35) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Letters for the x positions of the vertical walls, numbers for the y positions of
    the horizontal ones (Manhattan plans only; angled walls are skipped)."""
    xs: list[float] = []
    ys: list[float] = []
    for w in plan.walls:
        d = w.direction
        if abs(d[0]) < 0.05:  # vertical
            xs.append((w.a[0] + w.b[0]) / 2)
        elif abs(d[1]) < 0.05:
            ys.append((w.a[1] + w.b[1]) / 2)

    def cluster(vals: list[float]) -> list[float]:
        out: list[float] = []
        for v in sorted(vals):
            if out and abs(v - out[-1]) <= merge_tol:
                out[-1] = (out[-1] + v) / 2
            else:
                out.append(v)
        return out

    letters = [(chr(ord("A") + i), x) for i, x in enumerate(cluster(xs)) if i < 26]
    numbers = [(str(i + 1), y) for i, y in enumerate(reversed(cluster(ys)))]  # 1 at the top
    return letters, numbers


# ----------------------------------------------------------------------------------------
# the drawing
# ----------------------------------------------------------------------------------------


def floor_plan_drawing(
    plan: FloorPlan,
    scale: float = 80.0,
    margin: float | None = None,
    lang: str = "en",
    units: str = "m",
    title: str | None = None,
    show_dimensions: bool = True,
    show_labels: bool = True,
    show_title_block: bool = True,
    show_chains: bool = True,
    show_axes: bool = True,
    show_tables: bool = True,
    print_scale: int | None = None,
    font_scale: float = 1.0,
) -> Drawing:
    """Build the plan drawing.  ``scale`` is pixels (or points) per metre.

    ``print_scale`` (e.g. 100 for 1:100) is only printed in the title block; the caller
    picks ``scale`` accordingly.  ``font_scale`` multiplies every text size.
    """
    fs = font_scale
    xmin, ymin, xmax, ymax = plan.bounds
    if xmax - xmin < 1e-6:
        xmin, xmax = xmin - 1, xmax + 1
    if ymax - ymin < 1e-6:
        ymin, ymax = ymin - 1, ymax + 1
    chains = dimension_chains(plan) if (show_chains and show_dimensions) else []
    letters, numbers = reference_axes(plan) if show_axes else ([], [])
    # space around the plan, in metres
    m_left = 1.35 if show_dimensions else 0.4
    m_bottom = 1.35 if show_dimensions else 0.4
    m_top = 0.9 if letters else 0.4
    m_right = 0.9 if numbers else 0.4
    if chains:
        m_top = max(m_top, 1.25)
        m_right = max(m_right, 1.25)
    if plan.north_deg is not None:
        m_top = max(m_top, 1.1)
    pad = 24.0 * fs if margin is None else margin
    plan_w = (xmax - xmin + m_left + m_right) * scale
    plan_h = (ymax - ymin + m_top + m_bottom) * scale
    table_w = (260.0 * fs) if show_tables and (plan.rooms or plan.openings) else 0.0
    ax_off = 0.95 if chains else 0.65  # axis bubbles sit beyond the dimension chains
    tb_h = 78.0 * fs if show_title_block else 0.0
    W = pad + plan_w + (16 * fs + table_w if table_w else 0) + pad
    H = pad + plan_h + tb_h + pad
    d = Drawing(W, H)

    ox = pad + m_left * scale
    oy = pad + m_top * scale

    def X(x: float) -> float:
        return ox + (x - xmin) * scale

    def Y(y: float) -> float:
        return oy + (ymax - y) * scale

    def P(pts) -> list[tuple[float, float]]:
        return [(X(x), Y(y)) for x, y in pts]

    # rooms
    for r in plan.rooms:
        d.polygon(P(r.polygon), fill=COLORS["room"] if r.closed else COLORS["room_open"], holes=[P(h) for h in r.holes], cls="room")
    for a, b in open_edges(plan):
        d.line((X(a[0]), Y(a[1])), (X(b[0]), Y(b[1])), stroke=COLORS["open_edge"], width=1.2 * fs, dash=(6 * fs, 5 * fs), cls="open-edge")
    # reference axes (behind the walls)
    if letters or numbers:
        for lab, x in letters:
            d.line((X(x), Y(ymax) - (ax_off - 0.1) * scale), (X(x), Y(ymin) + 0.2 * scale), stroke=COLORS["axis"], width=0.6 * fs, dash=(9 * fs, 5 * fs), cls="axis")
            cy = Y(ymax) - ax_off * scale
            d.circle(X(x), cy, 9 * fs, fill="#ffffff", stroke=COLORS["axis"], width=0.9 * fs, cls="axis")
            d.text(X(x), cy + 3.5 * fs, lab, size=10 * fs, weight="bold", color=COLORS["axis"], cls="axis")
        for lab, y in numbers:
            d.line((X(xmin) - 0.2 * scale, Y(y)), (X(xmax) + (ax_off - 0.1) * scale, Y(y)), stroke=COLORS["axis"], width=0.6 * fs, dash=(9 * fs, 5 * fs), cls="axis")
            cx = X(xmax) + ax_off * scale
            d.circle(cx, Y(y), 9 * fs, fill="#ffffff", stroke=COLORS["axis"], width=0.9 * fs, cls="axis")
            d.text(cx, Y(y) + 3.5 * fs, lab, size=10 * fs, weight="bold", color=COLORS["axis"], cls="axis")
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
            d.line((X(a[0]), Y(a[1])), (X(tip[0]), Y(tip[1])), stroke=COLORS["door"], width=1.4 * fs, cls="door")
            d.polyline(P(door_arc(a, tip, b)), stroke=COLORS["door"], width=1.2 * fs, cls="door")
            tag_pt = (a + b) / 2 + n * side * (o.width * 0.75)
        elif o.kind == "window":
            for k in (-0.5, 0.0, 0.5):
                off = n * k * w.thickness * 0.6
                d.line((X(a[0] + off[0]), Y(a[1] + off[1])), (X(b[0] + off[0]), Y(b[1] + off[1])), stroke=COLORS["window"], width=1.2 * fs, cls="window")
            plus, _ = wall_sides(plan, w)
            tag_pt = (a + b) / 2 + n * (1.0 if plus else -1.0) * (w.thickness / 2 + 0.22)
        else:
            d.line((X(a[0]), Y(a[1])), (X(b[0]), Y(b[1])), stroke=COLORS["passage"], width=1.0 * fs, dash=(4 * fs, 4 * fs), cls="passage")
            plus, _minus = wall_sides(plan, w)
            tag_pt = (a + b) / 2 + n * (1.0 if plus else -1.0) * (w.thickness / 2 + 0.22)
        if o.tag and show_labels:
            col = COLORS["door"] if o.kind == "door" else COLORS["window"] if o.kind == "window" else COLORS["label"]
            d.text(X(tag_pt[0]), Y(tag_pt[1]) + 3.5 * fs, o.tag, size=9.5 * fs, weight="bold", color=col, cls="tag")
    # room labels
    if show_labels:
        for r in plan.rooms:
            cx, cy = r.centroid
            bx0, by0, bx1, by1 = r.shapely.bounds
            name = r.name if r.closed else f"{r.name} ({t(lang, 'incomplete')})"
            d.text(X(cx), Y(cy) - 4 * fs, name, size=13 * fs, weight="bold", color=COLORS["label"], cls="label")
            d.text(X(cx), Y(cy) + 11 * fs, f"{fmt_area(r.area, units)} · {fmt_len(bx1 - bx0, units)} × {fmt_len(by1 - by0, units)}", size=11 * fs, color=COLORS["sub"], cls="label")
            if plan.project.get("level"):
                d.text(X(cx), Y(cy) + 24 * fs, f"{t(lang, 'level_marker')} {plan.project['level']}", size=9.5 * fs, color=COLORS["sub"], cls="label")
    # dimension chains on perimeter walls
    if chains:
        for ch in chains:
            _draw_chain(d, ch, X, Y, scale, units, fs)
    # overall dimensions (further out)
    if show_dimensions:
        off = 1.05 * scale
        yb = Y(ymin) + off
        _dim_line(d, (X(xmin), yb), (X(xmax), yb), fmt_len(xmax - xmin, units), fs, ext_from=((X(xmin), Y(ymin) + 6 * fs), (X(xmax), Y(ymin) + 6 * fs)))
        xl = X(xmin) - off
        _dim_line(d, (xl, Y(ymin)), (xl, Y(ymax)), fmt_len(ymax - ymin, units), fs, ext_from=((X(xmin) - 6 * fs, Y(ymin)), (X(xmin) - 6 * fs, Y(ymax))), vertical=True)
    # north arrow
    if plan.north_deg is not None:
        _north_arrow(d, X(xmin) - 0.85 * scale, oy - 0.45 * scale, plan.north_deg, fs, lang)
    # tables
    if table_w:
        tx = pad + plan_w + 16 * fs
        ty = pad
        ty = _areas_table(d, tx, ty, table_w, plan, lang, units, fs)
        if plan.openings:
            _schedule_table(d, tx, ty + 18 * fs, table_w, plan, lang, units, fs)
    # title block
    if show_title_block:
        _title_block(d, pad, H - pad - tb_h, W - 2 * pad, tb_h, plan, title, lang, units, scale, print_scale, fs)
    return d


# ----------------------------------------------------------------------------------------
# pieces
# ----------------------------------------------------------------------------------------


def _tick(d: Drawing, x: float, y: float, fs: float) -> None:
    d.line((x - 3 * fs, y + 3 * fs), (x + 3 * fs, y - 3 * fs), stroke=COLORS["dim"], width=0.8 * fs, cls="dim")


def _dim_line(d: Drawing, a, b, text: str, fs: float, ext_from=None, vertical: bool = False) -> None:
    d.line(a, b, stroke=COLORS["dim"], width=0.8 * fs, cls="dim")
    if ext_from is not None:
        (e0, e1) = ext_from
        d.line(e0, a, stroke=COLORS["dim"], width=0.6 * fs, cls="dim")
        d.line(e1, b, stroke=COLORS["dim"], width=0.6 * fs, cls="dim")
    _tick(d, a[0], a[1], fs)
    _tick(d, b[0], b[1], fs)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if vertical:
        d.text(mx - 4 * fs, my, text, size=10.5 * fs, color=COLORS["dim_text"], rotate=90, cls="dim")
    else:
        d.text(mx, my - 4 * fs, text, size=10.5 * fs, color=COLORS["dim_text"], cls="dim")


def _draw_chain(d: Drawing, ch: dict, X, Y, scale: float, units: str, fs: float) -> None:
    w: Wall = ch["wall"]
    side = ch["side"]
    n = w.normal * side
    dvec = w.direction
    off = w.thickness / 2 + 0.5  # metres from the centreline
    stations = ch["stations"]
    base = np.array(w.a, dtype=float)
    line_a = base + n * off
    line_b = base + dvec * w.length + n * off
    d.line((X(line_a[0]), Y(line_a[1])), (X(line_b[0]), Y(line_b[1])), stroke=COLORS["dim"], width=0.8 * fs, cls="dim-chain")
    vertical = abs(dvec[0]) < 0.5
    for s in stations:
        p_wall = base + dvec * s + n * (w.thickness / 2 + 0.06)
        p_dim = base + dvec * s + n * off
        d.line((X(p_wall[0]), Y(p_wall[1])), (X(p_dim[0]), Y(p_dim[1])), stroke=COLORS["dim"], width=0.6 * fs, cls="dim-chain")
        _tick(d, X(p_dim[0]), Y(p_dim[1]), fs)
    for s0, s1 in pairwise(stations):
        if s1 - s0 < 0.1:
            continue
        mid = base + dvec * ((s0 + s1) / 2) + n * off
        label = fmt_len(s1 - s0, units)
        # text on the far side of the dimension line, away from the wall
        tp = mid + n * (0.06 + 0.02)
        if vertical:
            d.text(X(tp[0]), Y(tp[1]), label, size=9.5 * fs, color=COLORS["dim_text"], rotate=90, cls="dim-chain")
        else:
            d.text(X(tp[0]), Y(tp[1]) + (3.5 * fs if n[1] < 0 else 0), label, size=9.5 * fs, color=COLORS["dim_text"], cls="dim-chain")


def _north_arrow(d: Drawing, x: float, y: float, north_deg: float, fs: float, lang: str) -> None:
    r = 16 * fs
    ang = np.deg2rad(north_deg)  # clockwise from up
    ux, uy = np.sin(ang), -np.cos(ang)  # screen direction of north (y down)
    d.circle(x, y, r, fill="#ffffff", stroke="#444", width=0.9 * fs, cls="north")
    tip = (x + ux * r * 0.95, y + uy * r * 0.95)
    tail = (x - ux * r * 0.7, y - uy * r * 0.7)
    px, py = -uy, ux  # perpendicular
    d.polygon([tip, (x + px * r * 0.28, y + py * r * 0.28), tail, (x - px * r * 0.28, y - py * r * 0.28)], fill="#222", cls="north")
    d.text(x + ux * (r + 9 * fs), y + uy * (r + 9 * fs) + 3.5 * fs, t(lang, "north"), size=10 * fs, weight="bold", color="#222", cls="north")


def _table(d: Drawing, x: float, y: float, w: float, title: str, headers: list[str], rows: list[list[str]], widths: list[float], fs: float, aligns: list[str] | None = None) -> float:
    """Draw a small table; returns the y below it."""
    rh = 15 * fs
    d.text(x, y + 11 * fs, title, size=11 * fs, weight="bold", anchor="start", color=COLORS["table"], cls="table")
    y += 16 * fs
    cols = np.cumsum([0.0, *widths]) * w
    aligns = aligns or ["start"] * len(headers)
    d.line((x, y), (x + w, y), stroke=COLORS["table"], width=0.8 * fs, cls="table")
    for j, h in enumerate(headers):
        ax = x + cols[j] + 3 * fs if aligns[j] == "start" else x + cols[j + 1] - 3 * fs
        d.text(ax, y + 11 * fs, h, size=8.5 * fs, weight="bold", anchor=aligns[j], color=COLORS["table"], cls="table")
    y += rh
    d.line((x, y), (x + w, y), stroke=COLORS["table"], width=0.6 * fs, cls="table")
    for row in rows:
        for j, cell in enumerate(row):
            ax = x + cols[j] + 3 * fs if aligns[j] == "start" else x + cols[j + 1] - 3 * fs
            d.text(ax, y + 11 * fs, cell, size=8.5 * fs, anchor=aligns[j], color=COLORS["table"], cls="table")
        y += rh
        d.line((x, y), (x + w, y), stroke=COLORS["rule"], width=0.5 * fs, cls="table")
    return y


def _areas_table(d: Drawing, x: float, y: float, w: float, plan: FloorPlan, lang: str, units: str, fs: float) -> float:
    rows = [[r.name + ("" if r.closed else " *"), fmt_area(r.area, units), fmt_len(r.perimeter, units)] for r in plan.rooms]
    summ = plan.area_summary()
    rows.append([t(lang, "useful_area"), fmt_area(summ["useful_m2"], units), ""])
    rows.append([t(lang, "walls_area"), fmt_area(summ["walls_m2"], units), fmt_len(summ["wall_length_m"], units)])
    rows.append([t(lang, "gross_area"), fmt_area(summ["gross_m2"], units), ""])
    y = _table(d, x, y, w, t(lang, "areas_table"), [t(lang, "name"), t(lang, "area"), t(lang, "perimeter")], rows, [0.46, 0.27, 0.27], fs, ["start", "end", "end"])
    if any(not r.closed for r in plan.rooms):
        d.text(x, y + 11 * fs, f"* {t(lang, 'incomplete')}", size=8 * fs, anchor="start", color=COLORS["sub"], cls="table")
        y += 12 * fs
    return y


def _schedule_table(d: Drawing, x: float, y: float, w: float, plan: FloorPlan, lang: str, units: str, fs: float) -> float:
    rows = []
    for o in sorted(plan.openings, key=lambda o: (o.kind, o.tag)):
        h = fmt_len(o.z1 - o.z0, units)
        rows.append([o.tag or "-", t(lang, o.kind), fmt_len(o.width, units), h, fmt_len(o.z0, units) if o.kind == "window" else "-", f"{o.wall_id + 1}"])
    return _table(d, x, y, w, t(lang, "schedule"), [t(lang, "tag"), t(lang, "kind"), t(lang, "width"), t(lang, "height").upper() if len(t(lang, "height")) <= 2 else t(lang, "height"), t(lang, "sill"), t(lang, "wall")], rows, [0.11, 0.21, 0.16, 0.14, 0.23, 0.15], fs, ["start", "start", "end", "end", "end", "end"])


def _title_block(d: Drawing, x: float, y: float, w: float, h: float, plan: FloorPlan, title: str | None, lang: str, units: str, scale: float, print_scale: int | None, fs: float) -> None:
    pr = plan.project
    d.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], fill="#ffffff", stroke="#333", width=1.0 * fs, cls="titleblock")
    cols = [0.0, 0.34, 0.56, 0.72, 0.86, 1.0]
    for c in cols[1:-1]:
        d.line((x + c * w, y), (x + c * w, y + h), stroke="#333", width=0.7 * fs, cls="titleblock")

    def cell(i: int, label: str, value: str, big: bool = False) -> None:
        cx = x + cols[i] * w + 6 * fs
        d.text(cx, y + 13 * fs, label.upper(), size=7.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
        d.text(cx, y + (36 if big else 32) * fs, value, size=(14 if big else 11) * fs, weight="bold" if big else "normal", anchor="start", color=COLORS["title"], cls="titleblock")

    cell(0, t(lang, "project"), pr.get("name") or (title or t(lang, "floor_plan")), big=True)
    d.text(x + 6 * fs, y + 54 * fs, f"{t(lang, 'plan_title')}: {title or t(lang, 'floor_plan')}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
    ceil = f"{t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)} ({t(lang, 'measured') if plan.ceiling_measured else t(lang, 'default')})"
    d.text(x + 6 * fs, y + 68 * fs, f"{len(plan.rooms)} {t(lang, 'rooms')} · {fmt_area(plan.total_area, units)} · {ceil}", size=8.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
    cell(1, t(lang, "author"), pr.get("author") or "—")
    d.text(x + cols[1] * w + 6 * fs, y + 54 * fs, f"{t(lang, 'level')}: {pr.get('level') or '±0.00'}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
    d.text(x + cols[1] * w + 6 * fs, y + 68 * fs, t(lang, "generated_by"), size=8.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
    cell(2, t(lang, "scale"), f"1:{print_scale}" if print_scale else "—")
    # scale bar under the scale text
    sx = x + cols[2] * w + 6 * fs
    sy = y + 58 * fs
    bar = scale  # 1 m
    avail = (cols[3] - cols[2]) * w - 12 * fs
    n_units = 1.0
    if bar > avail:
        n_units = 0.5
        bar = scale * 0.5
    d.polygon([(sx, sy), (sx + bar / 2, sy), (sx + bar / 2, sy + 5 * fs), (sx, sy + 5 * fs)], fill="#222", cls="titleblock")
    d.polygon([(sx + bar / 2, sy), (sx + bar, sy), (sx + bar, sy + 5 * fs), (sx + bar / 2, sy + 5 * fs)], fill=None, stroke="#222", width=0.8 * fs, cls="titleblock")
    d.text(sx, sy - 3 * fs, "0", size=7.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
    d.text(sx + bar, sy - 3 * fs, fmt_len(n_units, units), size=7.5 * fs, anchor="end", color=COLORS["meta"], cls="titleblock")
    cell(3, t(lang, "date"), pr.get("date") or _dt.date.today().isoformat())
    d.text(x + cols[3] * w + 6 * fs, y + 54 * fs, f"{t(lang, 'revision')} {pr.get('revision') or 'A'}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
    cell(4, t(lang, "sheet"), pr.get("sheet") or "A-01")
    d.text(x + cols[4] * w + 6 * fs, y + 54 * fs, f"{t(lang, 'north')}: {(f'{plan.north_deg:.0f}°') if plan.north_deg is not None else '—'}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
