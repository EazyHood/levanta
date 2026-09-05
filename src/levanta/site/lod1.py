"""Footprint + height -> LOD1 block model (GLB/OBJ), site plan (HTML/PNG/SVG/DXF) and JSON."""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

from levanta.i18n import fmt_area, fmt_len, t
from levanta.io.draw import Drawing, render_svg
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
    lang: str = "en",
    units: str = "m",
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
    d2 = site_plan_drawing(buildings, proj, only_target=only_target, level_height=level_height, lang=lang, units=units)
    paths["svg"] = d2.save_svg(out_dir / f"{stem}.svg")
    paths["png"] = d2.save_png(out_dir / f"{stem}.png")
    d3 = site_iso_drawing(buildings, proj, only_target=only_target, level_height=level_height, lang=lang)
    paths["iso_png"] = d3.save_png(out_dir / f"{stem}_3d.png")
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
    paths["html"] = site_html(out_dir / f"{stem}.html", buildings, proj, render_svg(d2, standalone=False), render_svg(d3, standalone=False), rows, lang=lang, units=units)
    return paths


# ----------------------------------------------------------------------------------------
# drawings
# ----------------------------------------------------------------------------------------


def site_plan_drawing(buildings: list[Building], proj: LocalProjection, only_target: bool = True, level_height: float = 3.0, lang: str = "en", units: str = "m", scale: float = 12.0, margin: float = 80.0) -> Drawing:
    polys = [b.polygon_local(proj) for b in buildings]
    shown = polys[:1] if only_target else polys
    xs = [c for p in shown for c in (p.bounds[0], p.bounds[2])] + [0.0]
    ys = [c for p in shown for c in (p.bounds[1], p.bounds[3])] + [0.0]
    xmin, xmax, ymin, ymax = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    W = (xmax - xmin) * scale + 2 * margin
    H = (ymax - ymin) * scale + 2 * margin + 30
    d = Drawing(W, H)

    def X(x: float) -> float:
        return margin + (x - xmin) * scale

    def Y(y: float) -> float:
        return margin + (ymax - y) * scale

    def P(pts):
        return [(X(x), Y(y)) for x, y in pts]

    if not only_target:
        for p in polys[1:]:
            d.polygon(P(p.exterior.coords), fill="#ececec", stroke="#999", width=1.0, cls="neighbour")
    if polys:
        p = polys[0]
        b = buildings[0]
        d.polygon(P(p.exterior.coords), fill="#d9c7a9", stroke="#5a4a33", width=1.5, holes=[P(r.coords) for r in p.interiors], cls="building")
        coords = list(p.exterior.coords)
        c = p.centroid
        lengths = [float(np.hypot(x1 - x0, y1 - y0)) for (x0, y0), (x1, y1) in pairwise(coords)]
        # label the long sides only; a traced outline can have a hundred tiny jogs
        min_label = 1.0 if len(lengths) <= 16 else max(2.5, float(np.sort(lengths)[-16]))
        for (x0, y0), (x1, y1) in pairwise(coords):
            L = float(np.hypot(x1 - x0, y1 - y0))
            if L < min_label:
                continue
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            nx, ny = -(y1 - y0) / L, (x1 - x0) / L
            if (mx - c.x) * nx + (my - c.y) * ny < 0:
                nx, ny = -nx, -ny
            d.text(X(mx + nx * 1.2), Y(my + ny * 1.2) + 4, fmt_len(L, units), size=11, color="#333", cls="edge")
        h, how = b.height(level_height=level_height)
        d.text(X(c.x), Y(c.y), b.name or t(lang, "building"), size=13, weight="bold", cls="label")
        d.text(X(c.x), Y(c.y) + 14, f"{fmt_area(p.area, units)} · {t(lang, 'height')} {fmt_len(h, units)} ({t(lang, how)})", size=10.5, color="#666", cls="label")
    d.circle(X(0), Y(0), 3.5, fill="#c0392b", cls="query")
    ax, ay = W - margin + 20, margin
    d.line((ax, ay + 40), (ax, ay), stroke="#777", width=0.8)
    d.polygon([(ax - 5, ay + 12), (ax, ay), (ax + 5, ay + 12)], fill="#333")
    d.text(ax, ay + 54, "N", size=10.5, color="#666")
    sx, sy = W - margin - 10 * scale, H - 26
    d.polygon([(sx, sy), (sx + 5 * scale, sy), (sx + 5 * scale, sy + 6), (sx, sy + 6)], fill="#222")
    d.polygon([(sx + 5 * scale, sy), (sx + 10 * scale, sy), (sx + 10 * scale, sy + 6), (sx + 5 * scale, sy + 6)], fill=None, stroke="#222", width=0.8)
    d.text(sx, sy - 4, "0", size=10.5, anchor="start", color="#666")
    d.text(sx + 10 * scale, sy - 4, "10 m" if units == "m" else "33'", size=10.5, anchor="end", color="#666")
    attr = buildings[0].attribution if buildings else ""
    d.text(margin, H - 18, f"{t(lang, 'site_plan')} · {t(lang, 'generated_by')} · {attr} · {buildings[0].license if buildings else ''} · {_dt.date.today().isoformat()}", size=10.5, anchor="start", color="#666")
    return d


