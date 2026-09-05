"""Footprint + height -> LOD1 block model (GLB/OBJ), site plan (HTML/PNG/SVG/PDF/DXF) and JSON.

The site plan carries what a civil drafter expects of a lot: numbered vertices with a
coordinate table (local metres, WGS84, UTM with zone and EPSG), a boundary table with
azimuth and length per side, area in m² and ha, perimeter and the closure of the
traverse.
"""

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
from levanta.site.projection import LocalProjection, azimuth_deg, dms, utm_from_latlon
from levanta.site.sources import Building

TARGET_COLOR = (214, 196, 168, 255)
NEIGHBOUR_COLOR = (225, 225, 225, 255)
GROUND_COLOR = (200, 210, 190, 255)


def lod1_mesh(poly: Polygon, height: float) -> trimesh.Trimesh:
    """Prism over ``poly`` (metres) of the given height, base at z = 0."""
    if not poly.is_valid:
        poly = poly.buffer(0)
    return trimesh.creation.extrude_polygon(poly, height=height)


# ----------------------------------------------------------------------------------------
# survey-style tables
# ----------------------------------------------------------------------------------------


def lot_survey(b: Building, proj: LocalProjection) -> dict:
    """Vertices, sides, area and closure of the building footprint, as a surveyor lists them."""
    poly = b.polygon_local(proj)
    ring = list(poly.exterior.coords)[:-1]
    # counter-clockwise, starting at the north-western-most vertex
    if Polygon(ring).exterior.is_ccw is False:
        ring = ring[::-1]
    start = int(np.argmin([x - y for x, y in ring]))
    ring = ring[start:] + ring[:start]
    vertices = []
    for i, (x, y) in enumerate(ring):
        lon, lat = proj.to_wgs84(x, y)
        u = utm_from_latlon(float(lat), float(lon))
        vertices.append({"id": i + 1, "x": float(x), "y": float(y), "lat": float(lat), "lon": float(lon), "utm_e": u["easting"], "utm_n": u["northing"]})
    u0 = utm_from_latlon(proj.lat0, proj.lon0)
    sides = []
    for (i, a), (_, c) in pairwise([*list(enumerate(ring)), (0, ring[0])]):
        dx, dy = c[0] - a[0], c[1] - a[1]
        length = float(np.hypot(dx, dy))
        sides.append({"from": i + 1, "to": (i + 1) % len(ring) + 1, "length_m": length, "azimuth_deg": azimuth_deg(dx, dy)})
    closure = float(np.hypot(sum(s["length_m"] * np.sin(np.deg2rad(s["azimuth_deg"])) for s in sides), sum(s["length_m"] * np.cos(np.deg2rad(s["azimuth_deg"])) for s in sides)))
    return {
        "vertices": vertices,
        "sides": sides,
        "area_m2": float(poly.area),
        "area_ha": float(poly.area) / 10_000.0,
        "perimeter_m": float(poly.length),
        "closure_m": closure,
        "utm": {"zone": u0["zone"], "band": u0["band"], "hemisphere": u0["hemisphere"], "epsg": u0["epsg"]},
        "origin": {"lat": proj.lat0, "lon": proj.lon0, "utm_e": u0["easting"], "utm_n": u0["northing"]},
    }


def site_scene(buildings: list[Building], proj: LocalProjection, only_target: bool = True, level_height: float = 3.0, ground_margin: float = 8.0) -> tuple[trimesh.Scene, list[dict]]:
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


