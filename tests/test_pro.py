"""The drafter's checklist: chains, tags, schedules, title block, PDF, elevations, DXF, UTM."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import ezdxf
import numpy as np

from levanta.io.draw import render_svg
from levanta.io.elevations import elevations_drawing
from levanta.io.export import export_all, export_dxf, export_dxf_3d, export_pdf
from levanta.io.pdf import text_width
from levanta.io.plan2d import dimension_chains, floor_plan_drawing, reference_axes
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from levanta.site.projection import azimuth_deg, dms, utm_from_latlon


def _plan() -> FloorPlan:
    p = FloorPlan(
        walls=[
            Wall(0, (0, 0), (4, 0), 0.2, 2.5, exterior=True),
            Wall(1, (4, 0), (4, 3), 0.2, 2.5, exterior=True),
            Wall(2, (4, 3), (0, 3), 0.2, 2.5, exterior=True),
            Wall(3, (0, 3), (0, 0), 0.2, 2.5, exterior=True),
        ],
        rooms=[Room(0, "Sala", [(0.1, 0.1), (3.9, 0.1), (3.9, 2.9), (0.1, 2.9)])],
        openings=[Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05, height_measured=True), Opening(1, 2, "window", 1.0, 2.2, 0.9, 2.1, height_measured=True)],
        ceiling_height=2.5,
        north_deg=30.0,
        project={"name": "Casa Pérez", "author": "J. del Río", "sheet": "A-02", "level": "±0.00"},
    )
    return p.label_openings()


def test_tags_chains_axes_and_summary():
    p = _plan()
    assert [o.tag for o in p.openings] == ["P1", "V1"]
    chains = dimension_chains(p)
    assert len(chains) == 4  # every perimeter wall gets a chain
    south = next(c for c in chains if c["wall"].id == 0)
    assert south["stations"] == [0.0, 1.0, 1.9, 4.0]  # corner - jamb - jamb - corner
    letters, numbers = reference_axes(p)
    assert [lab for lab, _ in letters] == ["A", "B"] and [lab for lab, _ in numbers] == ["1", "2"]
    s = p.area_summary()
    assert abs(s["useful_m2"] - 10.64) < 1e-6 and s["walls_m2"] > 2.0 and s["gross_m2"] > s["useful_m2"]
    qa = p.quality("es")
    assert any("4 de 4" in q["text"] for q in qa)  # one-sided walls reported


def test_sheet_has_every_professional_element():
    d = floor_plan_drawing(_plan(), lang="es", print_scale=100)
    svg = render_svg(d)
    classes = {c for el in ET.fromstring(svg).iter() for c in (el.get("class") or "").split()}
    assert {"dim-chain", "axis", "north", "table", "titleblock", "tag"} <= classes
    assert "Cuadro de áreas" in svg and "Cuadro de carpinterías" in svg and "1:100" in svg and "Casa Pérez" in svg and "P1" in svg


def test_elevations_show_openings_with_heights():
    d = elevations_drawing(_plan(), lang="en")
    svg = render_svg(d)
    classes = {c for el in ET.fromstring(svg).iter() for c in (el.get("class") or "").split()}
    assert {"elev-wall", "elev-door", "elev-window"} <= classes and "Interior elevations" in svg


def test_pdf_is_valid_vector_at_a_standard_scale(tmp_path):
    p = export_pdf(_plan(), tmp_path / "plan.pdf", paper="A4", lang="es")
    data = p.read_bytes()
    assert data.startswith(b"%PDF-1.4") and b"/Type /Page" in data and b"%%EOF" in data and b"Helvetica" in data
    assert data.count(b"/Type /Page ") == 2  # plan + elevations
    assert abs(text_width("Hola", 10) - 10 * (722 + 556 + 222 + 556) / 1000) < 1e-9


def test_dxf_layers_blocks_units_and_3d(tmp_path):
    p = export_dxf(_plan(), tmp_path / "plan.dxf", lang="es", dxf_units="cm")
    doc = ezdxf.readfile(p)
    assert doc.header["$INSUNITS"] == 5
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"A-WALL", "A-AREA", "A-DOOR", "A-GLAZ", "A-ANNO-DIMS", "A-ANNO-TEXT", "A-GRID", "A-ANNO-TTLB", "A-ANNO-TABL", "A-ANNO-NORTH"} <= layers
    inserts = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert {e.dxf.name for e in inserts} == {"LEVANTA_DOOR", "LEVANTA_WINDOW"}
    door = next(e for e in inserts if e.dxf.name == "LEVANTA_DOOR")
    assert abs(abs(door.dxf.xscale) - 90.0) < 1e-6  # 0.9 m door in cm
    walls = [e for e in doc.modelspace().query("LWPOLYLINE") if e.dxf.layer == "A-WALL"]
    xs = [v[0] for e in walls for v in e.get_points()]
    assert max(xs) > 400  # coordinates scaled to cm
    p3 = export_dxf_3d(_plan(), tmp_path / "plan_3d.dxf")
    doc3 = ezdxf.readfile(p3)
    faces = [e for e in doc3.modelspace() if e.dxftype() == "3DFACE"]
    assert len(faces) > 30 and {e.dxf.layer for e in faces} >= {"A-WALL-3D", "A-FLOR-3D", "A-DOOR-3D"}


def test_export_all_writes_the_sheet_set(tmp_path):
    paths = export_all(_plan(), tmp_path, stem="t", lang="es", paper="A3", dxf_units="mm")
    for k in ("pdf", "elev_png", "dxf3d", "html", "png"):
        assert paths[k].exists() and paths[k].stat().st_size > 500, k
    html_text = paths["html"].read_text(encoding="utf-8")
    assert "Comprobaciones" in html_text and "Alzados interiores" in html_text and "pxPerM" in html_text and "P1" in html_text


def test_utm_bogota_and_bearings():
    u = utm_from_latlon(4.5981, -74.0760)
    assert u["zone"] == 18 and u["hemisphere"] == "N" and u["epsg"] == 32618 and u["band"] == "N"
    assert 598_000 < u["easting"] < 607_000 and 505_000 < u["northing"] < 512_000  # 0.924 deg east of the zone meridian
    s = utm_from_latlon(-33.4489, -70.6693)  # Santiago de Chile
    assert s["zone"] == 19 and s["hemisphere"] == "S" and 6_290_000 < s["northing"] < 6_310_000
    assert abs(azimuth_deg(1, 0) - 90) < 1e-9 and abs(azimuth_deg(0, -1) - 180) < 1e-9 and abs(azimuth_deg(-1, 1) - 315) < 1e-9
    assert dms(45.5) == "45°30'00\"" and dms(0.999999) == "1°00'00\""
    assert np.isfinite(u["easting"])
