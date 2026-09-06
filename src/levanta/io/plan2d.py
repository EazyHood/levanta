"""The 2-D floor-plan sheet, drafted the way an architect expects it.

Layers, from the bottom up: rooms, unscanned sides (dashed), reference axes, walls
(openings cut; one-sided walls get a dashed outer face), openings with tags, wall tags
(elevation markers), room labels, dimension chains (perimeter walls outside, interior
partitions inside the larger room), axis chains (distances between axes), overall
dimensions, north arrow, area and opening schedules, general notes, title block.  One
function builds it; SVG, PNG and PDF come from the same primitives.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Sequence
from itertools import pairwise

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from levanta.i18n import fmt_area, fmt_len, t
from levanta.io.draw import Drawing
from levanta.plan.types import FloorPlan, Opening, Wall

# below this, an outline is mostly inference and the label says so
FLOOR_SEEN_NOTE = 0.60

COLORS = {
    "room": "#f6f2ea",
    "room_open": "#f3f0ea",
    "wall": "#2b2b2b",
    "door": "#8a5a2b",
    "window": "#2b6cb0",
    "passage": "#2b2b2b",
    "open_edge": "#9a9a9a",
    "assumed": "#d9d4cb",
    "label": "#222222",
    "sub": "#555555",
    "dim": "#777777",
    "dim_text": "#333333",
    "axis": "#b04a4a",
    "walltag": "#6b6b6f",
    "title": "#111111",
    "meta": "#666666",
    "table": "#333333",
    "rule": "#cfcac2",
}

# metres from the wall face / plan bounds, the way a drafter stacks them
OFF_CHAIN = 0.5  # first chain: corner - jamb - jamb - corner
OFF_AXES = 0.95  # axis-to-axis chain
OFF_OVERALL = 1.05  # overall (bottom, left)
OFF_BUBBLE = 1.35  # axis bubbles (top, right)


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


def room_side_areas(plan: FloorPlan, wall: Wall, probe: float = 0.3) -> tuple[float, float]:
    """Area of the room touching the +normal side and the -normal side (0 if none)."""
    mid = wall.point_at(wall.length / 2)
    n = wall.normal
    d = wall.thickness / 2 + probe
    out = []
    for sign in (1.0, -1.0):
        p = Point(mid + n * sign * d)
        out.append(next((r.area for r in plan.rooms if r.shapely.contains(p)), 0.0))
    return out[0], out[1]


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


def _stations(plan: FloorPlan, w: Wall) -> list[float]:
    st = {0.0, w.length}
    for o in plan.openings_of(w.id):
        st.add(max(0.0, o.t0))
        st.add(min(w.length, o.t1))
    return sorted(st)


def dimension_chains(plan: FloorPlan, min_len: float = 1.0) -> list[dict]:
    """Chains along perimeter walls, drawn on the side with no room:
    ``{wall, side, stations, offset, inside}`` (``offset`` in metres from the centreline)."""
    chains = []
    for w in plan.walls:
        if w.length < min_len:
            continue
        plus, minus = wall_sides(plan, w)
        if plus and minus:
            continue  # interior partition: see interior_chains
        if not plus and not minus:
            continue  # bounds nothing
        side = 1.0 if not plus else -1.0
        chains.append({"wall": w, "side": side, "stations": _stations(plan, w), "offset": w.thickness / 2 + OFF_CHAIN, "inside": False})
    return chains


def interior_chains(plan: FloorPlan, min_len: float = 0.8) -> list[dict]:
    """Chains along interior partitions that carry an opening, drawn inside the larger of
    the two rooms, so every door is positioned from the wall ends."""
    chains = []
    for w in plan.walls:
        if w.length < min_len or not plan.openings_of(w.id):
            continue
        plus, minus = wall_sides(plan, w)
        if not (plus and minus):
            continue
        a_plus, a_minus = room_side_areas(plan, w)
        side = 1.0 if a_plus >= a_minus else -1.0
        chains.append({"wall": w, "side": side, "stations": _stations(plan, w), "offset": w.thickness / 2 + 0.35, "inside": True})
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


def axis_chains(plan: FloorPlan) -> list[dict]:
    """Axis-to-axis dimensions: ``{orientation: 'h'|'v', positions: [...]}``.  The
    horizontal chain (across the top) carries the x of every lettered axis, the vertical
    one (down the right) the y of every numbered axis."""
    letters, numbers = reference_axes(plan)
    out = []
    if len(letters) >= 2:
        out.append({"orientation": "h", "positions": [x for _, x in letters]})
    if len(numbers) >= 2:
        out.append({"orientation": "v", "positions": sorted(y for _, y in numbers)})
    return out


def wall_orientation(wall: Wall, side: float, north_deg: float | None, lang: str = "en") -> str:
    """Compass letter of the direction one faces when looking at the wall from ``side``
    (N/NE/E/SE/S/SW/W/NW; Spanish uses O for west).  Empty when north is unknown."""
    if north_deg is None:
        return ""
    look = -wall.normal * side  # from the room into the wall
    ang_plan = np.degrees(np.arctan2(look[0], look[1]))  # clockwise from +y
    bearing = (ang_plan - north_deg) % 360.0
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] if lang != "es" else ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return names[round(bearing / 45.0) % 8]


def wall_tag_point(plan: FloorPlan, w: Wall, avoid: Sequence[tuple[float, float, float, float]] = (), radius: float = 0.12) -> tuple[np.ndarray, float]:
    """Where the wall tag / elevation marker sits: inside the larger adjoining room, at
    the middle of the longest solid stretch (never on top of a door), and clear of the
    boxes in ``avoid`` (room labels, plan metres) when any position along the wall is."""
    a_plus, a_minus = room_side_areas(plan, w)
    side = 1.0 if a_plus >= a_minus else -1.0
    if a_plus == 0 and a_minus == 0:
        side = 1.0
    st = _stations(plan, w)
    ops = plan.openings_of(w.id)
    solid = []
    for s0, s1 in pairwise(st):
        if any(abs(o.t0 - s0) < 1e-6 and abs(o.t1 - s1) < 1e-6 for o in ops):
            continue  # this stretch is an opening
        solid.append((s1 - s0, (s0 + s1) / 2, s0, s1))
    solid.sort(reverse=True)
    if not solid or solid[0][0] < 0.25:
        # the wall is one opening (a door found between two wall pieces): tag it beside the jamb
        best = -0.18 if w.length < 1.0 else w.length + 0.18
        return w.point_at(best) + w.normal * side * (w.thickness / 2 + 0.28), side
    candidates = [mid for _, mid, _, _ in solid]
    for _, _, s0, s1 in solid:  # then the quarters of every solid stretch
        candidates += [s0 + (s1 - s0) * 0.25, s0 + (s1 - s0) * 0.75]
    offset = w.thickness / 2 + 0.28
    for sd in (side, -side):
        for tpos in candidates:
            pt = w.point_at(tpos) + w.normal * sd * offset
            if not any(bx0 - radius <= pt[0] <= bx1 + radius and by0 - radius <= pt[1] <= by1 + radius for bx0, by0, bx1, by1 in avoid):
                return pt, sd
    return w.point_at(candidates[0]) + w.normal * side * offset, side


def _room_chord(poly, pt: tuple[float, float]) -> float:
    """Length of the horizontal stretch of ``poly`` through ``pt`` (the width a label
    has there), or the bounds width when the point is outside."""
    from shapely.geometry import LineString

    bx0, _by0, bx1, _by1 = poly.bounds
    cut = poly.intersection(LineString([(bx0 - 1, pt[1]), (bx1 + 1, pt[1])]))
    parts = list(cut.geoms) if hasattr(cut, "geoms") else [cut]
    for g in parts:
        if g.geom_type == "LineString" and g.length > 0 and min(x for x, _ in g.coords) - 1e-9 <= pt[0] <= max(x for x, _ in g.coords) + 1e-9:
            return float(g.length)
    return float(bx1 - bx0)


def room_label_specs(plan: FloorPlan, lang: str, units: str, scale: float, fs: float, min_size: float = 6.0) -> list[dict]:
    """Where and how big each room label is drawn: lines (text, size, bold), the anchor in
    plan metres and the box (plan metres) they cover.  Lines that would run past the room
    are shrunk, down to ``min_size`` px; the name and "(incomplete)" go on separate lines
    in a narrow room so a corridor keeps a readable label."""
    from levanta.io.pdf import text_width

    specs = []
    for r in plan.rooms:
        poly = r.shapely
        cx, cy = r.centroid
        if not poly.contains(Point(cx, cy)):
            rp = poly.representative_point()
            cx, cy = float(rp.x), float(rp.y)
        bx0, by0, bx1, by1 = poly.bounds
        avail = max(0.3, _room_chord(poly, (cx, cy)) - 0.16) * scale  # px, wall faces kept clear
        lines = [(r.name, 13.0 * fs, True)]
        # an outline drawn over floor nobody saw is inference, and the sheet says so where
        # the reader looks: beside the room name, not only in the notes
        notes = [] if r.closed else [t(lang, "incomplete")]
        if r.floor_seen is not None and r.floor_seen < FLOOR_SEEN_NOTE:
            notes.append(t(lang, "floor_seen").format(pct=round(100 * r.floor_seen)))
        if notes:
            inc = f"({' · '.join(notes)})"
            if text_width(f"{r.name} {inc}", 13.0 * fs, True) <= avail:
                lines = [(f"{r.name} {inc}", 13.0 * fs, True)]
            else:
                lines.append((inc, 11.0 * fs, False))
        dims = f"{fmt_len(bx1 - bx0, units)} × {fmt_len(by1 - by0, units)}"
        if text_width(f"{fmt_area(r.area, units)} · {dims}", 11.0 * fs, False) <= avail:
            lines.append((f"{fmt_area(r.area, units)} · {dims}", 11.0 * fs, False))
        else:
            lines += [(fmt_area(r.area, units), 11.0 * fs, False), (dims, 11.0 * fs, False)]
        if plan.project.get("level"):
            lines.append((f"{t(lang, 'level_marker')} {plan.project['level']}", 9.5 * fs, False))
        fitted = []
        for text, size, bold in lines:
            w_px = text_width(text, size, bold)
            if w_px > avail:
                size = max(min_size, size * avail / w_px)
            fitted.append((text, size, bold))
        total_h = sum(sz * 1.25 for _, sz, _ in fitted)
        width_px = max(text_width(tx, sz, b) for tx, sz, b in fitted)
        specs.append({"room": r, "x": cx, "y": cy, "lines": fitted, "box": (cx - width_px / 2 / scale, cy - total_h / 2 / scale, cx + width_px / 2 / scale, cy + total_h / 2 / scale)})
    return specs


def stamp(d: Drawing, cx: float, cy: float, extent: float, lang: str, fs: float, unreliable: bool = False) -> None:
    """A diagonal "PRELIMINARY - scale not calibrated" across the drawing, sized to it;
    "NOT RECONSTRUCTIBLE - mirror or glass" when the reconstruction itself broke."""
    from levanta.io.pdf import text_width

    text = t(lang, "stamp_unreliable" if unreliable else "stamp")
    size = max(12.0 * fs, min(extent / 9.0, 0.9 * extent * 1.25 / max(text_width(text, 1.0, True), 1e-6)))
    d.text(cx, cy + size * 0.35, text, size=size, weight="bold", color="#e07070" if unreliable else "#e8a0a0", rotate=28.0, cls="stamp")


def next_sheet(sheet: str | None) -> str:
    """'A-01' -> 'A-02', 'A1' -> 'A2', None -> 'A-02'."""
    if not sheet:
        return "A-02"
    m = re.search(r"(\d+)(?!.*\d)", sheet)
    if not m:
        return sheet + "-2"
    n = int(m.group(1)) + 1
    return sheet[: m.start(1)] + str(n).zfill(len(m.group(1))) + sheet[m.end(1) :]


def general_notes(plan: FloorPlan, lang: str, units: str) -> list[str]:
    """What a reader must know before trusting the sheet: assumed thicknesses, open sides,
    default ceiling, assumed door heights, uncalibrated scale."""
    notes: list[str] = []
    one = [w for w in plan.walls if w.sides_seen == 1]
    if one:
        by_th: dict[float, list[int]] = {}
        for w in one:
            by_th.setdefault(round(w.thickness, 2), []).append(w.id + 1)
        for th, ids in sorted(by_th.items()):
            notes.append(t(lang, "note_assumed_thickness").format(walls=", ".join(f"M{i}" for i in ids), th=fmt_len(th, units)))
    for q in plan.quality(lang):
        if q["level"] == "ok" or q.get("key") == "thickness":
            continue  # the per-wall note above already covers assumed thicknesses
        notes.append(q["text"])
    return notes


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
    tables: str = "right",
    print_scale: int | None = None,
    font_scale: float = 1.0,
    notes: list[str] | None = None,
) -> Drawing:
    """Build the plan sheet.  ``scale`` is pixels (or points) per metre.

    ``tables``: ``"right"`` (schedules beside the plan) or ``"below"`` (under it, side
    by side).  ``print_scale`` (e.g. 100 for 1:100) is printed in the title block; the
    caller picks ``scale`` accordingly.  ``notes`` are extra general notes.
    """
    fs = font_scale
    xmin, ymin, xmax, ymax = plan.bounds
    if xmax - xmin < 1e-6:
        xmin, xmax = xmin - 1, xmax + 1
    if ymax - ymin < 1e-6:
        ymin, ymax = ymin - 1, ymax + 1
    chains = (dimension_chains(plan) + interior_chains(plan)) if (show_chains and show_dimensions) else []
    letters, numbers = reference_axes(plan) if show_axes else ([], [])
    axes_ch = axis_chains(plan) if (show_axes and show_dimensions) else []
    # space around the plan, in metres
    m_left = OFF_OVERALL + 0.35 if show_dimensions else 0.4
    m_bottom = OFF_OVERALL + 0.35 if show_dimensions else 0.4
    m_top = (OFF_BUBBLE + 0.3) if letters else (0.9 if chains else 0.4)
    m_right = (OFF_BUBBLE + 0.3) if numbers else (0.9 if chains else 0.4)
    if plan.north_deg is not None:
        m_top = max(m_top, 1.1)
        m_left = max(m_left, 1.5)
    pad = 24.0 * fs if margin is None else margin
    plan_w = (xmax - xmin + m_left + m_right) * scale
    plan_h = (ymax - ymin + m_top + m_bottom) * scale
    have_tables = bool(show_tables and (plan.rooms or plan.openings))
    table_w = 260.0 * fs if have_tables else 0.0
    tb_h = 78.0 * fs if show_title_block else 0.0
    all_notes = general_notes(plan, lang, units) + list(notes or [])
    notes_h = (16 + 13 * (len(all_notes) + sum(len(n) // 72 for n in all_notes))) * fs if all_notes else 0.0
    n_rows = len(plan.rooms) + 4 + (len(plan.openings) + 3 if plan.openings else 0)
    tables_h = (34 + 15 * n_rows + 30) * fs if have_tables else 0.0
    below = tables == "below" and have_tables
    if below:
        block_h = max(tables_h, notes_h + 10 * fs) if (2 * table_w + 40 * fs + 260 * fs) <= max(plan_w, 2 * table_w + 40 * fs) else tables_h + notes_h + 10 * fs
        W = pad + max(plan_w, 2 * table_w + 40 * fs) + pad
        H = pad + plan_h + block_h + 10 * fs + tb_h + pad
    else:
        side_w = (16 * fs + table_w) if have_tables else 0.0
        W = pad + plan_w + side_w + pad
        H = pad + max(plan_h, tables_h + notes_h + 20 * fs) + tb_h + pad
    d = Drawing(W, H)

    ox = pad + m_left * scale
    oy = pad + m_top * scale
    d.meta.update({"ox": ox, "oy": oy, "scale": scale, "xmin": xmin, "ymax": ymax})  # X(x) = ox + (x - xmin) * scale, Y(y) = oy + (ymax - y) * scale

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
    for lab, x in letters:
        d.line((X(x), Y(ymax) - (OFF_BUBBLE - 0.12) * scale), (X(x), Y(ymin) + 0.2 * scale), stroke=COLORS["axis"], width=0.6 * fs, dash=(9 * fs, 5 * fs), cls="axis")
        cy = Y(ymax) - OFF_BUBBLE * scale
        d.circle(X(x), cy, 9 * fs, fill="#ffffff", stroke=COLORS["axis"], width=0.9 * fs, cls="axis")
        d.text(X(x), cy + 3.5 * fs, lab, size=10 * fs, weight="bold", color=COLORS["axis"], cls="axis")
    for lab, y in numbers:
        d.line((X(xmin) - 0.2 * scale, Y(y)), (X(xmax) + (OFF_BUBBLE - 0.12) * scale, Y(y)), stroke=COLORS["axis"], width=0.6 * fs, dash=(9 * fs, 5 * fs), cls="axis")
        cx = X(xmax) + OFF_BUBBLE * scale
        d.circle(cx, Y(y), 9 * fs, fill="#ffffff", stroke=COLORS["axis"], width=0.9 * fs, cls="axis")
        d.text(cx, Y(y) + 3.5 * fs, lab, size=10 * fs, weight="bold", color=COLORS["axis"], cls="axis")
    # walls (openings cut)
    for poly in wall_body_polygons(plan):
        d.polygon(P(list(poly.exterior.coords)), fill=COLORS["wall"], holes=[P(list(ring.coords)) for ring in poly.interiors], cls="wall")
    # one-sided walls: the unseen face is drawn dashed on top of the body
    for w in plan.walls:
        if w.sides_seen == 2:
            continue
        plus, minus = wall_sides(plan, w)
        unseen = -1.0 if plus and not minus else 1.0 if minus and not plus else None
        if unseen is None:
            continue
        a = np.array(w.a) + w.normal * unseen * (w.thickness / 2 - 0.01)
        b = np.array(w.b) + w.normal * unseen * (w.thickness / 2 - 0.01)
        d.line((X(a[0]), Y(a[1])), (X(b[0]), Y(b[1])), stroke=COLORS["assumed"], width=1.3 * fs, dash=(5 * fs, 4 * fs), cls="wall-assumed")
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
            plus, _ = wall_sides(plan, w)
            tag_pt = (a + b) / 2 + n * (1.0 if plus else -1.0) * (w.thickness / 2 + 0.22)
        if o.tag and show_labels:
            col = COLORS["door"] if o.kind == "door" else COLORS["window"] if o.kind == "window" else COLORS["label"]
            d.text(X(tag_pt[0]), Y(tag_pt[1]) + 3.5 * fs, o.tag, size=9.5 * fs, weight="bold", color=col, cls="tag")
    # wall tags: elevation markers (circle with the wall number, pointer towards the wall)
    label_specs = room_label_specs(plan, lang, units, scale, fs) if show_labels else []
    if show_labels:
        for w in plan.walls:
            if w.length < 0.6:
                continue
            p, side = wall_tag_point(plan, w, avoid=[sp["box"] for sp in label_specs], radius=(7 * fs + 2) / scale)
            n = w.normal * side
            r = 7 * fs
            cx, cy = X(p[0]), Y(p[1])
            edge = p - n * 0.09
            face = p - n * 0.2
            d.line((X(edge[0]), Y(edge[1])), (X(face[0]), Y(face[1])), stroke=COLORS["walltag"], width=0.9 * fs, cls="wall-tag-pointer")
            d.circle(cx, cy, r, fill="#ffffff", stroke=COLORS["walltag"], width=0.9 * fs, cls="wall-tag-circle")
            d.text(cx, cy + 3 * fs, f"M{w.id + 1}", size=7.5 * fs, weight="bold", color=COLORS["walltag"], cls="wall-tag")
    # room labels (name, "(incomplete)", area and size, level), sized to the room
    for sp in label_specs:
        total_h = sum(sz * 1.25 for _, sz, _ in sp["lines"])
        y = Y(sp["y"]) - total_h / 2
        for i, (text, size, bold) in enumerate(sp["lines"]):
            y += size * 1.25
            d.text(X(sp["x"]), y - size * 0.3, text, size=size, weight="bold" if bold else "normal", color=COLORS["label"] if i == 0 else COLORS["sub"], cls="label")
    # dimension chains (perimeter outside, partitions inside)
    for ch in chains:
        _draw_chain(d, ch, X, Y, scale, units, fs)
    # axis chains: across the top (letters) and down the right (numbers)
    for ac in axes_ch:
        _draw_axis_chain(d, ac, X, Y, scale, units, fs, xmin, ymin, xmax, ymax)
    # overall dimensions (further out)
    if show_dimensions:
        off = OFF_OVERALL * scale
        yb = Y(ymin) + off
        _dim_line(d, (X(xmin), yb), (X(xmax), yb), fmt_len(xmax - xmin, units), fs, ext_from=((X(xmin), Y(ymin) + 6 * fs), (X(xmax), Y(ymin) + 6 * fs)))
        xl = X(xmin) - off
        _dim_line(d, (xl, Y(ymin)), (xl, Y(ymax)), fmt_len(ymax - ymin, units), fs, ext_from=((X(xmin) - 6 * fs, Y(ymin)), (X(xmin) - 6 * fs, Y(ymax))), vertical=True)
    # north arrow
    if plan.north_deg is not None:
        _north_arrow(d, X(xmin) - 1.05 * scale, oy - 0.45 * scale, plan.north_deg, fs, lang)
    if plan.scale_uncalibrated or plan.unreliable is not None:
        stamp(d, X((xmin + xmax) / 2), Y((ymin + ymax) / 2), min(plan_w, plan_h), lang, fs, unreliable=plan.unreliable is not None)
    # tables + notes
    if have_tables:
        if below:
            tx1, ty0 = pad, pad + plan_h + 8 * fs
            ty = _areas_table(d, tx1, ty0, table_w, plan, lang, units, fs)
            tx2 = tx1 + table_w + 40 * fs
            ty2 = _schedule_table(d, tx2, ty0, table_w, plan, lang, units, fs) if plan.openings else ty0
            if all_notes:
                tx3 = tx2 + table_w + 40 * fs
                if W - pad - tx3 >= 260 * fs:
                    _notes_block(d, tx3, ty0, all_notes, lang, fs)
                else:
                    _notes_block(d, tx1, max(ty, ty2) + 12 * fs, all_notes, lang, fs)
        else:
            tx = pad + plan_w + 16 * fs
            ty = _areas_table(d, tx, pad, table_w, plan, lang, units, fs)
            if plan.openings:
                ty = _schedule_table(d, tx, ty + 18 * fs, table_w, plan, lang, units, fs)
            if all_notes:
                _notes_block(d, tx, ty + 18 * fs, all_notes, lang, fs)
    elif all_notes:
        _notes_block(d, pad, pad + plan_h, all_notes, lang, fs)
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
    off = ch["offset"]
    cls = "dim-chain-in" if ch.get("inside") else "dim-chain"
    stations = ch["stations"]
    base = np.array(w.a, dtype=float)
    line_a = base + n * off
    line_b = base + dvec * w.length + n * off
    d.line((X(line_a[0]), Y(line_a[1])), (X(line_b[0]), Y(line_b[1])), stroke=COLORS["dim"], width=0.8 * fs, cls=cls)
    vertical = abs(dvec[0]) < 0.5
    for s in stations:
        p_wall = base + dvec * s + n * (w.thickness / 2 + 0.06)
        p_dim = base + dvec * s + n * off
        d.line((X(p_wall[0]), Y(p_wall[1])), (X(p_dim[0]), Y(p_dim[1])), stroke=COLORS["dim"], width=0.6 * fs, cls=cls)
        _tick(d, X(p_dim[0]), Y(p_dim[1]), fs)
    for s0, s1 in pairwise(stations):
        if s1 - s0 < 0.1:
            continue
        mid = base + dvec * ((s0 + s1) / 2) + n * off
        label = fmt_len(s1 - s0, units)
        tp = mid + n * 0.08
        if vertical:
            d.text(X(tp[0]), Y(tp[1]), label, size=9.5 * fs, color=COLORS["dim_text"], rotate=90, cls=cls)
        else:
            d.text(X(tp[0]), Y(tp[1]) + (3.5 * fs if n[1] < 0 else 0), label, size=9.5 * fs, color=COLORS["dim_text"], cls=cls)


def _draw_axis_chain(d: Drawing, ac: dict, X, Y, scale: float, units: str, fs: float, xmin, ymin, xmax, ymax) -> None:
    pos = ac["positions"]
    if ac["orientation"] == "h":
        y = Y(ymax) - OFF_AXES * scale
        d.line((X(pos[0]), y), (X(pos[-1]), y), stroke=COLORS["dim"], width=0.8 * fs, cls="dim-axes")
        for x in pos:
            _tick(d, X(x), y, fs)
        for x0, x1 in pairwise(pos):
            d.text((X(x0) + X(x1)) / 2, y - 4 * fs, fmt_len(x1 - x0, units), size=9.5 * fs, color=COLORS["dim_text"], cls="dim-axes")
    else:
        x = X(xmax) + OFF_AXES * scale
        d.line((x, Y(pos[0])), (x, Y(pos[-1])), stroke=COLORS["dim"], width=0.8 * fs, cls="dim-axes")
        for y in pos:
            _tick(d, x, Y(y), fs)
        for y0, y1 in pairwise(pos):
            d.text(x + 4 * fs, (Y(y0) + Y(y1)) / 2, fmt_len(y1 - y0, units), size=9.5 * fs, color=COLORS["dim_text"], rotate=90, cls="dim-axes")


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
    def seen(r) -> str:
        return "" if r.floor_seen is None else f"{round(100 * r.floor_seen)} %"

    rows = [[r.name + ("" if r.closed else " *"), fmt_area(r.area, units), fmt_len(r.perimeter, units), seen(r)] for r in plan.rooms]
    summ = plan.area_summary()
    rows.append([t(lang, "useful_area"), fmt_area(summ["useful_m2"], units), "", ""])
    rows.append([t(lang, "walls_area"), fmt_area(summ["walls_m2"], units), fmt_len(summ["wall_length_m"], units), ""])
    rows.append([t(lang, "gross_area"), fmt_area(summ["gross_m2"], units), "", ""])
    head = [t(lang, "name"), t(lang, "area"), t(lang, "perimeter"), t(lang, "floor_seen_col")]
    y = _table(d, x, y, w, t(lang, "areas_table"), head, rows, [0.34, 0.21, 0.23, 0.22], fs, ["start", "end", "end", "end"])
    if any(not r.closed for r in plan.rooms):
        d.text(x, y + 11 * fs, f"* {t(lang, 'incomplete')}", size=8 * fs, anchor="start", color=COLORS["sub"], cls="table")
        y += 12 * fs
    return y


def _schedule_table(d: Drawing, x: float, y: float, w: float, plan: FloorPlan, lang: str, units: str, fs: float) -> float:
    rows = []
    for o in sorted(plan.openings, key=lambda o: (o.kind, o.tag)):
        h = fmt_len(o.z1 - o.z0, units)
        rows.append([o.tag or "-", t(lang, o.kind), fmt_len(o.width, units), h, fmt_len(o.z0, units) if o.kind == "window" else "-", f"M{o.wall_id + 1}"])
    return _table(d, x, y, w, t(lang, "schedule"), [t(lang, "tag"), t(lang, "kind"), t(lang, "width"), "H", t(lang, "sill"), t(lang, "wall")], rows, [0.11, 0.21, 0.16, 0.14, 0.23, 0.15], fs, ["start", "start", "end", "end", "end", "end"])


def _notes_block(d: Drawing, x: float, y: float, notes: list[str], lang: str, fs: float) -> float:
    d.text(x, y + 11 * fs, t(lang, "notes"), size=11 * fs, weight="bold", anchor="start", color=COLORS["table"], cls="notes")
    y += 16 * fs
    for i, n in enumerate(notes):
        words = n.split()
        lines, cur = [], ""
        for wd in words:
            if len(cur) + len(wd) + 1 > 72:
                lines.append(cur)
                cur = wd
            else:
                cur = (cur + " " + wd).strip()
        if cur:
            lines.append(cur)
        for k, ln in enumerate(lines):
            d.text(x, y + 11 * fs, (f"{i + 1}. " if k == 0 else "    ") + ln, size=8.5 * fs, anchor="start", color=COLORS["table"], cls="notes")
            y += 12.5 * fs
    return y


def _title_block(d: Drawing, x: float, y: float, w: float, h: float, plan: FloorPlan, title: str | None, lang: str, units: str, scale: float, print_scale: int | None, fs: float, sheet: str | None = None, subtitle: str | None = None) -> None:
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
    d.text(x + 6 * fs, y + 54 * fs, f"{t(lang, 'plan_title')}: {subtitle or title or t(lang, 'floor_plan')}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
    ceil = f"{t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)} ({t(lang, 'measured') if plan.ceiling_measured else t(lang, 'default')})"
    d.text(x + 6 * fs, y + 68 * fs, f"{len(plan.rooms)} {t(lang, 'rooms')} · {fmt_area(plan.total_area, units)} · {ceil}", size=8.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
    cell(1, t(lang, "author"), pr.get("author") or "—")
    d.text(x + cols[1] * w + 6 * fs, y + 54 * fs, f"{t(lang, 'level')}: {pr.get('level') or '±0.00'}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
    d.text(x + cols[1] * w + 6 * fs, y + 68 * fs, t(lang, "generated_by"), size=8.5 * fs, anchor="start", color=COLORS["meta"], cls="titleblock")
    cell(2, t(lang, "scale"), (f"1:{print_scale}" if print_scale else "—") + (f" · {t(lang, 'stamp_short')}" if plan.scale_uncalibrated else ""))
    sx = x + cols[2] * w + 6 * fs
    sy = y + 58 * fs
    bar = scale
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
    cell(4, t(lang, "sheet"), sheet or pr.get("sheet") or "A-01")
    d.text(x + cols[4] * w + 6 * fs, y + 54 * fs, f"{t(lang, 'north')}: {(f'{plan.north_deg:.0f}°') if plan.north_deg is not None else '—'}", size=9.5 * fs, anchor="start", color=COLORS["sub"], cls="titleblock")
