"""The planner alone: perfect depth, perfect poses, no network at all.

The apartment benchmark blames something for one room where there are three, but not yet
*which* half of the pipeline.  The rendered walk carries the exact depth of every pixel and
the exact pose of every frame, so the planner can be fed a flawless cloud and judged on
its own.  No GPU: the depth maps are on disk and the fusion is numpy.

Thresholds written before running (`apartment_0`: 51.8 m² of floor, three rooms, two
doorways):

- **3 rooms of 3** and **both doorways** — anything less is the planner's own limit;
- total area within **±10 %**, per room within **±15 %**;
- if all three hold, every error the benchmark reports is the network's.

Usage: python bench/ideal_input.py <replica_scene_dir> out/replica_apt0 [--stride 4]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from replica import evaluate, floor_truth, load_mesh


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("out", type=Path, help="a bench/replica.py output directory rendered with --save-depth")
    ap.add_argument("--stride", type=int, default=4, help="keep one pixel every N in each direction")
    ap.add_argument("--voxel", type=float, default=0.03)
    ap.add_argument("--every", type=int, default=1, help="use every N-th walk step")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    import cv2

    from levanta.io.export import export_all
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.recon.rgbd import fuse_frames
    from levanta.scene import Camera, Frame

    meta = json.loads((args.out / "walk_poses.json").read_text(encoding="utf-8"))
    K = np.array(meta["K"])
    poses = [np.array(p) for p in meta["poses"]]
    render = args.out / "render"
    truth = floor_truth(load_mesh(args.scene / "mesh.ply"))
    print(f"truth: floor {truth['area_m2']:.1f} m2, {len(truth['rooms'])} rooms {[round(r['territory_m2'], 1) for r in truth['rooms']]}, {truth['doors']} doorways")

    t0 = time.time()
    frames, idx = [], []
    for k in range(0, len(poses), args.every):
        dpath = render / f"depth_{k:05d}.npy"
        ipath = render / f"frame_{k:05d}.png"
        if not dpath.exists():
            continue
        depth = np.load(dpath).astype(np.float32)
        depth[~np.isfinite(depth)] = 0.0
        img = cv2.imread(str(ipath))[:, :, ::-1].copy() if ipath.exists() else np.zeros((*depth.shape, 3), np.uint8)
        h, w = depth.shape
        frames.append(Frame(image=img, depth=depth, camera=Camera(K=K, T=poses[k], width=w, height=h)))
        idx.append({"file": ipath.name, "frame": k, "time_s": float(k), "sharpness": 0.0})
    print(f"{len(frames)} frames with exact depth ({time.time() - t0:.0f} s)")

    t1 = time.time()
    cloud = fuse_frames(frames, stride=args.stride, voxel=args.voxel, depth_max=12.0, edge_rel=0.06)
    cloud.meta.update({"source": "render", "views": len(frames)})
    print(f"{len(cloud):,} points fused ({time.time() - t1:.0f} s); bbox {cloud.xyz.min(0).round(2)} .. {cloud.xyz.max(0).round(2)}")

    run = args.out / "ideal"
    run.mkdir(parents=True, exist_ok=True)
    (run / "frames").mkdir(exist_ok=True)
    (run / "frames" / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")
    t2 = time.time()
    res = extract_floor_plan(cloud, PlanOptions())
    res.cloud.save_ply(run / "plan_cloud.ply")
    plan = res.plan.label_openings()
    print(f"plan ({time.time() - t2:.0f} s): {len(plan.walls)} walls, {len(plan.rooms)} rooms, {len(plan.openings)} openings")
    export_all(plan, run, lang="en", stem="plan")
    from levanta.plan.debug import render_debug

    render_debug(res, path=run / "plan_debug.png")
    r = evaluate(run, truth, poses, len(poses))
    print("ideal input:", json.dumps({k: v for k, v in r.items() if k != "per_room"}))
    for m in r.get("per_room", []):
        print(f"   room {m['truth_room']}: {m['truth_m2']:.1f} m2 -> planner {m['levanta_m2']:.1f} m2 ({m['area_error_pct']:+.0f} %)")
    ok_rooms = r.get("rooms_levanta") == r.get("rooms_truth")
    ok_doors = r.get("doors_levanta", 0) >= r.get("doorways_truth", 0)
    ok_area = abs(r.get("area_total_error_pct", 100.0)) <= 10.0
    print(f"\nthresholds: rooms {'ok' if ok_rooms else 'FAILED'}, doorways {'ok' if ok_doors else 'FAILED'}, total area {'ok' if ok_area else 'FAILED'}")
    (args.out / "ideal.json").write_text(json.dumps(r, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
