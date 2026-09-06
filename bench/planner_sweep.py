"""Choose planner settings by looking at every scene at once, not one against another.

Two rounds in a row a change that helped one case quietly hurt another: round 4 made an
open room's outline snap to the *nearest* parallel wall (ARKitScenes area went from −44 %
to −9 %) and that shrank the TUM room from 24.5 m² to 22.4 m² and cut its walls from 5.80
to 3.68 m, which nobody saw until the apartment benchmark sent me back to the TUM.

This replans saved clouds (no network, no GPU) under several settings and prints the area
error of every scene under each, so a setting is judged on all of them together.

Usage: python bench/planner_sweep.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

import levanta.plan.tidy as tidy
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.scene import PointCloud

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = tidy.snap_edges_to_walls


def snapper(score_mode: str):
    """`snap_edges_to_walls` with the two scorings that have been in the tree: the wall with
    the most overlap wins (before round 4), or the nearest wall wins (round 4 onwards)."""

    def snap(poly, walls, max_dist=1.0, min_overlap=0.5, angle_tol_deg=10.0):
        src = orient(poly, sign=1.0)
        pts = [np.array(p, dtype=float) for p in src.exterior.coords[:-1]]
        n = len(pts)
        if n < 4 or not walls:
            return poly
        cos_tol = np.cos(np.deg2rad(angle_tol_deg))
        shifts = np.zeros(n)
        normals = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            d = b - a
            length = float(np.linalg.norm(d))
            if length < 1e-9:
                normals.append(np.zeros(2))
                continue
            d /= length
            nrm = np.array([d[1], -d[0]])
            normals.append(nrm)
            best = None
            for wa, wb, th in walls:
                wd = wb - wa
                wl = float(np.linalg.norm(wd))
                if wl < 0.3:
                    continue
                wd /= wl
                if abs(float(wd @ d)) < cos_tol:
                    continue
                off = float((wa - a) @ nrm)
                if off < -max_dist or off > max_dist:
                    continue
                ta, tb = float((wa - a) @ d), float((wb - a) @ d)
                lo, hi = max(0.0, min(ta, tb)), min(length, max(ta, tb))
                overlap = hi - lo
                if overlap < min_overlap * length:
                    continue
                inner = off - np.sign(off) * th / 2 if abs(off) > th / 2 else 0.0
                score = (overlap, -abs(off)) if score_mode == "overlap" else (-abs(off), overlap)
                if best is None or score > best[0]:
                    best = (score, inner)
            if best is not None:
                shifts[i] = best[1]
        if not np.any(shifts):
            return poly
        new_pts = [p.copy() for p in pts]
        for i in range(n):
            if shifts[i] == 0.0:
                continue
            delta = normals[i] * shifts[i]
            new_pts[i] = new_pts[i] + delta
            new_pts[(i + 1) % n] = new_pts[(i + 1) % n] + delta
        out = Polygon([tuple(p) for p in new_pts]).buffer(0)
        if out.geom_type == "MultiPolygon":
            out = max(out.geoms, key=lambda g: g.area)
        if not out.is_valid or out.is_empty or out.area < 0.5 * poly.area:
            return poly
        return out

    return snap


def scenes() -> list[tuple[str, Path, float, int]]:
    """(name, cloud, truth area m2, truth rooms)."""
    out: list[tuple[str, Path, float, int]] = []
    rows = json.loads((ROOT / "bench/results/arkitscenes_2026-09-05_round4.json").read_text(encoding="utf-8"))
    for r in rows:
        p = ROOT / "out/bench3" / r["video_id"] / "noK" / "plan_cloud.ply"
        if p.exists():
            out.append((r["video_id"], p, r["truth_area_m2"], r["truth_rooms"]))
    tum = ROOT / "out/tum_raw.ply"
    if tum.exists():
        out.append(("TUM fr1/room", tum, 24.5, 1))  # the published example, a 5 x 5 m office
    apt = ROOT / "out/replica_apt0/ideal/plan_cloud.ply"
    if apt.exists():
        out.append(("Replica apt_0 (ideal)", apt, 51.8, 3))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    variants = [
        ("nearest wins (in the tree)", "nearest", 2.5),
        ("most overlap wins", "overlap", 2.5),
        ("most overlap, reach 1.0", "overlap", 1.0),
    ]
    todo = scenes()
    print(f"{len(todo)} scenes\n")
    header = "| scene | truth | " + " | ".join(v[0] for v in variants) + " |"
    print(header)
    print("|" + "---|" * (len(variants) + 2))
    results: dict = {}
    for name, path, truth_area, truth_rooms in todo:
        pc = PointCloud.load_ply(path)
        cells = []
        for _label, mode, reach in variants:
            tidy.snap_edges_to_walls = snapper(mode)
            try:
                plan = extract_floor_plan(pc, PlanOptions(room_snap_dist=reach)).plan
                area = sum(r.shapely.area for r in plan.rooms)
                cells.append(f"{area:.1f} m² ({(area - truth_area) / truth_area * 100:+.0f} %), {len(plan.rooms)} r, {len(plan.walls)} w")
                results.setdefault(name, {})[_label] = {"area": area, "rooms": len(plan.rooms), "walls": len(plan.walls)}
            except Exception as e:
                cells.append(f"failed: {type(e).__name__}")
            finally:
                tidy.snap_edges_to_walls = ORIGINAL
        print(f"| {name} | {truth_area:.1f} m² / {truth_rooms} r | " + " | ".join(cells) + " |")
    (ROOT / "out/planner_sweep.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
