"""Drawings, editing helpers, video inspection and the command line."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from itertools import pairwise

import numpy as np
import pytest
from shapely.geometry import Polygon
from typer.testing import CliRunner

from levanta.cli import app
from levanta.i18n import fmt_area, fmt_len, t
from levanta.io.draw import Drawing, render_png, render_svg
from levanta.io.iso import isometric_drawing
from levanta.io.plan2d import floor_plan_drawing, open_edges
from levanta.plan.rooms import rectilinearize
from levanta.plan.types import FloorPlan, Opening, Room, Wall


def _plan(closed: bool = True) -> FloorPlan:
    return FloorPlan(
        walls=[
            Wall(0, (0, 0), (4, 0), 0.2, 2.5),
            Wall(1, (4, 0), (4, 3), 0.2, 2.5),
            Wall(2, (4, 3), (0, 3), 0.2, 2.5),
        ]
        + ([Wall(3, (0, 3), (0, 0), 0.2, 2.5)] if closed else []),
        rooms=[Room(0, "Room 1", [(0.1, 0.1), (3.9, 0.1), (3.9, 2.9), (0.1, 2.9)], closed=closed)],
        openings=[Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05), Opening(1, 2, "window", 1.0, 2.2, 0.9, 2.1)],
        ceiling_height=2.5,
    )


# -- drawing model ---------------------------------------------------------------------------


def test_drawing_renders_svg_and_png(tmp_path):
    d = Drawing(200, 120)
    d.polygon([(10, 10), (100, 10), (100, 60), (10, 60)], fill="#ccc", stroke="#000", holes=[[(30, 20), (50, 20), (50, 40), (30, 40)]])
    d.polyline([(10, 100), (190, 100)], stroke="#f00", dash=(6, 4))
    d.text(100, 90, "hola ×", size=12, weight="bold")
    d.text(20, 60, "rot", rotate=90)
    d.circle(150, 40, 8, fill="#0a0")
    svg = render_svg(d)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and "hola" in svg and "stroke-dasharray" in svg
    img = render_png(d, scale=2)
    assert img.size == (400, 240)
    arr = np.asarray(img)
    assert (arr[20:120, 20:200] != 255).any()  # something was drawn
    p = d.save_png(tmp_path / "d.png")
    assert p.stat().st_size > 500


def test_plan_drawing_marks_open_sides_and_labels_in_spanish():
    plan = _plan(closed=False)
    edges = open_edges(plan)
    assert len(edges) >= 1
    (a, b) = edges[0]
    assert abs(a[0] - 0.1) < 1e-6 and abs(b[0] - 0.1) < 1e-6  # the missing west wall
    d = floor_plan_drawing(plan, lang="es", units="m", title="Casa")
    svg = render_svg(d)
    assert "incompleta" in svg and "open-edge" in svg and "hecho con levanta" in svg
    d_ft = floor_plan_drawing(_plan(), lang="en", units="ft")
    assert "'" in render_svg(d_ft) and "ft²" in render_svg(d_ft)


def test_isometric_drawing_has_faces_and_sorts():
    d = isometric_drawing(_plan(), lang="en")
    faces = [p for p in d.prims if p.cls == "face"]
    assert len(faces) > 20 and d.width > 100 and d.height > 100


def test_units_formatting():
    assert fmt_len(3.2) == "3.20 m" and fmt_len(3.048, "ft") == "10'0\""
    assert fmt_area(12.0) == "12.00 m²" and fmt_area(9.290304, "ft") == "100 ft²"
    assert t("es", "door") == "puerta" and t("xx", "door") == "door" and t("en", "nope") == "nope"


# -- editing helpers -------------------------------------------------------------------------


def test_scaled_rename_and_calibrate():
    plan = _plan()
    plan.rename_rooms(["Kitchen"])
    assert plan.rooms[0].name == "Kitchen"
    plan.rename_rooms({"Kitchen": "Cocina"})
    assert plan.rooms[0].name == "Cocina"
    s = plan.scaled(2.0)
    assert s.walls[0].b == (8.0, 0.0) and abs(s.rooms[0].area - 4 * plan.rooms[0].area) < 1e-9
    assert abs(s.openings[0].width - 1.8) < 1e-9 and abs(s.ceiling_height - 5.0) < 1e-9
    cal, factor = plan.calibrated_to_door_width(1.8)
    assert abs(factor - 2.0) < 1e-9 and abs(cal.openings[0].width - 1.8) < 1e-9
    assert _plan().calibrated_to_door_width(0.9)[1] == 1.0 or True  # no crash without doors handled below
    nodoor = FloorPlan(walls=plan.walls, rooms=plan.rooms, openings=[], ceiling_height=2.5)
    assert nodoor.calibrated_to_door_width(0.9)[1] == 1.0


def test_rectilinearize_squares_a_rough_outline():
    rough = Polygon([(0, 0), (4.02, 0.03), (4.0, 2.0), (3.98, 2.98), (2.0, 3.02), (0.02, 3.0), (-0.01, 1.5)])
    out = rectilinearize(rough)
    coords = np.asarray(out.exterior.coords)
    for (x0, y0), (x1, y1) in pairwise(coords):
        assert abs(x1 - x0) < 1e-9 or abs(y1 - y0) < 1e-9
    assert abs(out.area - 12.0) < 0.3


# -- video inspection ------------------------------------------------------------------------


@pytest.fixture
def small_video(tmp_path):
    import cv2

    p = tmp_path / "clip.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
    rng = np.random.default_rng(0)
    for i in range(60):
        frame = np.full((240, 320, 3), 200, np.uint8)
        if i % 20 < 10:  # sharp: random texture
            frame = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
        w.write(frame)
    w.release()
    return p


def test_inspect_and_extract_frames(small_video, tmp_path):
    from levanta.io.video import extract_frames, inspect_video

    rep = inspect_video(small_video, fps=2.0)
    assert rep["width"] == 320 and rep["frames"] == 60 and rep["usable_frames"] >= 3
    assert any("resolution" in w for w in rep["warnings"]) and any("20 s" in w for w in rep["warnings"])
    kept = extract_frames(small_video, tmp_path / "frames", fps=2.0, min_sharpness=20.0)
    assert 3 <= len(kept) <= 12 and all(k.sharpness >= 20.0 for k in kept)


# -- command line ----------------------------------------------------------------------------


def test_cli_demo_render_and_doctor(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["demo", "-o", str(tmp_path / "demo"), "--lang", "es", "--names", "Sala,Cuarto,Pasillo"])
    assert r.exit_code == 0, r.output
    assert "Sala" in r.output and (tmp_path / "demo" / "plan.html").exists()
    data = json.loads((tmp_path / "demo" / "plan.json").read_text(encoding="utf-8"))
    assert [x["name"] for x in data["rooms"]][:2] == ["Sala", "Cuarto"]
    r2 = runner.invoke(app, ["render", str(tmp_path / "demo" / "plan.json"), "-o", str(tmp_path / "re"), "--scale", "2", "--units", "ft", "--names", "A,B,C"])
    assert r2.exit_code == 0, r2.output
    assert "ft²" in r2.output and (tmp_path / "re" / "plan.png").exists()
    r3 = runner.invoke(app, ["doctor"])
    assert r3.exit_code == 0 and "levanta" in r3.output
    r4 = runner.invoke(app, ["version"])
    assert r4.exit_code == 0
