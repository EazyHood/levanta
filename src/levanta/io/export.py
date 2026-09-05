"""Writers: SVG/PNG/PDF (plan sheet), elevations, HTML (viewer), DXF 2D/3D (CAD), GLB/OBJ (3D), JSON."""

from __future__ import annotations

import datetime as _dt
import itertools
from pathlib import Path

import numpy as np

from levanta.i18n import fmt_area, fmt_len, t
from levanta.io.draw import Drawing
from levanta.io.elevations import elevations_drawing
from levanta.io.iso import isometric_drawing, model_faces
from levanta.io.pdf import PT_PER_MM, page_size_pt, write_pdf
from levanta.io.plan2d import (
    dimension_chains,
    floor_plan_drawing,
    reference_axes,
    swing_side,
    wall_body_polygons,
    wall_sides,
)
from levanta.plan.model import floor_plan_to_scene
from levanta.plan.types import FloorPlan

__all__ = [
    "export_all",
    "export_dxf",
    "export_dxf_3d",
    "export_elevations_pdf",
    "export_elevations_png",
    "export_glb",
    "export_html",
    "export_iso_png",
    "export_iso_svg",
    "export_json",
    "export_obj",
    "export_pdf",
    "export_png",
    "export_svg",
    "wall_body_polygons",
]

PRINT_SCALES = (20, 25, 50, 75, 100, 125, 150, 200, 250, 500)


# ----------------------------------------------------------------------------------------
# 2-D plan sheet
# ----------------------------------------------------------------------------------------


def export_svg(plan: FloorPlan, path: str | Path, scale: float = 80.0, title: str | None = None, lang: str = "en", units: str = "m", **kw) -> Path:
    """Architectural plan sheet as SVG.  ``scale`` is pixels per metre."""
    return floor_plan_drawing(plan, scale=scale, title=title, lang=lang, units=units, **kw).save_svg(path)


def export_png(plan: FloorPlan, path: str | Path, scale: float = 80.0, title: str | None = None, lang: str = "en", units: str = "m", dpi_scale: float = 2.0, **kw) -> Path:
    """Same sheet as a PNG (``dpi_scale`` times the SVG pixel size)."""
    return floor_plan_drawing(plan, scale=scale, title=title, lang=lang, units=units, **kw).save_png(path, scale=dpi_scale)


def fit_print_scale(plan: FloorPlan, paper: str = "A4", orientation: str = "landscape", margin_mm: float = 10.0, lang: str = "en", units: str = "m", title: str | None = None, scale: int | None = None, **kw):
    """Pick the largest standard scale (1:20 ... 1:500) and the table layout (beside or
    below the plan) at which the whole sheet fits the page, preferring the layout that
    fills the page best.  When the next larger scale does not fit, the sheet says so in
    its notes.

    Returns ``(drawing, page_w_pt, page_h_pt, offset_x, offset_y, print_scale, info)`` with
    ``info = {scale, layout, fill, next_scale, next_scale_fits}``; ``fill`` is the share
    of the usable page taken by the plan itself (walls plus dimensions).
    """
    pw, ph = page_size_pt(paper, orientation)
    usable_w, usable_h = pw - 2 * margin_mm * PT_PER_MM, ph - 2 * margin_mm * PT_PER_MM
    candidates = [scale] if scale else list(PRINT_SCALES)
    fits_at: dict[int, list[tuple[float, str, Drawing]]] = {}
    last = None
    for s in candidates:
        pt_per_m = 1000.0 / s * PT_PER_MM  # 1 m on paper = 1000/s mm
        for layout in ("below", "right"):
            d = floor_plan_drawing(plan, scale=pt_per_m, margin=margin_mm * PT_PER_MM, lang=lang, units=units, title=title, print_scale=s, font_scale=0.78, tables=layout, **kw)
            last = (d, s, layout)
            if d.width <= pw and d.height <= ph:
                xmin, ymin, xmax, ymax = plan.bounds
                plan_area = ((xmax - xmin) + 2.7) * ((ymax - ymin) + 2.7) * pt_per_m * pt_per_m
                fill = min(1.0, plan_area / (usable_w * usable_h))
                fits_at.setdefault(s, []).append((fill, layout, d))
        if s in fits_at:
            break
    if fits_at:
        s = min(fits_at)
        fill, layout, d = max(fits_at[s], key=lambda x: x[0])
    else:  # nothing fits even at 1:500: use the last drawing scaled down by the caller
        d, s, layout = last
        fill = 0.0
    idx = PRINT_SCALES.index(s) if s in PRINT_SCALES else 0
    next_scale = PRINT_SCALES[idx - 1] if idx > 0 else None
    next_fits = None
    if next_scale is not None:
        pt_next = 1000.0 / next_scale * PT_PER_MM
        next_fits = any(
            (dd := floor_plan_drawing(plan, scale=pt_next, margin=margin_mm * PT_PER_MM, lang=lang, units=units, title=title, print_scale=next_scale, font_scale=0.78, tables=lay, **kw)).width <= pw and dd.height <= ph
            for lay in ("below", "right")
        )
    info = {"scale": s, "layout": layout, "fill": float(fill), "next_scale": next_scale, "next_scale_fits": next_fits}
    if next_scale is not None and next_fits is False and fill < 0.6:
        note = t(lang, "note_scale_fit").format(s=s, next=next_scale, paper=paper)
        pt_per_m = 1000.0 / s * PT_PER_MM
        d = floor_plan_drawing(plan, scale=pt_per_m, margin=margin_mm * PT_PER_MM, lang=lang, units=units, title=title, print_scale=s, font_scale=0.78, tables=layout, notes=[note], **kw)
    ox = max(0.0, (pw - d.width) / 2)
    oy = max(0.0, (ph - d.height) / 2)
    return d, pw, ph, ox, oy, s, info


