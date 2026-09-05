"""Writers: SVG (presentation plan), DXF (CAD), GLB/OBJ (3D), JSON (data)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from levanta.plan.model import floor_plan_to_scene
from levanta.plan.types import FloorPlan, Opening, Wall

# ----------------------------------------------------------------------------------------
# helpers shared by SVG and DXF
# ----------------------------------------------------------------------------------------


def _opening_rect(wall: Wall, o: Opening, extra: float = 0.0) -> Polygon:
    a = wall.point_at(o.t0)
    b = wall.point_at(o.t1)
    return LineString([a, b]).buffer(wall.thickness / 2 + extra, cap_style="flat", join_style="mitre")


def wall_body_polygons(plan: FloorPlan) -> list[Polygon]:
    """Wall rectangles with every opening cut out (what you see from above)."""
    out: list[Polygon] = []
    for w in plan.walls:
        body = w.polygon()
        cuts = [_opening_rect(w, o, extra=0.002) for o in plan.openings_of(w.id)]
        if cuts:
            body = body.difference(unary_union(cuts))
        if body.is_empty:
            continue
        out.extend(list(body.geoms) if hasattr(body, "geoms") else [body])
    return out


def _swing_side(plan: FloorPlan, wall: Wall, o: Opening) -> float:
    """+1 / -1: on which side of the wall (along its normal) the door opens."""
    mid = wall.point_at((o.t0 + o.t1) / 2)
    n = wall.normal
    probe = mid + n * (wall.thickness / 2 + 0.3)
    from shapely.geometry import Point

    for r in plan.rooms:
        if r.shapely.contains(Point(probe)):
            return 1.0
    return -1.0


# ----------------------------------------------------------------------------------------
# SVG
# ----------------------------------------------------------------------------------------


def export_svg(
    plan: FloorPlan,
    path: str | Path,
    scale: float = 80.0,
    margin: float = 90.0,
    title: str | None = None,
    show_dimensions: bool = True,
    show_labels: bool = True,
) -> Path:
    """Architectural-style 2D plan.  ``scale`` is pixels per metre."""
    path = Path(path)
    xmin, ymin, xmax, ymax = plan.bounds
    if xmax - xmin < 1e-6:
        xmin, xmax = xmin - 1, xmax + 1
    if ymax - ymin < 1e-6:
        ymin, ymax = ymin - 1, ymax + 1
    W = (xmax - xmin) * scale + 2 * margin
    H = (ymax - ymin) * scale + 2 * margin + 40

    def X(x: float) -> float:
        return margin + (x - xmin) * scale

    def Y(y: float) -> float:
        return margin + (ymax - y) * scale

    def pts(coords) -> str:
        return " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in coords)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
        'font-family="Inter, Helvetica, Arial, sans-serif">'
    )
    parts.append(
        "<style>"
        ".room{fill:#f6f2ea;stroke:none}"
        ".wall{fill:#2b2b2b;stroke:none}"
        ".door{stroke:#8a5a2b;stroke-width:1.4;fill:none}"
        ".win{stroke:#2b6cb0;stroke-width:1.2;fill:none}"
        ".pass{stroke:#2b2b2b;stroke-width:1;fill:none;stroke-dasharray:4 4}"
        ".lbl{fill:#222;font-size:13px;font-weight:600}"
        ".sub{fill:#555;font-size:11px}"
        ".dim{stroke:#777;stroke-width:0.8;fill:none}"
        ".dimt{fill:#444;font-size:11px}"
        ".ttl{fill:#111;font-size:14px;font-weight:700}"
        ".meta{fill:#666;font-size:10.5px}"
        "</style>"
    )
    parts.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>')

    # rooms
    parts.append('<g id="rooms">')
    for r in plan.rooms:
        d = "M " + pts(r.polygon) + " Z"
        for h in r.holes:
            d += " M " + pts(h) + " Z"
        parts.append(f'<path class="room" fill-rule="evenodd" d="{d}"/>')
    parts.append("</g>")

    # walls (openings cut)
    parts.append('<g id="walls">')
    for poly in wall_body_polygons(plan):
        d = "M " + pts(list(poly.exterior.coords)) + " Z"
        for ring in poly.interiors:
            d += " M " + pts(list(ring.coords)) + " Z"
        parts.append(f'<path class="wall" fill-rule="evenodd" d="{d}"/>')
    parts.append("</g>")

    # openings
    parts.append('<g id="openings">')
    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a = w.point_at(o.t0)
        b = w.point_at(o.t1)
        n = w.normal
        if o.kind == "door":
            side = _swing_side(plan, w, o)
            hinge = a
            tip = hinge + n * side * o.width
            parts.append(f'<line class="door" x1="{X(hinge[0]):.1f}" y1="{Y(hinge[1]):.1f}" x2="{X(tip[0]):.1f}" y2="{Y(tip[1]):.1f}"/>')
            # quarter arc from the leaf tip to the far jamb
            r = o.width * scale
            sweep = 1 if side * (1 if w.direction[0] * n[1] - w.direction[1] * n[0] > 0 else -1) > 0 else 0
            parts.append(
                f'<path class="door" d="M {X(tip[0]):.1f} {Y(tip[1]):.1f} A {r:.1f} {r:.1f} 0 0 {sweep} {X(b[0]):.1f} {Y(b[1]):.1f}"/>'
            )
        elif o.kind == "window":
            for k in (-0.5, 0.0, 0.5):
                off = n * k * w.thickness * 0.6
                p, q = a + off, b + off
                parts.append(f'<line class="win" x1="{X(p[0]):.1f}" y1="{Y(p[1]):.1f}" x2="{X(q[0]):.1f}" y2="{Y(q[1]):.1f}"/>')
        else:
            parts.append(f'<line class="pass" x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(b[0]):.1f}" y2="{Y(b[1]):.1f}"/>')
    parts.append("</g>")

    # labels
    if show_labels:
        parts.append('<g id="labels">')
        for r in plan.rooms:
            cx, cy = r.centroid
            bx0, by0, bx1, by1 = r.shapely.bounds
            parts.append(f'<text class="lbl" x="{X(cx):.1f}" y="{Y(cy) - 4:.1f}" text-anchor="middle">{_esc(r.name)}</text>')
            parts.append(
                f'<text class="sub" x="{X(cx):.1f}" y="{Y(cy) + 11:.1f}" text-anchor="middle">'
                f"{r.area:.2f} m² · {bx1 - bx0:.2f} × {by1 - by0:.2f} m</text>"
            )
        parts.append("</g>")

    # overall dimensions
    if show_dimensions:
        parts.append('<g id="dimensions">')
        off = 28
        yb = Y(ymin) + off
        parts.append(f'<line class="dim" x1="{X(xmin):.1f}" y1="{Y(ymin) + 6:.1f}" x2="{X(xmin):.1f}" y2="{yb + 5:.1f}"/>')
        parts.append(f'<line class="dim" x1="{X(xmax):.1f}" y1="{Y(ymin) + 6:.1f}" x2="{X(xmax):.1f}" y2="{yb + 5:.1f}"/>')
        parts.append(f'<line class="dim" x1="{X(xmin):.1f}" y1="{yb:.1f}" x2="{X(xmax):.1f}" y2="{yb:.1f}"/>')
        parts.append(_tick(X(xmin), yb) + _tick(X(xmax), yb))
        parts.append(f'<text class="dimt" x="{(X(xmin) + X(xmax)) / 2:.1f}" y="{yb - 4:.1f}" text-anchor="middle">{xmax - xmin:.2f} m</text>')
        xl = X(xmin) - off
        parts.append(f'<line class="dim" x1="{X(xmin) - 6:.1f}" y1="{Y(ymin):.1f}" x2="{xl - 5:.1f}" y2="{Y(ymin):.1f}"/>')
        parts.append(f'<line class="dim" x1="{X(xmin) - 6:.1f}" y1="{Y(ymax):.1f}" x2="{xl - 5:.1f}" y2="{Y(ymax):.1f}"/>')
        parts.append(f'<line class="dim" x1="{xl:.1f}" y1="{Y(ymin):.1f}" x2="{xl:.1f}" y2="{Y(ymax):.1f}"/>')
        parts.append(_tick(xl, Y(ymin)) + _tick(xl, Y(ymax)))
        ym = (Y(ymin) + Y(ymax)) / 2
        parts.append(f'<text class="dimt" x="{xl - 4:.1f}" y="{ym:.1f}" text-anchor="middle" transform="rotate(-90 {xl - 4:.1f} {ym:.1f})">{ymax - ymin:.2f} m</text>')
        parts.append("</g>")

    # title block + scale bar
    ttl = title or "Floor plan"
    stamp = _dt.date.today().isoformat()
    ceil = f"ceiling {plan.ceiling_height:.2f} m ({'measured' if plan.ceiling_measured else 'default'})"
    parts.append(f'<text class="ttl" x="{margin:.0f}" y="{H - 34:.0f}">{_esc(ttl)}</text>')
    parts.append(
        f'<text class="meta" x="{margin:.0f}" y="{H - 18:.0f}">levanta · {len(plan.rooms)} rooms · {plan.total_area:.2f} m² · {ceil} · {stamp}</text>'
    )
    sx = W - margin - scale
    sy = H - 26
    parts.append(f'<rect x="{sx:.1f}" y="{sy:.1f}" width="{scale / 2:.1f}" height="6" fill="#222"/>')
    parts.append(f'<rect x="{sx + scale / 2:.1f}" y="{sy:.1f}" width="{scale / 2:.1f}" height="6" fill="none" stroke="#222" stroke-width="0.8"/>')
    parts.append(f'<text class="meta" x="{sx:.1f}" y="{sy - 4:.1f}">0</text><text class="meta" x="{sx + scale:.1f}" y="{sy - 4:.1f}" text-anchor="end">1 m</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _tick(x: float, y: float) -> str:
    return f'<line class="dim" x1="{x - 3:.1f}" y1="{y + 3:.1f}" x2="{x + 3:.1f}" y2="{y - 3:.1f}"/>'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def export_dxf(plan: FloorPlan, path: str | Path, show_dimensions: bool = True) -> Path:
    """AutoCAD 2010 DXF in metres ($INSUNITS = 6) with one layer per element type."""
    import ezdxf

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
        msp.add_mtext(f"{r.name}\n{r.area:.2f} m2", dxfattribs={"layer": "TEXT", "char_height": 0.15, "insert": (cx, cy), "attachment_point": 5})

    for o in plan.openings:
        w = plan.wall_by_id(o.wall_id)
        a = w.point_at(o.t0)
        b = w.point_at(o.t1)
        n = w.normal
        if o.kind == "door":
            side = _swing_side(plan, w, o)
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
# 3D + JSON
# ----------------------------------------------------------------------------------------


def export_glb(plan: FloorPlan, path: str | Path, include_ceiling: bool = False) -> Path:
    path = Path(path)
    scene = floor_plan_to_scene(plan, include_ceiling=include_ceiling)
    scene.export(str(path))
    return path


def export_obj(plan: FloorPlan, path: str | Path, include_ceiling: bool = False) -> Path:
    path = Path(path)
    scene = floor_plan_to_scene(plan, include_ceiling=include_ceiling)
    scene.export(str(path))
    return path


def export_json(plan: FloorPlan, path: str | Path) -> Path:
    path = Path(path)
    plan.to_json(path)
    return path


def export_all(plan: FloorPlan, out_dir: str | Path, stem: str = "plan", title: str | None = None, include_ceiling: bool = False) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "svg": export_svg(plan, out_dir / f"{stem}.svg", title=title),
        "dxf": export_dxf(plan, out_dir / f"{stem}.dxf"),
        "glb": export_glb(plan, out_dir / f"{stem}.glb", include_ceiling=include_ceiling),
        "obj": export_obj(plan, out_dir / f"{stem}.obj", include_ceiling=include_ceiling),
        "json": export_json(plan, out_dir / f"{stem}.json"),
    }
