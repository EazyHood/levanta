"""Footprint + height -> LOD1 block model (GLB/OBJ), site plan (SVG/DXF) and JSON."""

from __future__ import annotations

import datetime as _dt
import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

from levanta.site.projection import LocalProjection
from levanta.site.sources import Building

TARGET_COLOR = (214, 196, 168, 255)
NEIGHBOUR_COLOR = (225, 225, 225, 255)
GROUND_COLOR = (200, 210, 190, 255)


def lod1_mesh(poly: Polygon, height: float) -> trimesh.Trimesh:
    """Prism over ``poly`` (metres) of the given height, base at z = 0."""
    if not poly.is_valid:
        poly = poly.buffer(0)
    return trimesh.creation.extrude_polygon(poly, height=height)


def site_scene(
    buildings: list[Building],
    proj: LocalProjection,
    only_target: bool = True,
    level_height: float = 3.0,
    ground_margin: float = 8.0,
) -> tuple[trimesh.Scene, list[dict]]:
    scene = trimesh.Scene()
    rows = []
    chosen = buildings[:1] if only_target else buildings
    for i, b in enumerate(chosen):
        poly = b.polygon_local(proj)
        if poly.is_empty:
            continue
        h, how = b.height(level_height=level_height)
        mesh = lod1_mesh(poly, h)
        mesh.visual.face_colors = TARGET_COLOR if i == 0 else NEIGHBOUR_COLOR
        scene.add_geometry(mesh, geom_name=f"building_{i}", node_name=f"building_{i}")
        rows.append({**b.describe(proj), "height_used_m": round(h, 2), "height_source": how})
    if rows:
        minx, miny, maxx, maxy = scene.bounds[0][0], scene.bounds[0][1], scene.bounds[1][0], scene.bounds[1][1]
        ground = trimesh.creation.box(
            extents=[maxx - minx + 2 * ground_margin, maxy - miny + 2 * ground_margin, 0.05],
            transform=trimesh.transformations.translation_matrix([(minx + maxx) / 2, (miny + maxy) / 2, -0.025]),
        )
        ground.visual.face_colors = GROUND_COLOR
        scene.add_geometry(ground, geom_name="ground", node_name="ground")
    return scene, rows