def fit_elevations_scale(plan: FloorPlan, pw: float, ph: float, start: int, lang: str, units: str, title: str | None, margin_mm: float = 10.0) -> tuple[Drawing, int]:
    """Largest standard scale at which the elevations sheet fits the page unscaled."""
    scales = [s for s in PRINT_SCALES if s >= start] or [PRINT_SCALES[-1]]
    last = None
    for s in scales:
        pt_per_m = 1000.0 / s * PT_PER_MM
        e = elevations_drawing(plan, scale=pt_per_m, lang=lang, units=units, max_row_px=pw - 2 * margin_mm * PT_PER_MM - 100, print_scale=s, font_scale=0.78, title=title)
        last = (e, s)
        if e.width <= pw and e.height <= ph:
            return e, s
    return last


def export_pdf(plan: FloorPlan, path: str | Path, paper: str = "A4", orientation: str = "landscape", title: str | None = None, lang: str = "en", units: str = "m", scale: int | None = None, with_elevations: bool = True, **kw) -> Path:
    """Vector PDF at a standard scale (1:50, 1:100 ...) on a standard page, plus a second
    page with the interior elevations."""
    d, pw, ph, ox, oy, s, _info = fit_print_scale(plan, paper, orientation, lang=lang, units=units, title=title, scale=scale, **kw)
    pages = [(d, pw, ph, ox, oy, 1.0)]
    if with_elevations and plan.walls:
        e, _se = fit_elevations_scale(plan, pw, ph, max(s, 25), lang, units, title)
        sc = min(1.0, (pw - 20 * PT_PER_MM) / e.width, (ph - 20 * PT_PER_MM) / e.height)
        pages.append((e, pw, ph, (pw - e.width * sc) / 2, (ph - e.height * sc) / 2, sc))
    return write_pdf(path, pages, title=title or t(lang, "floor_plan"))


def export_elevations_png(plan: FloorPlan, path: str | Path, lang: str = "en", units: str = "m", dpi_scale: float = 2.0) -> Path:
    return elevations_drawing(plan, lang=lang, units=units).save_png(path, scale=dpi_scale)


def export_elevations_pdf(plan: FloorPlan, path: str | Path, paper: str = "A4", orientation: str = "landscape", lang: str = "en", units: str = "m") -> Path:
    pw, ph = page_size_pt(paper, orientation)
    e = elevations_drawing(plan, scale=1000.0 / 50 * PT_PER_MM, lang=lang, units=units, max_row_px=pw - 24 * PT_PER_MM)
    sc = min(1.0, (pw - 20 * PT_PER_MM) / e.width, (ph - 20 * PT_PER_MM) / e.height)
    return write_pdf(path, [(e, pw, ph, (pw - e.width * sc) / 2, (ph - e.height * sc) / 2, sc)], title=t(lang, "elevations"))


def export_iso_svg(plan: FloorPlan, path: str | Path, lang: str = "en", include_ceiling: bool = False, **kw) -> Path:
    return isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling, **kw).save_svg(path)


