"""Interior elevations: every wall seen face-on, with its openings and dimensions.

A plan tells you where things are; an elevation tells you how tall.  Each wall becomes a
strip (length × ceiling height) with doors from the floor up and windows between sill
and head, tagged like on the plan.
"""

from __future__ import annotations

from levanta.i18n import fmt_len, t
from levanta.io.draw import Drawing
from levanta.plan.types import FloorPlan

COL = {"wall": "#f1eee8", "edge": "#2b2b2b", "door": "#8a5a2b", "window": "#2b6cb0", "dim": "#777", "dimt": "#444", "lbl": "#222", "sub": "#555"}


def elevations_drawing(plan: FloorPlan, scale: float = 50.0, lang: str = "en", units: str = "m", max_row_px: float = 1000.0, min_len: float = 0.6) -> Drawing:
    walls = [w for w in plan.walls if w.length >= min_len]
    if not walls:
        return Drawing(400, 120)
    gap = 60.0
    margin = 50.0
    h_px = plan.ceiling_height * scale
    # lay strips out in rows
    rows: list[list] = [[]]
    x = 0.0
    for w in walls:
        wpx = w.length * scale
        if rows[-1] and x + wpx > max_row_px:
            rows.append([])
            x = 0.0
        rows[-1].append(w)
        x += wpx + gap
    row_h = h_px + 95.0
    W = min(max_row_px, max(sum(w.length * scale for w in r) + gap * (len(r) - 1) for r in rows)) + 2 * margin + 60
    H = margin + 30 + row_h * len(rows) + 30
    d = Drawing(W, H)
    d.text(margin, margin - 12, f"{t(lang, 'elevations')} · {t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)}", size=14, weight="bold", anchor="start", color=COL["lbl"])
    room_names = {r.id: r.name for r in plan.rooms}
    y0 = margin + 30
    for row in rows:
        x0 = margin
        for w in row:
            L = w.length
            wpx = L * scale
            top, bottom = y0, y0 + h_px
            d.polygon([(x0, top), (x0 + wpx, top), (x0 + wpx, bottom), (x0, bottom)], fill=COL["wall"], stroke=COL["edge"], width=1.2, cls="elev-wall")
            ops = plan.openings_of(w.id)
            for o in ops:
                ox0, ox1 = x0 + o.t0 * scale, x0 + o.t1 * scale
                oy0, oy1 = bottom - o.z0 * scale, bottom - o.z1 * scale
                col = COL["door"] if o.kind == "door" else COL["window"] if o.kind == "window" else COL["edge"]
                d.polygon([(ox0, oy1), (ox1, oy1), (ox1, oy0), (ox0, oy0)], fill="#ffffff", stroke=col, width=1.2, dash=(5, 4) if o.kind == "passage" else None, cls=f"elev-{o.kind}")
                if o.kind == "window":
                    d.line((ox0, (oy0 + oy1) / 2), (ox1, (oy0 + oy1) / 2), stroke=col, width=0.8)
                    d.line(((ox0 + ox1) / 2, oy0), ((ox0 + ox1) / 2, oy1), stroke=col, width=0.8)
                elif o.kind == "door":
                    d.line((ox0, oy0), (ox1, oy1), stroke=col, width=0.6)  # leaf diagonal
                if o.tag:
                    d.text((ox0 + ox1) / 2, oy1 - 5, o.tag, size=10, weight="bold", color=col)
                # width and height of the opening
                d.text((ox0 + ox1) / 2, oy0 - 5 if o.kind != "window" else oy0 + 12, fmt_len(o.width, units), size=9, color=COL["dimt"])
                if o.kind == "window":
                    d.text(ox1 + 4, (oy0 + oy1) / 2 + 3, f"{fmt_len(o.z0, units)}–{fmt_len(o.z1, units)}", size=8.5, anchor="start", color=COL["dimt"])
                else:
                    d.text(ox1 + 4, oy1 + 10, fmt_len(o.z1, units), size=8.5, anchor="start", color=COL["dimt"])
            # dims: length below, height at the left
            yb = bottom + 24
            d.line((x0, bottom + 6), (x0, yb + 4), stroke=COL["dim"], width=0.8)
            d.line((x0 + wpx, bottom + 6), (x0 + wpx, yb + 4), stroke=COL["dim"], width=0.8)
            d.line((x0, yb), (x0 + wpx, yb), stroke=COL["dim"], width=0.8)
            d.text(x0 + wpx / 2, yb - 4, fmt_len(L, units), size=10, color=COL["dimt"])
            xl = x0 - 18
            d.line((x0 - 6, top), (xl - 4, top), stroke=COL["dim"], width=0.8)
            d.line((x0 - 6, bottom), (xl - 4, bottom), stroke=COL["dim"], width=0.8)
            d.line((xl, top), (xl, bottom), stroke=COL["dim"], width=0.8)
            d.text(xl - 4, (top + bottom) / 2, fmt_len(plan.ceiling_height, units), size=9, color=COL["dimt"], rotate=90)
            # caption
            rooms_here = sorted({room_names[r] for o in ops for r in o.rooms if r in room_names})
            side = t(lang, "exterior") if w.exterior else (", ".join(rooms_here) if rooms_here else "")
            cap = f"{t(lang, 'wall')} {w.id + 1} · {side}" if side else f"{t(lang, 'wall')} {w.id + 1}"
            d.text(x0 + wpx / 2, yb + 18, cap, size=11, weight="bold", color=COL["lbl"])
            d.text(x0 + wpx / 2, yb + 32, f"{t(lang, 'thickness')} {fmt_len(w.thickness, units)} ({t(lang, 'measured_short') if w.sides_seen == 2 else t(lang, 'assumed')})", size=9, color=COL["sub"])
            x0 += wpx + gap
        y0 += row_h
    d.text(margin, H - 10, t(lang, "generated_by"), size=10, anchor="start", color="#666")
    return d
