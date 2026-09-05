"""Control experiments: synthetic apartments with known answers.

The thresholds below were fixed *before* the first run of the pipeline on these
scenes (see README, "How we know it works").
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from tests.synthetic import (
    match_rooms,
    opening_center,
    rigid_perturbation,
    sample_apartment,
    three_rooms,
    two_rooms,
)

ROOM_IOU_MIN = 0.90
DOOR_POS_TOL = 0.25
DOOR_WIDTH_TOL = 0.20
THICKNESS_TOL = 0.03
CEILING_TOL = 0.03


def _plan_openings_xy(plan, kind):
    out = []
    for o in plan.openings:
        if o.kind != kind:
            continue
        w = plan.wall_by_id(o.wall_id)
        c = w.point_at((o.t0 + o.t1) / 2)
        out.append((np.array(c), o.width, o))
    return out


def _check(apt, plan, rooms_expected: int):
    gt_polys = [r.polygon for r in apt.rooms]
    pred_polys: list[Polygon] = [r.shapely for r in plan.rooms]
    assert len(pred_polys) == rooms_expected, plan.summary()
    matches = match_rooms(gt_polys, pred_polys)
    assert len(matches) == rooms_expected
    for i, _j, iou in matches:
        assert iou >= ROOM_IOU_MIN, f"room {apt.rooms[i].name}: IoU {iou:.3f}\n{plan.summary()}"
    # doors
    doors = _plan_openings_xy(plan, "door")
    for o in [o for o in apt.openings if o.kind == "door"]:
        c = opening_center(o)
        best = min(doors, key=lambda d: np.linalg.norm(d[0] - c), default=None)
        assert best is not None and np.linalg.norm(best[0] - c) <= DOOR_POS_TOL, f"door at {c} missing\n{plan.summary()}"
        assert abs(best[1] - (o.t1 - o.t0)) <= DOOR_WIDTH_TOL, f"door width {best[1]:.2f} vs {o.t1 - o.t0:.2f}"
    # windows
    wins = _plan_openings_xy(plan, "window")
    for o in [o for o in apt.openings if o.kind == "window"]:
        c = opening_center(o)
        best = min(wins, key=lambda d: np.linalg.norm(d[0] - c), default=None)
        assert best is not None and np.linalg.norm(best[0] - c) <= DOOR_POS_TOL, f"window at {c} missing\n{plan.summary()}"
        assert abs(best[2].z0 - o.z0) <= 0.10 and abs(best[2].z1 - o.z1) <= 0.10
    # thickness of measured (two-sided) walls
    two_sided = [w for w in plan.walls if w.sides_seen == 2]
    assert two_sided, "no wall was measured from both sides"
    for w in two_sided:
        assert abs(w.thickness - apt.wall_int) <= THICKNESS_TOL, f"thickness {w.thickness:.3f}"
    assert plan.ceiling_measured and abs(plan.ceiling_height - apt.height) <= CEILING_TOL


def test_two_rooms_axis_aligned():
    apt = two_rooms()
    cloud = sample_apartment(apt, seed=1)
    res = extract_floor_plan(cloud, PlanOptions())
    _check(apt, res.plan, 2)
    # exterior walls: a single face with nothing behind -> the exterior default thickness
    ext = [w for w in res.plan.walls if w.sides_seen == 1]
    assert len(ext) == 4 and all(abs(w.thickness - PlanOptions().default_exterior_thickness) < 1e-6 for w in ext)


def test_three_rooms_rotated_and_tilted():
    apt = three_rooms()
    T = rigid_perturbation(tilt_deg=9.0, yaw_deg=23.0)
    cloud = sample_apartment(apt, seed=2, rigid=T)
    res = extract_floor_plan(cloud, PlanOptions())
    plan = res.plan
    # bring predictions back to the apartment frame: plan frame = T_total @ input; input = T @ gt
    M = np.array(plan.transform) @ T
    R = M[:3, :3]
    # the recovered frame may differ by a multiple of 90 deg and a translation; undo it
    yaw = np.arctan2(R[1, 0], R[0, 0])
    k = np.round(yaw / (np.pi / 2))
    residual = yaw - k * np.pi / 2
    assert abs(np.degrees(residual)) < 1.0, f"Manhattan residual {np.degrees(residual):.2f} deg"
    assert abs(R[2, 2] - 1.0) < 2e-3, "gravity not recovered"
    from levanta.plan.types import FloorPlan

    inv = np.linalg.inv(M)

    def back(p):
        q = inv[:3, :3] @ np.array([p[0], p[1], 0.0]) + inv[:3, 3]
        return (float(q[0]), float(q[1]))

    plan_back = FloorPlan.from_dict(plan.to_dict())
    for w in plan_back.walls:
        w.a, w.b = back(w.a), back(w.b)
    for r in plan_back.rooms:
        r.polygon = [back(p) for p in r.polygon]
        r.holes = [[back(p) for p in h] for h in r.holes]
    _check(apt, plan_back, 3)


def test_pca_normals_path_when_normals_missing():
    apt = two_rooms()
    cloud = sample_apartment(apt, seed=3, furniture=0)
    cloud.normals = None
    res = extract_floor_plan(cloud, PlanOptions())
    assert len(res.plan.rooms) == 2
    matches = match_rooms([r.polygon for r in apt.rooms], [r.shapely for r in res.plan.rooms])
    assert all(iou >= 0.85 for _, _, iou in matches)


def test_free_mode_finds_same_rooms():
    apt = two_rooms()
    cloud = sample_apartment(apt, seed=4)
    res = extract_floor_plan(cloud, PlanOptions(manhattan=False))
    assert len(res.plan.rooms) == 2


def test_rejects_cloud_without_walls():
    rng = np.random.default_rng(0)
    from levanta.scene import PointCloud

    xy = rng.uniform(0, 3, (2000, 2))
    cloud = PointCloud(xyz=np.c_[xy, np.zeros(2000)], normals=np.tile([0, 0, 1.0], (2000, 1)))
    with pytest.raises(ValueError):
        extract_floor_plan(cloud, PlanOptions())