def export_iso_png(plan: FloorPlan, path: str | Path, lang: str = "en", include_ceiling: bool = False, dpi_scale: float = 2.0, **kw) -> Path:
    return isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling, **kw).save_png(path, scale=dpi_scale)


# ----------------------------------------------------------------------------------------
# DXF
# ----------------------------------------------------------------------------------------

# AIA-style layer names: (color index, lineweight in 1/100 mm, linetype)
LAYERS = {
    "A-WALL": (7, 50, "CONTINUOUS"),
    "A-WALL-PATT": (8, 13, "CONTINUOUS"),
    "A-AREA": (3, 18, "CONTINUOUS"),
    "A-AREA-OPEN": (8, 18, "DASHED"),
    "A-DOOR": (30, 25, "CONTINUOUS"),
    "A-GLAZ": (5, 25, "CONTINUOUS"),
    "A-OPEN": (8, 18, "DASHED"),
    "A-ANNO-TEXT": (7, 18, "CONTINUOUS"),
    "A-ANNO-DIMS": (4, 13, "CONTINUOUS"),
    "A-GRID": (1, 13, "CENTER"),
    "A-ANNO-TTLB": (7, 35, "CONTINUOUS"),
    "A-ANNO-TABL": (7, 18, "CONTINUOUS"),
    "A-ANNO-NORTH": (7, 25, "CONTINUOUS"),
}
DXF_UNITS = {"m": (1.0, 6), "cm": (100.0, 5), "mm": (1000.0, 4)}