def site_iso_drawing(buildings: list[Building], proj: LocalProjection, only_target: bool = True, level_height: float = 3.0, lang: str = "en", scale: float = 8.0, margin: float = 40.0) -> Drawing:
    """Axonometric view of the LOD1 blocks."""
    from levanta.io.iso import project

    chosen = buildings[:1] if only_target else buildings
    faces = []
    for i, b in enumerate(chosen):
        poly = b.polygon_local(proj)
        if poly.is_empty:
            continue
        h, _ = b.height(level_height=level_height)
        base = (214, 196, 168) if i == 0 else (225, 225, 225)
        ring = [np.array([x, y, 0.0]) for x, y in poly.exterior.coords[:-1]]
        top = [p + np.array([0, 0, h]) for p in ring]
        faces.append((np.array(top), base, [np.array([[x, y, h] for x, y in r.coords[:-1]]) for r in poly.interiors]))
        for a, c in zip(ring, ring[1:] + ring[:1], strict=False):
            up = np.array([0, 0, h])
            faces.append((np.array([a, c, c + up, a + up]), base, []))
    if not faces:
        return Drawing(300, 120)
    light = np.array([-0.4, -0.6, 1.0])
    light /= np.linalg.norm(light)
    items, all_pts = [], []
    for pts, base, holes in faces:
        sp, depth = project(pts)
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        nn = np.linalg.norm(n)
        n = n / nn if nn > 0 else np.array([0, 0, 1.0])
        shade = 0.62 + 0.38 * max(0.0, float(abs(n @ light)))
        col = tuple(int(min(255, c * shade)) for c in base)
        hp = [project(hh)[0] for hh in holes]
        items.append((float(depth.mean()), sp, hp, col))
        all_pts.append(sp)
        all_pts.extend(hp)
    allp = np.concatenate(all_pts)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    W = (hi[0] - lo[0]) * scale + 2 * margin
    H = (hi[1] - lo[1]) * scale + 2 * margin + 28
    d = Drawing(W, H)

    def S(p):
        return [(margin + (x - lo[0]) * scale, margin + (hi[1] - y) * scale) for x, y in p]

    for _depth, sp, hp, col in sorted(items, key=lambda it: -it[0]):
        hexc = "#" + "".join(f"{c:02x}" for c in col)
        edge = "#" + "".join(f"{int(c * 0.72):02x}" for c in col)
        d.polygon(S(sp), fill=hexc, stroke=edge, width=0.6, holes=[S(h) for h in hp])
    d.text(margin, H - 10, f"LOD1 · {t(lang, 'site_limits')}", size=10.5, anchor="start", color="#666")
    return d


def site_html(path: Path, buildings: list[Building], proj: LocalProjection, svg_2d: str, svg_iso: str, rows: list[dict], lang: str = "en", units: str = "m") -> Path:
    b = buildings[0]
    p = b.polygon_local(proj)
    h, how = b.height()
    title = b.name or t(lang, "building")
    table = "".join(
        f"<tr><td>{_html.escape(str(r.get('name') or r['id']))}</td><td class=num>{fmt_area(r.get('footprint_area_m2', 0.0), units)}</td><td class=num>{fmt_len(r['height_used_m'], units)}</td><td>{t(lang, r['height_source'])}</td><td>{_html.escape(r['source'])}</td></tr>"
        for r in rows
    )
    doc = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html.escape(title)} · levanta</title>
<style>body{{margin:0;background:#faf8f4;color:#1d1d1f;font-family:Inter,'Segoe UI',Helvetica,Arial,sans-serif;line-height:1.45}}header{{padding:28px 32px 12px}}h1{{margin:0 0 4px;font-size:24px}}.sum{{color:#6b6b6f;font-size:14px}}
main{{display:grid;grid-template-columns:1fr;gap:20px;padding:0 32px 40px;max-width:1400px}}@media(min-width:1100px){{main{{grid-template-columns:1fr 1fr}}.wide{{grid-column:1/-1}}}}
.card{{background:#fff;border:1px solid #e6e3dd;border-radius:14px;padding:18px 20px}}.card h2{{margin:0 0 10px;font-size:15px;font-weight:600;color:#6b6b6f;text-transform:uppercase;letter-spacing:.06em}}.card svg{{width:100%;height:auto;display:block}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #e6e3dd}}th{{color:#6b6b6f;font-size:12px;text-transform:uppercase}}td.num{{text-align:right}}.hint{{font-size:12px;color:#6b6b6f;margin-top:8px}}footer{{padding:10px 32px 30px;color:#6b6b6f;font-size:12px}}</style></head>
<body><header><h1>{_html.escape(title)}</h1><div class="sum">{t(lang, 'footprint')} {fmt_area(p.area, units)} · {t(lang, 'perimeter')} {fmt_len(p.length, units)} · {t(lang, 'height')} {fmt_len(h, units)} ({t(lang, how)}) · {t(lang, 'source')}: {_html.escape(b.attribution)} ({_html.escape(b.license)})</div></header>
<main><section class="card"><h2>{t(lang, 'site_plan')}</h2>{svg_2d}</section>
<section class="card"><h2>{t(lang, 'view_3d')} (LOD1)</h2>{svg_iso}<div class="hint">{t(lang, 'site_limits')}</div></section>
<section class="card wide"><h2>{t(lang, 'measurements')}</h2><table><thead><tr><th>{t(lang, 'name')}</th><th>{t(lang, 'footprint')}</th><th>{t(lang, 'height')}</th><th>{t(lang, 'source')} ({t(lang, 'height')})</th><th>{t(lang, 'source')}</th></tr></thead><tbody>{table}</tbody></table></section></main>
<footer>{t(lang, 'generated_by')} · MIT · github.com/EazyHood/levanta</footer></body></html>"""
    path.write_text(doc, encoding="utf-8")
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
