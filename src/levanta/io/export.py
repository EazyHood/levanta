"""Writers: SVG/PNG (presentation plan), HTML (viewer), DXF (CAD), GLB/OBJ (3D), JSON (data)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from levanta.io.iso import isometric_drawing
from levanta.io.plan2d import floor_plan_drawing, swing_side, wall_body_polygons
from levanta.plan.model import floor_plan_to_scene
from levanta.plan.types import FloorPlan

__all__ = [
    "export_all",
    "export_dxf",
    "export_glb",
    "export_html",
    "export_iso_png",
    "export_iso_svg",
    "export_json",
    "export_obj",
    "export_png",
    "export_svg",
    "wall_body_polygons",
]


# ----------------------------------------------------------------------------------------
# 2-D plan
# ----------------------------------------------------------------------------------------


def export_svg(plan: FloorPlan, path: str | Path, scale: float = 80.0, title: str | None = None, lang: str = "en", units: str = "m", **kw) -> Path:
    """Architectural-style 2D plan as SVG.  ``scale`` is pixels per metre."""
    return floor_plan_drawing(plan, scale=scale, title=title, lang=lang, units=units, **kw).save_svg(path)


def export_png(plan: FloorPlan, path: str | Path, scale: float = 80.0, title: str | None = None, lang: str = "en", units: str = "m", dpi_scale: float = 2.0, **kw) -> Path:
    """Same plan as a PNG (``dpi_scale`` times the SVG pixel size)."""
    return floor_plan_drawing(plan, scale=scale, title=title, lang=lang, units=units, **kw).save_png(path, scale=dpi_scale)


def export_iso_svg(plan: FloorPlan, path: str | Path, lang: str = "en", include_ceiling: bool = False, **kw) -> Path:
    return isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling, **kw).save_svg(path)


def export_iso_png(plan: FloorPlan, path: str | Path, lang: str = "en", include_ceiling: bool = False, dpi_scale: float = 2.0, **kw) -> Path:
    return isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling, **kw).save_png(path, scale=dpi_scale)


# ----------------------------------------------------------------------------------------
# DXF
# ----------------------------------------------------------------------------------------

LAYERS = {
    "WALLS": 7,
    "WALL-FILL": 8,
    "ROOMS": 3,
    "DOORS": 30,
    "WINDOWS": 5,
    "PASSAGES": 8,
    "TEXT": 7,
    "DIMENSIONS": 4,
}


def export_dxf(plan: FloorPlan, path: str | Path, show_dimensions: bool = True, lang: str = "en") -> Path:
    """AutoCAD 2010 DXF in metres ($INSUNITS = 6) with one layer per element type."""
    import ezdxf

    from levanta.i18n import t

    path = Path(path)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    doc.header["$LUNITS"] = 2
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    doc.dimstyles.new(
        "LEVANTA",
        dxfattribs={"dimtxt": 0.12, "dimasz": 0.08, "dimexe": 0.05, "dimexo": 0.05, "dimdec": 2, "dimtad": 1, "dimgap": 0.03, "dimtih": 0, "dimtoh": 0},
    )
    msp = doc.modelspace()

    for poly in wall_body_polygons(plan):
        ext = list(poly.exterior.coords)
        msp.add_lwpolyline(ext, close=True, dxfattribs={"layer": "WALLS"})
        hatch = msp.add_hatch(color=LAYERS["WALL-FILL"], dxfattribs={"layer": "WALL-FILL"})
        hatch.paths.add_polyline_path(ext, is_closed=True)
        for ring in poly.interiors:
            msp.add_lwpolyline(list(ring.coords), close=True, dxfattribs={"layer": "WALLS"})
            hatch.paths.add_polyline_path(list(ring.coords), is_closed=True)
        hatch.set_pattern_fill("ANSI31", scale=0.01)

    for r in plan.rooms:
        msp.add_lwpolyline(r.polygon, close=True, dxfattribs={"layer": "ROOMS"})
        for h in r.holes:
            msp.add_lwpolyline(h, close=True, dxfattribs={"layer": "ROOMS"})
        cx, cy = r.centroid
        label = r.name if r.closed else f"{r.name} ({t(lang, 'incomplete')})"
        msp.add_mtext(f"{label}\n{r.area:.2f} m2", dxfattribs={"layer": "TEXT", "char_height": 0.15, "insert": (cx, cy), "attachment_point": 5})

    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a = w.point_at(o.t0)
        b = w.point_at(o.t1)
        n = w.normal
        if o.kind == "door":
            side = swing_side(plan, w, o)
            tip = a + n * side * o.width
            msp.add_line(tuple(a), tuple(tip), dxfattribs={"layer": "DOORS"})
            ang_tip = np.degrees(np.arctan2(tip[1] - a[1], tip[0] - a[0]))
            ang_b = np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0]))
            start, end = (ang_b, ang_tip) if ((ang_tip - ang_b) % 360) <= 180 else (ang_tip, ang_b)
            msp.add_arc(center=tuple(a), radius=o.width, start_angle=start, end_angle=end, dxfattribs={"layer": "DOORS"})
        elif o.kind == "window":
            for k in (-0.5, 0.0, 0.5):
                off = n * k * w.thickness * 0.6
                msp.add_line(tuple(a + off), tuple(b + off), dxfattribs={"layer": "WINDOWS"})
        else:
            msp.add_line(tuple(a), tuple(b), dxfattribs={"layer": "PASSAGES", "linetype": "DASHED"})

    if show_dimensions and plan.walls:
        xmin, ymin, xmax, ymax = plan.bounds
        msp.add_aligned_dim(p1=(xmin, ymin), p2=(xmax, ymin), distance=-0.6, dimstyle="LEVANTA", dxfattribs={"layer": "DIMENSIONS"}).render()
        msp.add_aligned_dim(p1=(xmin, ymax), p2=(xmin, ymin), distance=-0.6, dimstyle="LEVANTA", dxfattribs={"layer": "DIMENSIONS"}).render()
        for r in plan.rooms:
            bx0, by0, bx1, by1 = r.shapely.bounds
            msp.add_aligned_dim(p1=(bx0, by1), p2=(bx1, by1), distance=-0.25, dimstyle="LEVANTA", dxfattribs={"layer": "DIMENSIONS"}).render()
            msp.add_aligned_dim(p1=(bx1, by0), p2=(bx1, by1), distance=-0.25, dimstyle="LEVANTA", dxfattribs={"layer": "DIMENSIONS"}).render()

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
    """One HTML file with the 2D plan, an interactive 3D view and a measurements table."""
    from levanta.io.draw import render_svg
    from levanta.io.html import write_html

    svg_2d = render_svg(floor_plan_drawing(plan, title=title, lang=lang, units=units), standalone=False)
    svg_iso = render_svg(isometric_drawing(plan, lang=lang, include_ceiling=include_ceiling), standalone=False)
    if glb_path is not None and Path(glb_path).exists():
        glb = Path(glb_path).read_bytes()
    else:
        glb = floor_plan_to_scene(plan, include_ceiling=include_ceiling).export(file_type="glb")
    return write_html(path, plan, svg_2d, svg_iso, glb, lang=lang, units=units, title=title)


def export_all(
    plan: FloorPlan,
    out_dir: str | Path,
    stem: str = "plan",
    title: str | None = None,
    include_ceiling: bool = False,
    lang: str = "en",
    units: str = "m",
    formats: tuple[str, ...] = ("html", "png", "svg", "iso_png", "dxf", "glb", "obj", "json"),
) -> dict[str, Path]:
    """Write every output.  Returns ``{format: path}``.  ``html`` embeds the GLB, so the
    GLB is written first when both are requested."""
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
    if "iso_svg" in formats:
        paths["iso_svg"] = export_iso_svg(plan, out_dir / f"{stem}_3d.svg", lang=lang, include_ceiling=include_ceiling)
    if "iso_png" in formats:
        paths["iso_png"] = export_iso_png(plan, out_dir / f"{stem}_3d.png", lang=lang, include_ceiling=include_ceiling)
    if "dxf" in formats:
        paths["dxf"] = export_dxf(plan, out_dir / f"{stem}.dxf", lang=lang)
    if "json" in formats:
        paths["json"] = export_json(plan, out_dir / f"{stem}.json")
    if "html" in formats:
        paths["html"] = export_html(plan, out_dir / f"{stem}.html", title=title, lang=lang, units=units, include_ceiling=include_ceiling, glb_path=paths.get("glb"))
    return paths