def export_dxf(plan: FloorPlan, path: str | Path, show_dimensions: bool = True, lang: str = "en", dxf_units: str = "m", title: str | None = None) -> Path:
    """AutoCAD 2010 DXF with normalised layers, lineweights, door/window blocks,
    dimension chains, reference axes, area and opening schedules and a title block.

    ``dxf_units``: 'm' (default), 'cm' or 'mm'; $INSUNITS is set accordingly."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    k, insunits = DXF_UNITS.get(dxf_units, DXF_UNITS["m"])
    path = Path(path)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = insunits
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1
    for name, (color, lw, lt) in LAYERS.items():
        doc.layers.add(name, color=color, lineweight=lw, linetype=lt if lt in doc.linetypes else "CONTINUOUS")
    th_text = 0.12 * k
    doc.dimstyles.new(
        "LEVANTA",
        dxfattribs={"dimtxt": th_text, "dimasz": 0.08 * k, "dimexe": 0.05 * k, "dimexo": 0.05 * k, "dimdec": 2 if dxf_units == "m" else 0, "dimtad": 1, "dimgap": 0.03 * k, "dimtih": 0, "dimtoh": 0, "dimlfac": 1.0},
    )
    msp = doc.modelspace()

    def S(p):
        return (float(p[0]) * k, float(p[1]) * k)

    # blocks: unit door (hinge at origin, wall along +x, leaf along +y) and unit window
    if "LEVANTA_DOOR" not in doc.blocks:
        blk = doc.blocks.new("LEVANTA_DOOR")
        blk.add_line((0, 0), (0, 1), dxfattribs={"layer": "A-DOOR"})
        blk.add_arc(center=(0, 0), radius=1.0, start_angle=0, end_angle=90, dxfattribs={"layer": "A-DOOR"})
    if "LEVANTA_WINDOW" not in doc.blocks:
        blk = doc.blocks.new("LEVANTA_WINDOW")
        for yy in (-0.3, 0.0, 0.3):
            blk.add_line((0, yy), (1, yy), dxfattribs={"layer": "A-GLAZ"})
        blk.add_line((0, -0.5), (0, 0.5), dxfattribs={"layer": "A-GLAZ"})
        blk.add_line((1, -0.5), (1, 0.5), dxfattribs={"layer": "A-GLAZ"})

    # walls
    for poly in wall_body_polygons(plan):
        ext = [S(p) for p in poly.exterior.coords]
        msp.add_lwpolyline(ext, close=True, dxfattribs={"layer": "A-WALL"})
        hatch = msp.add_hatch(color=LAYERS["A-WALL-PATT"][0], dxfattribs={"layer": "A-WALL-PATT"})
        hatch.paths.add_polyline_path(ext, is_closed=True)
        for ring in poly.interiors:
            pts = [S(p) for p in ring.coords]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-WALL"})
            hatch.paths.add_polyline_path(pts, is_closed=True)
        hatch.set_pattern_fill("ANSI31", scale=0.01 * k)

    # rooms
    from levanta.io.plan2d import open_edges

    for r in plan.rooms:
        msp.add_lwpolyline([S(p) for p in r.polygon], close=True, dxfattribs={"layer": "A-AREA"})
        for h in r.holes:
            msp.add_lwpolyline([S(p) for p in h], close=True, dxfattribs={"layer": "A-AREA"})
        cx, cy = r.centroid
        label = r.name if r.closed else f"{r.name} ({t(lang, 'incomplete')})"
        bx0, by0, bx1, by1 = r.shapely.bounds
        msp.add_mtext(f"{label}\n{r.area:.2f} m2\n{bx1 - bx0:.2f} x {by1 - by0:.2f} m", dxfattribs={"layer": "A-ANNO-TEXT", "char_height": 0.15 * k, "insert": S((cx, cy)), "attachment_point": 5})
    for a, b in open_edges(plan):
        msp.add_line(S(a), S(b), dxfattribs={"layer": "A-AREA-OPEN"})

    # openings as blocks + tags
    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a = w.point_at(o.t0)
        b = w.point_at(o.t1)
        n = w.normal
        ang = float(np.degrees(np.arctan2(w.direction[1], w.direction[0])))
        if o.kind == "door":
            side = swing_side(plan, w, o)
            msp.add_blockref("LEVANTA_DOOR", S(a), dxfattribs={"layer": "A-DOOR", "xscale": o.width * k, "yscale": o.width * k * side, "rotation": ang})
            tag_pt = (a + b) / 2 + n * side * (o.width * 0.75)
        elif o.kind == "window":
            msp.add_blockref("LEVANTA_WINDOW", S(a), dxfattribs={"layer": "A-GLAZ", "xscale": o.width * k, "yscale": w.thickness * k, "rotation": ang})
            plus, _ = wall_sides(plan, w)
            tag_pt = (a + b) / 2 + n * (1.0 if plus else -1.0) * (w.thickness / 2 + 0.22)
        else:
            msp.add_line(S(a), S(b), dxfattribs={"layer": "A-OPEN"})
            plus, _minus = wall_sides(plan, w)
            tag_pt = (a + b) / 2 + n * (1.0 if plus else -1.0) * (w.thickness / 2 + 0.22)
        if o.tag:
            msp.add_text(o.tag, dxfattribs={"layer": "A-ANNO-TEXT", "height": 0.12 * k}).set_placement(S(tag_pt), align=TextEntityAlignment.MIDDLE_CENTER)

    # dimensions: chains on perimeter walls + overall
    if show_dimensions and plan.walls:
        for ch in dimension_chains(plan):
            w = ch["wall"]
            n = w.normal * ch["side"]
            off = (w.thickness / 2 + 0.5) * k
            st = ch["stations"]
            for s0, s1 in itertools.pairwise(st):
                if s1 - s0 < 0.1:
                    continue
                p1, p2 = w.point_at(s0), w.point_at(s1)
                msp.add_aligned_dim(p1=S(p1), p2=S(p2), distance=off if float(w.direction[0] * n[1] - w.direction[1] * n[0]) > 0 else -off, dimstyle="LEVANTA", dxfattribs={"layer": "A-ANNO-DIMS"}).render()
        xmin, ymin, xmax, ymax = plan.bounds
        msp.add_aligned_dim(p1=S((xmin, ymin)), p2=S((xmax, ymin)), distance=-1.05 * k, dimstyle="LEVANTA", dxfattribs={"layer": "A-ANNO-DIMS"}).render()
        msp.add_aligned_dim(p1=S((xmin, ymax)), p2=S((xmin, ymin)), distance=-1.05 * k, dimstyle="LEVANTA", dxfattribs={"layer": "A-ANNO-DIMS"}).render()

    # reference axes
    letters, numbers = reference_axes(plan)
    if letters or numbers:
        xmin, ymin, xmax, ymax = plan.bounds
        for lab, x in letters:
            msp.add_line(S((x, ymin - 0.2)), S((x, ymax + 0.55)), dxfattribs={"layer": "A-GRID"})
            msp.add_circle(S((x, ymax + 0.75)), radius=0.18 * k, dxfattribs={"layer": "A-GRID"})
            msp.add_text(lab, dxfattribs={"layer": "A-GRID", "height": 0.16 * k}).set_placement(S((x, ymax + 0.75)), align=TextEntityAlignment.MIDDLE_CENTER)
        for lab, y in numbers:
            msp.add_line(S((xmin - 0.2, y)), S((xmax + 0.55, y)), dxfattribs={"layer": "A-GRID"})
            msp.add_circle(S((xmax + 0.75, y)), radius=0.18 * k, dxfattribs={"layer": "A-GRID"})
            msp.add_text(lab, dxfattribs={"layer": "A-GRID", "height": 0.16 * k}).set_placement(S((xmax + 0.75, y)), align=TextEntityAlignment.MIDDLE_CENTER)

    # north arrow
    if plan.north_deg is not None:
        xmin, ymin, xmax, ymax = plan.bounds
        c = np.array([xmin + 0.3, ymax + 1.2])
        ang = np.deg2rad(plan.north_deg)
        u = np.array([np.sin(ang), np.cos(ang)])
        msp.add_circle(S(c), radius=0.25 * k, dxfattribs={"layer": "A-ANNO-NORTH"})
        msp.add_line(S(c - u * 0.2), S(c + u * 0.24), dxfattribs={"layer": "A-ANNO-NORTH"})
        msp.add_text("N", dxfattribs={"layer": "A-ANNO-NORTH", "height": 0.15 * k}).set_placement(S(c + u * 0.42), align=TextEntityAlignment.MIDDLE_CENTER)

    # schedules and title block, to the right of the plan
    xmin, ymin, xmax, ymax = plan.bounds
    tx, ty = xmax + 1.6, ymax
    ty = _dxf_table(msp, S, tx, ty, k, t(lang, "areas_table"), [t(lang, "name"), t(lang, "area"), t(lang, "perimeter")], [[r.name + ("" if r.closed else " *"), f"{r.area:.2f} m2", f"{r.perimeter:.2f} m"] for r in plan.rooms] + _summary_rows(plan, lang), [1.6, 1.0, 1.0])
    if plan.openings:
        ty = _dxf_table(msp, S, tx, ty - 0.3, k, t(lang, "schedule"), [t(lang, "tag"), t(lang, "kind"), t(lang, "width"), "H", t(lang, "sill"), t(lang, "wall")], [[o.tag or "-", t(lang, o.kind), f"{o.width:.2f}", f"{o.z1 - o.z0:.2f}", f"{o.z0:.2f}" if o.kind == "window" else "-", str(o.wall_id + 1)] for o in sorted(plan.openings, key=lambda o: (o.kind, o.tag))], [0.5, 0.9, 0.7, 0.6, 0.7, 0.5])
    _dxf_title_block(msp, S, k, xmin, ymin - 1.6, max(xmax - xmin, 6.0), plan, title, lang)

    doc.saveas(path)
    return path


def _summary_rows(plan: FloorPlan, lang: str) -> list[list[str]]:
    s = plan.area_summary()
    return [
        [t(lang, "useful_area"), f"{s['useful_m2']:.2f} m2", ""],
        [t(lang, "walls_area"), f"{s['walls_m2']:.2f} m2", f"{s['wall_length_m']:.2f} m"],
        [t(lang, "gross_area"), f"{s['gross_m2']:.2f} m2", ""],
    ]


def _dxf_table(msp, S, x: float, y: float, k: float, title: str, headers: list[str], rows: list[list[str]], widths: list[float]) -> float:
    from ezdxf.enums import TextEntityAlignment

    rh = 0.28
    msp.add_text(title, dxfattribs={"layer": "A-ANNO-TABL", "height": 0.16 * k}).set_placement(S((x, y)), align=TextEntityAlignment.BOTTOM_LEFT)
    y -= 0.1
    total_w = sum(widths)
    cols = np.cumsum([0.0, *widths])
    for row_i, row in enumerate([headers, *rows]):
        y0 = y - rh
        msp.add_lwpolyline([S((x, y)), S((x + total_w, y)), S((x + total_w, y0)), S((x, y0))], close=True, dxfattribs={"layer": "A-ANNO-TABL"})
        for j, cell in enumerate(row):
            msp.add_text(cell, dxfattribs={"layer": "A-ANNO-TABL", "height": (0.11 if row_i else 0.12) * k}).set_placement(S((x + cols[j] + 0.06, y0 + 0.08)), align=TextEntityAlignment.BOTTOM_LEFT)
        for c in cols[1:-1]:
            msp.add_line(S((x + c, y)), S((x + c, y0)), dxfattribs={"layer": "A-ANNO-TABL"})
        y = y0
    return y


def _dxf_title_block(msp, S, k: float, x: float, y: float, w: float, plan: FloorPlan, title: str | None, lang: str) -> None:
    from ezdxf.enums import TextEntityAlignment

    h = 1.2
    pr = plan.project
    msp.add_lwpolyline([S((x, y)), S((x + w, y)), S((x + w, y - h)), S((x, y - h))], close=True, dxfattribs={"layer": "A-ANNO-TTLB"})
    cols = [0.0, 0.4, 0.6, 0.75, 0.88, 1.0]
    for c in cols[1:-1]:
        msp.add_line(S((x + c * w, y)), S((x + c * w, y - h)), dxfattribs={"layer": "A-ANNO-TTLB"})
    cells = [
        (0, t(lang, "project"), pr.get("name") or (title or t(lang, "floor_plan"))),
        (1, t(lang, "author"), pr.get("author") or "-"),
        (2, t(lang, "scale"), "1:1 (model)"),
        (3, t(lang, "date"), pr.get("date") or _dt.date.today().isoformat()),
        (4, t(lang, "sheet"), pr.get("sheet") or "A-01"),
    ]
    for i, lab, val in cells:
        cx = x + cols[i] * w + 0.08
        msp.add_text(lab.upper(), dxfattribs={"layer": "A-ANNO-TTLB", "height": 0.09 * k}).set_placement(S((cx, y - 0.22)), align=TextEntityAlignment.BOTTOM_LEFT)
        msp.add_text(val, dxfattribs={"layer": "A-ANNO-TTLB", "height": 0.16 * k}).set_placement(S((cx, y - 0.6)), align=TextEntityAlignment.BOTTOM_LEFT)
    foot = f"{t(lang, 'plan_title')}: {title or t(lang, 'floor_plan')} · {len(plan.rooms)} {t(lang, 'rooms')} · {plan.total_area:.2f} m2 · {t(lang, 'ceiling')} {plan.ceiling_height:.2f} m · {t(lang, 'generated_by')}"
    msp.add_text(foot, dxfattribs={"layer": "A-ANNO-TTLB", "height": 0.1 * k}).set_placement(S((x + 0.08, y - h + 0.12)), align=TextEntityAlignment.BOTTOM_LEFT)


def export_dxf_3d(plan: FloorPlan, path: str | Path, dxf_units: str = "m", include_ceiling: bool = False) -> Path:
    """DXF with the model as 3DFACE meshes on layers by element (walls, doors, glazing, floors)."""
    import ezdxf

    k, insunits = DXF_UNITS.get(dxf_units, DXF_UNITS["m"])
    path = Path(path)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    for name, color in (("A-WALL-3D", 7), ("A-DOOR-3D", 30), ("A-GLAZ-3D", 5), ("A-FLOR-3D", 3), ("A-CLNG-3D", 8)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    layer_of = {(226, 222, 214): "A-WALL-3D", (150, 110, 70): "A-DOOR-3D", (170, 205, 235): "A-GLAZ-3D", (196, 176, 150): "A-FLOR-3D", (240, 240, 240): "A-CLNG-3D"}
    for pts, base, holes in model_faces(plan, include_ceiling=include_ceiling):
        layer = layer_of.get(tuple(base), "A-WALL-3D")
        if len(pts) == 4 and not holes:
            msp.add_3dface([tuple(float(v) * k for v in p) for p in pts], dxfattribs={"layer": layer})
        elif len(pts) == 3:
            msp.add_3dface([tuple(float(v) * k for v in p) for p in pts] + [tuple(float(v) * k for v in pts[2])], dxfattribs={"layer": layer})
        else:
            import trimesh
            from shapely.geometry import Polygon

            poly = Polygon([(p[0], p[1]) for p in pts], [[(p[0], p[1]) for p in h] for h in holes])
            z = float(pts[0][2])
            try:
                v, f = trimesh.creation.triangulate_polygon(poly)
            except Exception:
                continue
            for tri in f:
                msp.add_3dface([(float(v[i][0]) * k, float(v[i][1]) * k, z * k) for i in tri] + [(float(v[tri[2]][0]) * k, float(v[tri[2]][1]) * k, z * k)], dxfattribs={"layer": layer})
    doc.saveas(path)
    return path


# ----------------------------------------------------------------------------------------
# 3D + JSON + HTML
# ----------------------------------------------------------------------------------------


def export_glb(plan: FloorPlan, path: str | Path, include_ceiling: bool = False) -> Path:
    path = Path(path)
    floor_plan_to_scene(plan, include_ceiling=include_ceiling).export(str(path))
    return path


def export_obj(plan: FloorPlan, path: str | Path, include_ceiling: bool = False) -> Path:
    path = Path(path)
    floor_plan_to_scene(plan, include_ceiling=include_ceiling).export(str(path))
    return path


def export_json(plan: FloorPlan, path: str | Path) -> Path:
    path = Path(path)
    plan.to_json(path)
    return path


def export_html(plan: FloorPlan, path: str | Path, title: str | None = None, lang: str = "en", units: str = "m", include_ceiling: bool = False, glb_path: str | Path | None = None) -> Path:
    """One HTML file: plan sheet, interactive 3D, elevations, measurements, checks."""
    from levanta.io.draw import render_svg
    from levanta.io.html import write_html

    d2 = floor_plan_drawing(plan, title=title, lang=lang, units=units)
    svg_2d = render_svg(d2, standalone=False)
    svg_iso = render_svg(isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling), standalone=False)
    svg_elev = render_svg(elevations_drawing(plan, lang=lang, units=units), standalone=False) if plan.walls else ""
    if glb_path is not None and Path(glb_path).exists():
        glb = Path(glb_path).read_bytes()
    else:
        glb = floor_plan_to_scene(plan, include_ceiling=include_ceiling).export(file_type="glb")
    return write_html(path, plan, svg_2d, svg_iso, glb, lang=lang, units=units, title=title, svg_elev=svg_elev, px_per_m=80.0)


def export_all(
    plan: FloorPlan,
    out_dir: str | Path,
    stem: str = "plan",
    title: str | None = None,
    include_ceiling: bool = False,
    lang: str = "en",
    units: str = "m",
    paper: str = "A4",
    dxf_units: str = "m",
    formats: tuple[str, ...] = ("html", "pdf", "png", "svg", "iso_png", "elev_png", "dxf", "dxf3d", "glb", "obj", "json"),
) -> dict[str, Path]:
    """Write every output.  Returns ``{format: path}``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if "glb" in formats:
        paths["glb"] = export_glb(plan, out_dir / f"{stem}.glb", include_ceiling=include_ceiling)
    if "obj" in formats:
        paths["obj"] = export_obj(plan, out_dir / f"{stem}.obj", include_ceiling=include_ceiling)
    if "svg" in formats:
        paths["svg"] = export_svg(plan, out_dir / f"{stem}.svg", title=title, lang=lang, units=units)
    if "png" in formats:
        paths["png"] = export_png(plan, out_dir / f"{stem}.png", title=title, lang=lang, units=units)
    if "pdf" in formats:
        paths["pdf"] = export_pdf(plan, out_dir / f"{stem}.pdf", paper=paper, title=title, lang=lang, units=units)
    if "iso_svg" in formats:
        paths["iso_svg"] = export_iso_svg(plan, out_dir / f"{stem}_3d.svg", lang=lang, include_ceiling=include_ceiling)
    if "iso_png" in formats:
        paths["iso_png"] = export_iso_png(plan, out_dir / f"{stem}_3d.png", lang=lang, include_ceiling=include_ceiling)
    if "elev_png" in formats and plan.walls:
        paths["elev_png"] = export_elevations_png(plan, out_dir / f"{stem}_elevations.png", lang=lang, units=units)
    if "dxf" in formats:
        paths["dxf"] = export_dxf(plan, out_dir / f"{stem}.dxf", lang=lang, dxf_units=dxf_units, title=title)
    if "dxf3d" in formats:
        paths["dxf3d"] = export_dxf_3d(plan, out_dir / f"{stem}_3d.dxf", dxf_units=dxf_units, include_ceiling=include_ceiling)
    if "json" in formats:
        paths["json"] = export_json(plan, out_dir / f"{stem}.json")
    if "html" in formats:
        paths["html"] = export_html(plan, out_dir / f"{stem}.html", title=title, lang=lang, units=units, include_ceiling=include_ceiling, glb_path=paths.get("glb"))
    return paths


def describe_units(units: str) -> str:
    return fmt_len(1.0, units) + " / " + fmt_area(1.0, units)