def export_site(buildings: list[Building], lat: float, lon: float, out_dir: str | Path, stem: str = "site", only_target: bool = True, level_height: float = 3.0, lang: str = "en", units: str = "m", paper: str = "A4") -> dict[str, Path]:
    from levanta.io.pdf import PT_PER_MM, page_size_pt, write_pdf

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    proj = LocalProjection(lat, lon)
    scene, rows = site_scene(buildings, proj, only_target=only_target, level_height=level_height)
    survey = lot_survey(buildings[0], proj) if buildings else None
    paths: dict[str, Path] = {}
    paths["glb"] = out_dir / f"{stem}.glb"
    scene.export(str(paths["glb"]))
    paths["obj"] = out_dir / f"{stem}.obj"
    scene.export(str(paths["obj"]))
    d2 = site_plan_drawing(buildings, proj, only_target=only_target, level_height=level_height, lang=lang, units=units, survey=survey)
    paths["svg"] = d2.save_svg(out_dir / f"{stem}.svg")
    paths["png"] = d2.save_png(out_dir / f"{stem}.png")
    pw, ph = page_size_pt(paper, "landscape")
    sc = min(1.0, (pw - 20 * PT_PER_MM) / d2.width, (ph - 20 * PT_PER_MM) / d2.height)
    paths["pdf"] = write_pdf(out_dir / f"{stem}.pdf", [(d2, pw, ph, (pw - d2.width * sc) / 2, (ph - d2.height * sc) / 2, sc)], title=t(lang, "site_plan"))
    d3 = site_iso_drawing(buildings, proj, only_target=only_target, level_height=level_height, lang=lang)
    paths["iso_png"] = d3.save_png(out_dir / f"{stem}_3d.png")
    paths["dxf"] = site_plan_dxf(buildings, proj, out_dir / f"{stem}.dxf", only_target=only_target, level_height=level_height, survey=survey, lang=lang)
    paths["json"] = out_dir / f"{stem}.json"
    payload = {
        "query": {"lat": lat, "lon": lon},
        "origin": {"lat": lat, "lon": lon, "note": "local frame: x east, y north, metres, z up from ground"},
        "buildings": rows,
        "lot": survey,
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "limits": "LOD1: footprint x height only; no walls, roof geometry or interior can be derived from overhead data.",
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["html"] = site_html(out_dir / f"{stem}.html", buildings, proj, render_svg(d2, standalone=False), render_svg(d3, standalone=False), rows, survey, lang=lang, units=units)
    return paths


# ----------------------------------------------------------------------------------------
# drawings
# ----------------------------------------------------------------------------------------


def site_plan_drawing(buildings: list[Building], proj: LocalProjection, only_target: bool = True, level_height: float = 3.0, lang: str = "en", units: str = "m", scale: float = 12.0, margin: float = 80.0, survey: dict | None = None) -> Drawing:
    from levanta.io.plan2d import _table

    polys = [b.polygon_local(proj) for b in buildings]
    shown = polys[:1] if only_target else polys
    xs = [c for p in shown for c in (p.bounds[0], p.bounds[2])] + [0.0]
    ys = [c for p in shown for c in (p.bounds[1], p.bounds[3])] + [0.0]
    xmin, xmax, ymin, ymax = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    MAX_ROWS = 40
    if survey:
        lengths_all = [s["length_m"] for s in survey["sides"]]
        min_label = 1.0 if len(lengths_all) <= 16 else max(2.5, float(np.sort(lengths_all)[-16]))
        keep_ids = {s["from"] for s in survey["sides"] if s["length_m"] >= min_label} | {s["to"] for s in survey["sides"] if s["length_m"] >= min_label}
        vrows_all = [[str(v["id"]), f"{v['x']:.2f}", f"{v['y']:.2f}", f"{v['utm_e']:.1f}", f"{v['utm_n']:.1f}"] for v in survey["vertices"] if v["id"] in keep_ids]
        srows_all = [[f"{s['from']}–{s['to']}", dms(s["azimuth_deg"]), fmt_len(s["length_m"], units)] for s in survey["sides"] if s["length_m"] >= min_label]
        n_rows = max(len(vrows_all), len(srows_all))
        below = n_rows > 14
    else:
        below = False
        n_rows = 0
    table_w = 300.0 if survey else 0.0
    map_w = (xmax - xmin) * scale + 2 * margin
    map_h = (ymax - ymin) * scale + 2 * margin + 30
    tables_h = (60 + 16 * (min(n_rows, MAX_ROWS) + 4)) if survey else 0
    if below:
        W = max(map_w, 2 * table_w + 60 + 2 * margin)
        H = map_h + tables_h + 40
    else:
        W = map_w + (table_w + 20 if table_w else 0)
        H = max(map_h, tables_h + 2 * margin)

    def X(x: float) -> float:
        return margin + (x - xmin) * scale

    def Y(y: float) -> float:
        return margin + (ymax - y) * scale

    def P(pts):
        return [(X(x), Y(y)) for x, y in pts]

    d = Drawing(W, H)
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
        if not survey:
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
        # numbered vertices (only the ones a surveyor would keep: long sides)
        if survey:
            for v in survey["vertices"]:
                if v["id"] in keep_ids:
                    d.circle(X(v["x"]), Y(v["y"]), 3, fill="#5a4a33", cls="vertex")
                    d.text(X(v["x"]) + 6, Y(v["y"]) - 5, str(v["id"]), size=10, anchor="start", weight="bold", color="#5a4a33", cls="vertex")
        h, how = b.height(level_height=level_height)
        d.text(X(c.x), Y(c.y), b.name or t(lang, "building"), size=13, weight="bold", cls="label")
        d.text(X(c.x), Y(c.y) + 14, f"{fmt_area(p.area, units)} · {t(lang, 'height')} {fmt_len(h, units)} ({t(lang, how)})", size=10.5, color="#666", cls="label")
    d.circle(X(0), Y(0), 3.5, fill="#c0392b", cls="query")
    ax, ay = X(xmax) + 24, margin
    d.line((ax, ay + 40), (ax, ay), stroke="#777", width=0.8)
    d.polygon([(ax - 5, ay + 12), (ax, ay), (ax + 5, ay + 12)], fill="#333")
    d.text(ax, ay + 54, "N", size=10.5, color="#666")
    sx, sy = X(xmax) - 10 * scale, map_h - 26
    d.polygon([(sx, sy), (sx + 5 * scale, sy), (sx + 5 * scale, sy + 6), (sx, sy + 6)], fill="#222")
    d.polygon([(sx + 5 * scale, sy), (sx + 10 * scale, sy), (sx + 10 * scale, sy + 6), (sx + 5 * scale, sy + 6)], fill=None, stroke="#222", width=0.8)
    d.text(sx, sy - 4, "0", size=10.5, anchor="start", color="#666")
    d.text(sx + 10 * scale, sy - 4, "10 m" if units == "m" else "33'", size=10.5, anchor="end", color="#666")
    attr = buildings[0].attribution if buildings else ""
    d.text(margin, map_h - 18, f"{t(lang, 'site_plan')} · {t(lang, 'generated_by')} · {attr} · {buildings[0].license if buildings else ''} · {_dt.date.today().isoformat()}", size=10.5, anchor="start", color="#666")
    if survey:
        u = survey["utm"]
        vrows = vrows_all[:MAX_ROWS]
        srows = srows_all[:MAX_ROWS]
        more_v = len(vrows_all) - len(vrows)
        more_s = len(srows_all) - len(srows)
        if more_v > 0:
            vrows.append([f"+{more_v}", "…", "", "", "JSON"])
        if more_s > 0:
            srows.append([f"+{more_s}", "…", "JSON"])
        title_v = f"{t(lang, 'coordinates')} · {t(lang, 'utm')} {u['zone']}{u['band']} (EPSG:{u['epsg']})"
        if below:
            tx1, tx2, ty0 = margin, margin + table_w + 60, map_h + 10
            _table(d, tx1, ty0, table_w, title_v, [t(lang, "vertex"), t(lang, "east"), t(lang, "north_coord"), "UTM E", "UTM N"], vrows, [0.12, 0.2, 0.2, 0.24, 0.24], 1.0, ["start", "end", "end", "end", "end"])
            ty = _table(d, tx2, ty0, table_w, t(lang, "boundaries"), [t(lang, "side"), t(lang, "azimuth"), t(lang, "length")], srows, [0.3, 0.4, 0.3], 1.0, ["start", "end", "end"])
            d.text(tx2, ty + 16, f"{t(lang, 'lot_area')}: {fmt_area(survey['area_m2'], units)} ({survey['area_ha']:.4f} ha)", size=9.5, anchor="start", color="#333")
            d.text(tx2, ty + 30, f"{t(lang, 'perimeter')} {fmt_len(survey['perimeter_m'], units)} · {t(lang, 'closure')} {survey['closure_m'] * 1000:.0f} mm", size=9.5, anchor="start", color="#333")
        else:
            tx = map_w
            ty = margin - 20
            ty = _table(d, tx, ty, table_w, title_v, [t(lang, "vertex"), t(lang, "east"), t(lang, "north_coord"), "UTM E", "UTM N"], vrows, [0.12, 0.2, 0.2, 0.24, 0.24], 1.0, ["start", "end", "end", "end", "end"])
            ty = _table(d, tx, ty + 14, table_w, t(lang, "boundaries"), [t(lang, "side"), t(lang, "azimuth"), t(lang, "length")], srows, [0.3, 0.4, 0.3], 1.0, ["start", "end", "end"])
            d.text(tx, ty + 16, f"{t(lang, 'lot_area')}: {fmt_area(survey['area_m2'], units)} ({survey['area_ha']:.4f} ha) · {t(lang, 'perimeter')} {fmt_len(survey['perimeter_m'], units)} · {t(lang, 'closure')} {survey['closure_m'] * 1000:.0f} mm", size=9.5, anchor="start", color="#333")
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


def site_html(path: Path, buildings: list[Building], proj: LocalProjection, svg_2d: str, svg_iso: str, rows: list[dict], survey: dict | None, lang: str = "en", units: str = "m") -> Path:
    b = buildings[0]
    p = b.polygon_local(proj)
    h, how = b.height()
    title = b.name or t(lang, "building")
    table = "".join(
        f"<tr><td>{_html.escape(str(r.get('name') or r['id']))}</td><td class=num>{fmt_area(r.get('footprint_area_m2', 0.0), units)}</td><td class=num>{fmt_len(r['height_used_m'], units)}</td><td>{t(lang, r['height_source'])}</td><td>{_html.escape(r['source'])}</td></tr>"
        for r in rows
    )
    vtable = stable = ""
    if survey:
        u = survey["utm"]
        vtable = f"<h2 style='margin-top:18px'>{t(lang, 'coordinates')} · {t(lang, 'utm')} {u['zone']}{u['band']} (EPSG:{u['epsg']})</h2><table><thead><tr><th>{t(lang, 'vertex')}</th><th>{t(lang, 'east')}</th><th>{t(lang, 'north_coord')}</th><th>Lat</th><th>Lon</th><th>UTM E</th><th>UTM N</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{v['id']}</td><td class=num>{v['x']:.2f}</td><td class=num>{v['y']:.2f}</td><td class=num>{v['lat']:.6f}</td><td class=num>{v['lon']:.6f}</td><td class=num>{v['utm_e']:.2f}</td><td class=num>{v['utm_n']:.2f}</td></tr>" for v in survey["vertices"]
        ) + "</tbody></table>"
        stable = f"<h2 style='margin-top:18px'>{t(lang, 'boundaries')}</h2><table><thead><tr><th>{t(lang, 'side')}</th><th>{t(lang, 'azimuth')}</th><th>{t(lang, 'length')}</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{s['from']}–{s['to']}</td><td class=num>{dms(s['azimuth_deg'])}</td><td class=num>{fmt_len(s['length_m'], units)}</td></tr>" for s in survey["sides"]
        ) + f"</tbody></table><p class='hint'>{t(lang, 'lot_area')}: {fmt_area(survey['area_m2'], units)} ({survey['area_ha']:.4f} ha) · {t(lang, 'perimeter')} {fmt_len(survey['perimeter_m'], units)} · {t(lang, 'closure')} {survey['closure_m'] * 1000:.0f} mm</p>"
    doc = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html.escape(title)} · levanta</title>