def export_site(
    buildings: list[Building],
    lat: float,
    lon: float,
    out_dir: str | Path,
    stem: str = "site",
    only_target: bool = True,
    level_height: float = 3.0,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    proj = LocalProjection(lat, lon)
    scene, rows = site_scene(buildings, proj, only_target=only_target, level_height=level_height)
    paths: dict[str, Path] = {}
    paths["glb"] = out_dir / f"{stem}.glb"
    scene.export(str(paths["glb"]))
    paths["obj"] = out_dir / f"{stem}.obj"
    scene.export(str(paths["obj"]))
    paths["svg"] = site_plan_svg(buildings, proj, out_dir / f"{stem}.svg", only_target=only_target, level_height=level_height)
    paths["dxf"] = site_plan_dxf(buildings, proj, out_dir / f"{stem}.dxf", only_target=only_target, level_height=level_height)
    paths["json"] = out_dir / f"{stem}.json"
    payload = {
        "query": {"lat": lat, "lon": lon},
        "origin": {"lat": lat, "lon": lon, "note": "local frame: x east, y north, metres, z up from ground"},
        "buildings": rows,
        "target_local_footprint": [[round(float(x), 3), round(float(y), 3)] for x, y in buildings[0].polygon_local(proj).exterior.coords[:-1]] if buildings else [],
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "limits": "LOD1: footprint x height only; no walls, roof geometry or interior can be derived from overhead data.",
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return paths


# ----------------------------------------------------------------------------------------
# site plan drawings
# ----------------------------------------------------------------------------------------


def site_plan_svg(buildings: list[Building], proj: LocalProjection, path: str | Path, only_target: bool = True, level_height: float = 3.0, scale: float = 12.0, margin: float = 80.0) -> Path:
    path = Path(path)
    polys = [b.polygon_local(proj) for b in buildings]
    shown = polys[:1] if only_target else polys
    xs = [c for p in shown for c in (p.bounds[0], p.bounds[2])] + [0.0]
    ys = [c for p in shown for c in (p.bounds[1], p.bounds[3])] + [0.0]
    xmin, xmax, ymin, ymax = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    W = (xmax - xmin) * scale + 2 * margin
    H = (ymax - ymin) * scale + 2 * margin + 30

    def X(x: float) -> float:
        return margin + (x - xmin) * scale

    def Y(y: float) -> float:
        return margin + (ymax - y) * scale

    s: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="Inter, Helvetica, Arial, sans-serif">',
        "<style>.tgt{fill:#d9c7a9;stroke:#5a4a33;stroke-width:1.5}.nb{fill:#ececec;stroke:#999;stroke-width:1}"
        ".edge{fill:#333;font-size:11px}.lbl{fill:#222;font-size:13px;font-weight:600}.meta{fill:#666;font-size:10.5px}"
        ".dim{stroke:#777;stroke-width:0.8;fill:none}.pt{fill:#c0392b}</style>",
        f'<rect width="{W:.0f}" height="{H:.0f}" fill="#fff"/>',
    ]
    if not only_target:
        for p in polys[1:]:
            s.append('<path class="nb" d="M ' + " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in p.exterior.coords) + ' Z"/>')
    if polys:
        p = polys[0]
        b = buildings[0]
        d = "M " + " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in p.exterior.coords) + " Z"
        for ring in p.interiors:
            d += " M " + " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in ring.coords) + " Z"
        s.append(f'<path class="tgt" fill-rule="evenodd" d="{d}"/>')
        # edge lengths, placed outside each edge
        coords = list(p.exterior.coords)
        c = p.centroid
        for (x0, y0), (x1, y1) in pairwise(coords):
            L = float(np.hypot(x1 - x0, y1 - y0))
            if L < 1.0:
                continue
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            nx, ny = -(y1 - y0) / L, (x1 - x0) / L
            if (mx - c.x) * nx + (my - c.y) * ny < 0:
                nx, ny = -nx, -ny
            tx, ty = mx + nx * 1.2, my + ny * 1.2
            s.append(f'<text class="edge" x="{X(tx):.1f}" y="{Y(ty) + 4:.1f}" text-anchor="middle">{L:.2f} m</text>')
        h, how = b.height(level_height=level_height)
        s.append(f'<text class="lbl" x="{X(c.x):.1f}" y="{Y(c.y):.1f}" text-anchor="middle">{_esc(b.name or "Building")}</text>')
        s.append(f'<text class="meta" x="{X(c.x):.1f}" y="{Y(c.y) + 14:.1f}" text-anchor="middle">{p.area:.1f} m² · h {h:.1f} m ({how})</text>')
    # query point + north arrow + scale + attribution
    s.append(f'<circle class="pt" cx="{X(0):.1f}" cy="{Y(0):.1f}" r="3.5"/>')
    ax, ay = W - margin + 20, margin
    s.append(f'<line class="dim" x1="{ax}" y1="{ay + 40}" x2="{ax}" y2="{ay}"/><polygon points="{ax - 5},{ay + 12} {ax},{ay} {ax + 5},{ay + 12}" fill="#333"/>')
    s.append(f'<text class="meta" x="{ax}" y="{ay + 54}" text-anchor="middle">N</text>')
    sx, sy = W - margin - 10 * scale, H - 26
    s.append(f'<rect x="{sx:.1f}" y="{sy:.1f}" width="{5 * scale:.1f}" height="6" fill="#222"/><rect x="{sx + 5 * scale:.1f}" y="{sy:.1f}" width="{5 * scale:.1f}" height="6" fill="none" stroke="#222" stroke-width="0.8"/>')
    s.append(f'<text class="meta" x="{sx:.1f}" y="{sy - 4:.1f}">0</text><text class="meta" x="{sx + 10 * scale:.1f}" y="{sy - 4:.1f}" text-anchor="end">10 m</text>')
    attr = buildings[0].attribution if buildings else ""
    s.append(f'<text class="meta" x="{margin:.0f}" y="{H - 18:.0f}">levanta site plan · {_esc(attr)} · {buildings[0].license if buildings else ""} · {_dt.date.today().isoformat()}</text>')
    s.append("</svg>")
    path.write_text("\n".join(s), encoding="utf-8")
    return path


def site_plan_dxf(buildings: list[Building], proj: LocalProjection, path: str | Path, only_target: bool = True, level_height: float = 3.0) -> Path:
    import ezdxf

    path = Path(path)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    doc.layers.add("BUILDING", color=7)
    doc.layers.add("NEIGHBOURS", color=8)
    doc.layers.add("TEXT", color=7)
    doc.layers.add("DIMENSIONS", color=4)
    doc.dimstyles.new("LEVANTA", dxfattribs={"dimtxt": 0.5, "dimasz": 0.3, "dimexe": 0.2, "dimexo": 0.2, "dimdec": 2, "dimtad": 1, "dimgap": 0.1})
    msp = doc.modelspace()
    chosen = buildings[:1] if only_target else buildings
    for i, b in enumerate(chosen):
        p = b.polygon_local(proj)
        layer = "BUILDING" if i == 0 else "NEIGHBOURS"
        msp.add_lwpolyline(list(p.exterior.coords), close=True, dxfattribs={"layer": layer})
        for ring in p.interiors:
            msp.add_lwpolyline(list(ring.coords), close=True, dxfattribs={"layer": layer})
        if i == 0:
            h, how = b.height(level_height=level_height)
            c = p.centroid
            msp.add_mtext(f"{b.name or 'Building'}\n{p.area:.1f} m2\nh = {h:.1f} m ({how})", dxfattribs={"layer": "TEXT", "char_height": 0.6, "insert": (c.x, c.y), "attachment_point": 5})
            coords = list(p.exterior.coords)
            for (x0, y0), (x1, y1) in pairwise(coords):
                if np.hypot(x1 - x0, y1 - y0) >= 1.0:
                    msp.add_aligned_dim(p1=(x0, y0), p2=(x1, y1), distance=1.0, dimstyle="LEVANTA", dxfattribs={"layer": "DIMENSIONS"}).render()
    msp.add_point((0.0, 0.0), dxfattribs={"layer": "TEXT"})
    doc.saveas(path)
    return path


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
