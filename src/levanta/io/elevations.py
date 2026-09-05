"""Interior elevations sheet: every wall seen face-on, with its openings and dimensions.

A plan tells you where things are; an elevation tells you how tall.  Each wall becomes a
strip (length × ceiling height) with doors from the floor up and windows between sill
and head, tagged like on the plan, captioned with its number, the room it belongs to
and the compass direction one faces when looking at it.  The sheet carries its own
title block with the next sheet number.
"""

from __future__ import annotations

from levanta.i18n import fmt_len, t
from levanta.io.draw import Drawing
from levanta.plan.types import FloorPlan

COL = {"wall": "#f1eee8", "edge": "#2b2b2b", "door": "#8a5a2b", "window": "#2b6cb0", "dim": "#777", "dimt": "#444", "lbl": "#222", "sub": "#555"}


def elevations_drawing(
    plan: FloorPlan,
    scale: float = 50.0,
    lang: str = "en",
    units: str = "m",
    max_row_px: float = 1000.0,
    min_len: float = 0.6,
    title_block: bool = True,
    sheet: str | None = None,
    print_scale: int | None = None,
    font_scale: float = 1.0,
    title: str | None = None,
) -> Drawing:
    from levanta.io.plan2d import _title_block, next_sheet, stamp, wall_orientation, wall_tag_point

    fs = font_scale
    walls = [w for w in plan.walls if w.length >= min_len]
    if not walls:
        return Drawing(400, 120)
    gap = 60.0 * fs
    margin = 50.0 * fs
    h_px = plan.ceiling_height * scale
    rows: list[list] = [[]]
    x = 0.0
    for w in walls:
        wpx = w.length * scale
        if rows[-1] and x + wpx > max_row_px:
            rows.append([])
            x = 0.0
        rows[-1].append(w)
        x += wpx + gap
    row_h = h_px + 95.0 * fs
    tb_h = 78.0 * fs if title_block else 0.0
    W = min(max_row_px, max(sum(w.length * scale for w in r) + gap * (len(r) - 1) for r in rows)) + 2 * margin + 60 * fs
    H = margin + 30 * fs + row_h * len(rows) + 30 * fs + tb_h
    d = Drawing(W, H)
    d.text(margin, margin - 12 * fs, f"{t(lang, 'elevations')} · {t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)}", size=14 * fs, weight="bold", anchor="start", color=COL["lbl"])
    room_names = {r.id: r.name for r in plan.rooms}
    y0 = margin + 30 * fs
    for row in rows:
        x0 = margin
        for w in row:
            L = w.length
            wpx = L * scale
            top, bottom = y0, y0 + h_px
            d.polygon([(x0, top), (x0 + wpx, top), (x0 + wpx, bottom), (x0, bottom)], fill=COL["wall"], stroke=COL["edge"], width=1.2 * fs, cls="elev-wall")
            ops = plan.openings_of(w.id)
            for o in ops:
                ox0, ox1 = x0 + o.t0 * scale, x0 + o.t1 * scale
                oy0, oy1 = bottom - o.z0 * scale, bottom - o.z1 * scale
                col = COL["door"] if o.kind == "door" else COL["window"] if o.kind == "window" else COL["edge"]
                d.polygon([(ox0, oy1), (ox1, oy1), (ox1, oy0), (ox0, oy0)], fill="#ffffff", stroke=col, width=1.2 * fs, dash=(5 * fs, 4 * fs) if o.kind == "passage" else None, cls=f"elev-{o.kind}")
                if o.kind == "window":
                    d.line((ox0, (oy0 + oy1) / 2), (ox1, (oy0 + oy1) / 2), stroke=col, width=0.8 * fs)
                    d.line(((ox0 + ox1) / 2, oy0), ((ox0 + ox1) / 2, oy1), stroke=col, width=0.8 * fs)
                elif o.kind == "door":
                    d.line((ox0, oy0), (ox1, oy1), stroke=col, width=0.6 * fs)  # leaf diagonal
                if o.tag:
                    d.text((ox0 + ox1) / 2, oy1 - 5 * fs, o.tag, size=10 * fs, weight="bold", color=col)
                d.text((ox0 + ox1) / 2, oy0 - 5 * fs if o.kind != "window" else oy0 + 12 * fs, fmt_len(o.width, units), size=9 * fs, color=COL["dimt"])
                if o.kind == "window":
                    d.text(ox1 + 4 * fs, (oy0 + oy1) / 2 + 3 * fs, f"{fmt_len(o.z0, units)}–{fmt_len(o.z1, units)}", size=8.5 * fs, anchor="start", color=COL["dimt"])
                else:
                    d.text(ox1 + 4 * fs, oy1 + 10 * fs, fmt_len(o.z1, units), size=8.5 * fs, anchor="start", color=COL["dimt"])
            # dims: length below, height at the left
            yb = bottom + 24 * fs
            d.line((x0, bottom + 6 * fs), (x0, yb + 4 * fs), stroke=COL["dim"], width=0.8 * fs)
            d.line((x0 + wpx, bottom + 6 * fs), (x0 + wpx, yb + 4 * fs), stroke=COL["dim"], width=0.8 * fs)
            d.line((x0, yb), (x0 + wpx, yb), stroke=COL["dim"], width=0.8 * fs)
            d.text(x0 + wpx / 2, yb - 4 * fs, fmt_len(L, units), size=10 * fs, color=COL["dimt"])
            xl = x0 - 18 * fs
            d.line((x0 - 6 * fs, top), (xl - 4 * fs, top), stroke=COL["dim"], width=0.8 * fs)
            d.line((x0 - 6 * fs, bottom), (xl - 4 * fs, bottom), stroke=COL["dim"], width=0.8 * fs)
            d.line((xl, top), (xl, bottom), stroke=COL["dim"], width=0.8 * fs)
            d.text(xl - 4 * fs, (top + bottom) / 2, fmt_len(plan.ceiling_height, units), size=9 * fs, color=COL["dimt"], rotate=90)
            # caption: number · room · orientation
            _, side = wall_tag_point(plan, w)
            rooms_here = sorted({room_names[r] for o in ops for r in o.rooms if r in room_names})
            if not rooms_here:
                from shapely.geometry import Point

                p = w.point_at(w.length / 2) + w.normal * side * (w.thickness / 2 + 0.3)
                rooms_here = [r.name for r in plan.rooms if r.shapely.contains(Point(p))]
            where = ", ".join(rooms_here) if rooms_here else (t(lang, "exterior") if w.exterior else "")
            orient = wall_orientation(w, side, plan.north_deg, lang)
            cap = " · ".join(x for x in (f"{t(lang, 'wall')} {w.id + 1}", where, orient) if x)
            d.text(x0 + wpx / 2, yb + 18 * fs, cap, size=11 * fs, weight="bold", color=COL["lbl"])
            d.text(x0 + wpx / 2, yb + 32 * fs, f"{t(lang, 'thickness')} {fmt_len(w.thickness, units)} ({t(lang, 'measured_short') if w.sides_seen == 2 else t(lang, 'assumed')})", size=9 * fs, color=COL["sub"])
            x0 += wpx + gap
        y0 += row_h
    if title_block:
        _title_block(d, margin, H - tb_h - 10 * fs, W - 2 * margin, tb_h, plan, title, lang, units, scale, print_scale, fs, sheet=sheet or next_sheet(plan.project.get("sheet")), subtitle=t(lang, "elevations"))
    if plan.scale_uncalibrated or plan.unreliable is not None:
        stamp(d, W / 2, (H - tb_h) / 2, min(W, H - tb_h), lang, fs, unreliable=plan.unreliable is not None)
    else:
        d.text(margin, H - 10 * fs, t(lang, "generated_by"), size=10 * fs, anchor="start", color="#666")
    return d