<style>body{{margin:0;background:#faf8f4;color:#1d1d1f;font-family:Inter,'Segoe UI',Helvetica,Arial,sans-serif;line-height:1.45}}header{{padding:28px 32px 12px}}h1{{margin:0 0 4px;font-size:24px}}.sum{{color:#6b6b6f;font-size:14px}}
main{{display:grid;grid-template-columns:1fr;gap:20px;padding:0 32px 40px;max-width:1500px}}@media(min-width:1100px){{main{{grid-template-columns:1fr 1fr}}.wide{{grid-column:1/-1}}}}
.card{{background:#fff;border:1px solid #e6e3dd;border-radius:14px;padding:18px 20px}}.card h2{{margin:0 0 10px;font-size:15px;font-weight:600;color:#6b6b6f;text-transform:uppercase;letter-spacing:.06em}}.card svg{{width:100%;height:auto;display:block}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #e6e3dd}}th{{color:#6b6b6f;font-size:12px;text-transform:uppercase}}td.num{{text-align:right;font-variant-numeric:tabular-nums}}.hint{{font-size:12px;color:#6b6b6f;margin-top:8px}}footer{{padding:10px 32px 30px;color:#6b6b6f;font-size:12px}}</style></head>
<body><header><h1>{_html.escape(title)}</h1><div class="sum">{t(lang, 'footprint')} {fmt_area(p.area, units)} · {t(lang, 'perimeter')} {fmt_len(p.length, units)} · {t(lang, 'height')} {fmt_len(h, units)} ({t(lang, how)}) · {t(lang, 'source')}: {_html.escape(b.attribution)} ({_html.escape(b.license)})</div></header>
<main><section class="card wide"><h2>{t(lang, 'site_plan')}</h2>{svg_2d}</section>
<section class="card"><h2>{t(lang, 'view_3d')} (LOD1)</h2>{svg_iso}<div class="hint">{t(lang, 'site_limits')}</div></section>
<section class="card"><h2>{t(lang, 'measurements')}</h2><table><thead><tr><th>{t(lang, 'name')}</th><th>{t(lang, 'footprint')}</th><th>{t(lang, 'height')}</th><th>{t(lang, 'source')} ({t(lang, 'height')})</th><th>{t(lang, 'source')}</th></tr></thead><tbody>{table}</tbody></table>{stable}</section>
<section class="card wide">{vtable}</section></main>
<footer>{t(lang, 'generated_by')} · MIT · github.com/EazyHood/levanta</footer></body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path


def site_plan_dxf(buildings: list[Building], proj: LocalProjection, path: str | Path, only_target: bool = True, level_height: float = 3.0, survey: dict | None = None, lang: str = "en") -> Path:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    path = Path(path)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for name, color in (("C-BLDG", 7), ("C-BLDG-NEAR", 8), ("C-ANNO-TEXT", 7), ("C-ANNO-DIMS", 4), ("C-PROP-VERT", 1), ("C-ANNO-TABL", 7)):
        doc.layers.add(name, color=color)
    doc.dimstyles.new("LEVANTA", dxfattribs={"dimtxt": 0.5, "dimasz": 0.3, "dimexe": 0.2, "dimexo": 0.2, "dimdec": 2, "dimtad": 1, "dimgap": 0.1})
    msp = doc.modelspace()
    chosen = buildings[:1] if only_target else buildings
    for i, b in enumerate(chosen):
        p = b.polygon_local(proj)
        layer = "C-BLDG" if i == 0 else "C-BLDG-NEAR"
        msp.add_lwpolyline(list(p.exterior.coords), close=True, dxfattribs={"layer": layer})
        for ring in p.interiors:
            msp.add_lwpolyline(list(ring.coords), close=True, dxfattribs={"layer": layer})
        if i == 0:
            h, how = b.height(level_height=level_height)
            c = p.centroid
            msp.add_mtext(f"{b.name or 'Building'}\n{p.area:.1f} m2\nh = {h:.1f} m ({how})", dxfattribs={"layer": "C-ANNO-TEXT", "char_height": 0.6, "insert": (c.x, c.y), "attachment_point": 5})
            coords = list(p.exterior.coords)
            for (x0, y0), (x1, y1) in pairwise(coords):
                if np.hypot(x1 - x0, y1 - y0) >= 1.0:
                    msp.add_aligned_dim(p1=(x0, y0), p2=(x1, y1), distance=1.0, dimstyle="LEVANTA", dxfattribs={"layer": "C-ANNO-DIMS"}).render()
    msp.add_point((0.0, 0.0), dxfattribs={"layer": "C-ANNO-TEXT"})
    if survey:
        for v in survey["vertices"]:
            msp.add_circle((v["x"], v["y"]), radius=0.25, dxfattribs={"layer": "C-PROP-VERT"})
            msp.add_text(str(v["id"]), dxfattribs={"layer": "C-PROP-VERT", "height": 0.5}).set_placement((v["x"] + 0.4, v["y"] + 0.4), align=TextEntityAlignment.BOTTOM_LEFT)
        # tables to the right
        xmax = max(v["x"] for v in survey["vertices"]) + 6.0
        y = max(v["y"] for v in survey["vertices"])
        u = survey["utm"]
        rows = [[str(v["id"]), f"{v['x']:.2f}", f"{v['y']:.2f}", f"{v['utm_e']:.2f}", f"{v['utm_n']:.2f}"] for v in survey["vertices"]]
        y = _dxf_rows(msp, xmax, y, f"{t(lang, 'coordinates')} UTM {u['zone']}{u['band']} EPSG:{u['epsg']}", [t(lang, "vertex"), "E (m)", "N (m)", "UTM E", "UTM N"], rows, [2.0, 3.0, 3.0, 4.0, 4.0])
        rows = [[f"{s['from']}-{s['to']}", dms(s["azimuth_deg"]), f"{s['length_m']:.2f} m"] for s in survey["sides"]]
        y = _dxf_rows(msp, xmax, y - 1.0, t(lang, "boundaries"), [t(lang, "side"), t(lang, "azimuth"), t(lang, "length")], rows, [3.0, 4.0, 3.0])
        msp.add_text(f"{t(lang, 'lot_area')}: {survey['area_m2']:.2f} m2 ({survey['area_ha']:.4f} ha) - {t(lang, 'perimeter')} {survey['perimeter_m']:.2f} m - {t(lang, 'closure')} {survey['closure_m'] * 1000:.0f} mm", dxfattribs={"layer": "C-ANNO-TABL", "height": 0.45}).set_placement((xmax, y - 1.0), align=TextEntityAlignment.BOTTOM_LEFT)
    doc.saveas(path)
    return path


def _dxf_rows(msp, x: float, y: float, title: str, headers: list[str], rows: list[list[str]], widths: list[float]) -> float:
    from ezdxf.enums import TextEntityAlignment

    rh = 0.9
    msp.add_text(title, dxfattribs={"layer": "C-ANNO-TABL", "height": 0.55}).set_placement((x, y), align=TextEntityAlignment.BOTTOM_LEFT)
    y -= 0.3
    total = sum(widths)
    cols = np.cumsum([0.0, *widths])
    for row in [headers, *rows]:
        y0 = y - rh
        msp.add_lwpolyline([(x, y), (x + total, y), (x + total, y0), (x, y0)], close=True, dxfattribs={"layer": "C-ANNO-TABL"})
        for j, cell in enumerate(row):
            msp.add_text(cell, dxfattribs={"layer": "C-ANNO-TABL", "height": 0.4}).set_placement((x + cols[j] + 0.2, y0 + 0.25), align=TextEntityAlignment.BOTTOM_LEFT)
        y = y0
    return y
