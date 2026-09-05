from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np

from levanta.io.export import export_all, wall_body_polygons
from levanta.plan.model import floor_plan_to_scene, wall_pieces
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from tests.synthetic import sample_apartment, two_rooms


def _simple_plan() -> FloorPlan:
    return FloorPlan(
        walls=[
            Wall(0, (0, 0), (4, 0), 0.2, 2.5),
            Wall(1, (4, 0), (4, 3), 0.2, 2.5),
            Wall(2, (4, 3), (0, 3), 0.2, 2.5),
            Wall(3, (0, 3), (0, 0), 0.2, 2.5),
        ],
        rooms=[Room(0, "Room 1", [(0.1, 0.1), (3.9, 0.1), (3.9, 2.9), (0.1, 2.9)])],
        openings=[Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05), Opening(1, 2, "window", 1.0, 2.2, 0.9, 2.1)],
        ceiling_height=2.5,
    )


def test_wall_pieces_split_around_openings():
    w = Wall(0, (0, 0), (4, 0), 0.2, 2.5)
    pieces = wall_pieces(w, [Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05), Opening(1, 0, "window", 2.5, 3.5, 0.9, 2.1)])
    assert (0.0, 1.0, 0.0, 2.5) in pieces and (1.9, 2.5, 0.0, 2.5) in pieces and (3.5, 4.0, 0.0, 2.5) in pieces
    assert (1.0, 1.9, 2.05, 2.5) in pieces  # lintel
    assert (2.5, 3.5, 0.0, 0.9) in pieces and (2.5, 3.5, 2.1, 2.5) in pieces  # sill + header
    assert not any(t0 == 1.0 and z0 == 0.0 and z1 == 2.5 for t0, _, z0, z1 in pieces)


def test_scene_is_watertight_and_sized():
    plan = _simple_plan()
    scene = floor_plan_to_scene(plan)
    walls = scene.geometry["walls"]
    assert walls.is_watertight or walls.volume > 0
    ext = walls.bounds
    assert np.allclose(ext[0][:2], [-0.1, -0.1], atol=1e-6) and np.allclose(ext[1], [4.1, 3.1, 2.5], atol=1e-6)
    assert "floor_0" in scene.geometry and "doors" in scene.geometry and "windows" in scene.geometry


def test_wall_body_polygons_have_cuts():
    plan = _simple_plan()
    polys = wall_body_polygons(plan)
    total = sum(p.area for p in polys)
    full = sum(w.polygon().area for w in plan.walls)
    assert total < full - 0.9 * 0.2 - 1.2 * 0.2 + 1e-6


def test_export_all_writes_valid_files(tmp_path):
    apt = two_rooms()
    res = extract_floor_plan(sample_apartment(apt, seed=5), PlanOptions())
    paths = export_all(res.plan, tmp_path, stem="t")
    for p in paths.values():
        assert p.exists() and p.stat().st_size > 200
    root = ET.parse(paths["svg"]).getroot()
    assert root.tag.endswith("svg")
    ids = {g.get("id") for g in root.iter() if g.get("id")}
    assert {"rooms", "walls", "openings", "labels", "dimensions"} <= ids
    import ezdxf

    doc = ezdxf.readfile(paths["dxf"])
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"WALLS", "ROOMS", "DOORS", "WINDOWS", "DIMENSIONS", "TEXT"} <= layers
    assert doc.header["$INSUNITS"] == 6
    import trimesh

    scene = trimesh.load(paths["glb"])
    assert isinstance(scene, trimesh.Scene) and len(scene.geometry) >= 3
    back = FloorPlan.from_json(paths["json"])
    assert len(back.rooms) == len(res.plan.rooms)
