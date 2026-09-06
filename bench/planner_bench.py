"""The planner on every scene at once: one command, seven rows, no network and no GPU.

Two rounds in a row a planner change that helped one scene quietly hurt another, and the
regression lived until someone re-ran the TUM by hand.  This replans clouds that are
already on disk and scores each against its own truth, so a change is judged on all of
them together.

Scenes:

- five ARKitScenes rooms — the clouds `levanta video` produced, the LiDAR mesh as truth,
  and the ARKit trajectory to place the plan in the mesh's frame;
- the TUM office — no mesh, so it is scored against the published example, which is what
  a regression there would break;
- the Replica flat with a *perfect* cloud (exact depth, exact poses): the planner's own
  ceiling, with no network error in the way.

Metrics per scene: wall recall and precision against the mesh (how much of the real wall
became a wall, and how much of what was drawn is wall), rooms found vs. real, doors found
vs. doorways, and total room area against the floor.

Usage:
    python bench/planner_bench.py                    # the table
    python bench/planner_bench.py --json out.json    # machine readable, for CI
    python bench/planner_bench.py --set room_snap_dist=1.0 min_wall_len=0.3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import read_traj, umeyama
from replica import floor_truth, load_mesh, wall_scores, wall_truth

ROOT = Path(__file__).resolve().parent.parent
ARKIT = Path("C:/Users/jhona/arkitscenes_data/raw/Validation")
REPLICA = Path("C:/Users/jhona/replica_data")

# what the published example shows; a change that moves these broke the TUM
TUM_REFERENCE = {"walls": 3, "rooms": 1, "openings": 1, "area_m2": 24.49, "wall_lengths": [5.80, 4.93, 4.07]}


def scene_list() -> list[dict]:
    out = []
    rows = json.loads((ROOT / "bench/results/arkitscenes_2026-09-05_round4.json").read_text(encoding="utf-8"))
    for r in rows:
        vid = r["video_id"]
        cloud = ROOT / "out/bench3" / vid / "noK" / "plan_cloud.ply"
        mesh = ARKIT / vid / f"{vid}_3dod_mesh.ply"
        if cloud.exists() and mesh.exists():
            out.append({"name": vid, "cloud": cloud, "mesh": mesh, "kind": "arkit", "traj": ARKIT / vid / "lowres_wide.traj", "index": cloud.parent / "frames" / "index.json"})
    tum = ROOT / "out/tum_raw.ply"
    if tum.exists():
        out.append({"name": "TUM fr1/room", "cloud": tum, "kind": "reference", "reference": TUM_REFERENCE})
    apt = ROOT / "out/replica_apt0/ideal/plan_cloud.ply"
    if apt.exists() and (REPLICA / "apartment_0/mesh.ply").exists():
        out.append({"name": "Replica apt_0 (perfect cloud)", "cloud": apt, "mesh": REPLICA / "apartment_0/mesh.ply", "kind": "replica", "poses": ROOT / "out/replica_apt0/walk_poses.json", "index": apt.parent / "frames" / "index.json"})
    return out


def truth_cameras(scene: dict, idx: list[dict]) -> np.ndarray | None:
    """Where the cameras really were, one per kept frame."""
    if scene["kind"] == "arkit":
        ts, centres = read_traj(scene["traj"])
        offs = json.loads((ROOT / "out/bench3/results.json").read_text(encoding="utf-8"))
        off = next((r["noK"].get("time_offset_s", 0.0) for r in offs if r["video_id"] == scene["name"]), 0.0)
        return centres[[int(np.argmin(np.abs(ts - (ts[0] + off + f["time_s"])))) for f in idx]]
    if scene["kind"] == "replica":
        meta = json.loads(scene["poses"].read_text(encoding="utf-8"))
        poses = [np.array(p) for p in meta["poses"]]
        return np.array([poses[min(round(f["time_s"]), len(poses) - 1)][:3, 3] for f in idx])
    return None


def run_scene(scene: dict, overrides: dict) -> dict:
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.scene import PointCloud

    pc = PointCloud.load_ply(scene["cloud"])
    res = extract_floor_plan(pc, PlanOptions(**overrides))
    plan = res.plan.label_openings()
    areas = [r.shapely.area for r in plan.rooms]
    row = {
        "scene": scene["name"],
        "walls": len(plan.walls),
        "rooms": len(plan.rooms),
        "doors": sum(1 for o in plan.openings if o.kind == "door"),
        "area_m2": float(sum(areas)),
    }
    if scene["kind"] == "reference":
        ref = scene["reference"]
        row.update({
            "truth_rooms": ref["rooms"], "truth_doors": ref["openings"], "truth_area_m2": ref["area_m2"],
            "area_error_pct": (row["area_m2"] - ref["area_m2"]) / ref["area_m2"] * 100.0,
            "walls_expected": ref["walls"],
            "wall_lengths": sorted((round(w.length, 2) for w in plan.walls), reverse=True),
        })
        return row
    mesh = load_mesh(scene["mesh"])
    truth = floor_truth(mesh)
    row.update({"truth_rooms": len(truth["rooms"]), "truth_doors": truth["doors"], "truth_area_m2": truth["area_m2"]})
    row["area_error_pct"] = (row["area_m2"] - truth["area_m2"]) / truth["area_m2"] * 100.0
    idx = json.loads(scene["index"].read_text(encoding="utf-8"))
    dst = truth_cameras(scene, idx)
    cams = res.cloud.cameras[:, :3, 3] if res.cloud.cameras is not None else None
    if dst is not None and cams is not None and len(cams) == len(dst) and len(cams) >= 5:
        s, R, t, rms = umeyama(cams, dst)
        row["camera_rms_m"] = rms
        walls = [{"a": w.a, "b": w.b, "thickness": w.thickness} for w in plan.walls]
        sc = wall_scores(walls, truth, wall_truth(mesh, truth), (s, R, t))
        row["wall_recall"] = sc["wall_recall"]
        row["wall_precision"] = sc["wall_precision"]
    return row


def fmt(rows: list[dict]) -> str:
    head = "| scene | truth: floor / rooms / doorways | walls | rooms | doors | area | wall recall | wall precision |"
    out = [head, "|" + "---|" * 8]
    for r in rows:
        recall = "—" if r.get("wall_recall") is None else f"{100 * r['wall_recall']:.0f} %"
        prec = "—" if r.get("wall_precision") is None else f"{100 * r['wall_precision']:.0f} %"
        exp = f" (ref {r['walls_expected']})" if "walls_expected" in r else ""
        out.append(
            f"| {r['scene']} | {r['truth_area_m2']:.1f} m² / {r['truth_rooms']} / {r['truth_doors']} "
            f"| {r['walls']}{exp} | {r['rooms']} | {r['doors']} | {r['area_m2']:.1f} m² ({r['area_error_pct']:+.0f} %) | {recall} | {prec} |"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--set", nargs="*", default=[], help="PlanOptions overrides, e.g. room_snap_dist=1.0")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    overrides: dict = {}
    for item in args.set:
        k, v = item.split("=", 1)
        overrides[k] = float(v) if "." in v or v.replace("-", "").isdigit() else v
        if v in ("True", "False"):
            overrides[k] = v == "True"
    rows = []
    for scene in scene_list():
        if args.only and scene["name"] not in args.only:
            continue
        row = run_scene(scene, overrides)
        rows.append(row)
        print(f"  {row['scene']}: {json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items() if k != 'scene'})}")
    print()
    print(fmt(rows))
    if args.json:
        args.json.write_text(json.dumps({"overrides": overrides, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
