"""How much of the walk do you actually have to record?

Round 10 went looking for a planner ceiling and found a coverage one instead: the same flat,
the same exact depth and exact poses, planned from the first 48 of the walk's 116 views,
came out 21 % under the truth, and from all 116 it comes out over it.  Forty points from a
variable nobody had characterised, and it is the one variable a person holds in their hand
before they start: how long they walk.

So this sweeps *prefixes* of the walk, which is what a shorter recording is.  Sampling the
same path more sparsely is a different question (frame rate, not duration) and is not what
the capture guide has to answer.

Fusion is `stride 4` and `voxel 0.03`.  Three numbers have been quoted for "exact depth on
this flat" and they are three different things, so here they are with their labels:

| what was fused | area |
|---|---|
| the published ideal cloud: **58 views, every second one of the walk** | **+19 %** |
| all 116 views, voxel 0.03 | +23 % |
| all 116 views, voxel 0.02 | +22 % |

The first is the one the bench and the README quote, and it is a *subsample* of the whole
walk, not a prefix.  ``--every`` reproduces it; the prefixes answer the other question.

**Written before the first run.** The prediction is that the *room count* saturates early,
around 60 views, and that the *per-room error does not flatten at all* by 116, because what
binds it is how much floor was seen (36 % of the flat at 116 views) and every extra view
adds some.  "Flattens" is defined as the mean per-room absolute error moving less than 10
points from the previous step.  If it does flatten by 60 the capture guide can name a
number; if it does not, the guide has to say that more is always better, which is a worse
answer and still has to be published.

Usage:
    python bench/coverage_sweep.py out/replica_apt0 C:/Users/jhona/replica_data/apartment_0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import umeyama
from planner_bench import match_rooms
from replica import CELL, floor_truth, load_mesh

TRUTH_FLOOR_M2 = 51.8


def seen_floor_of_the_flat(xyz: np.ndarray, sim, truth: dict) -> float:
    """Share of the real floor that the cloud actually put points on, at 10 cm."""
    from scipy import ndimage

    s, R, t = sim
    up, hz, lo, filled = truth["up"], truth["horiz"], truth["lo"], truth["filled"]
    w = s * (R @ xyz.T).T + t
    near = np.abs(w[:, up] - truth["floor_h"]) < 0.10
    iy = ((w[near, hz[0]] - lo[0]) / CELL).astype(int)
    ix = ((w[near, hz[1]] - lo[1]) / CELL).astype(int)
    ok = (iy >= 0) & (ix >= 0) & (iy < filled.shape[0]) & (ix < filled.shape[1])
    m = np.zeros_like(filled)
    m[iy[ok], ix[ok]] = True
    r = max(1, round(0.10 / CELL))
    m = ndimage.binary_dilation(m, iterations=r) & filled
    return float(m.sum() / max(filled.sum(), 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path, help="a bench/replica.py directory rendered with --save-depth")
    ap.add_argument("scene", type=Path, help="the Replica scene directory, for mesh.ply")
    ap.add_argument("--views", type=int, nargs="*", default=[20, 40, 60, 80, 116])
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--voxel", type=float, default=0.03)
    ap.add_argument("--every", type=int, default=1, help="take every N-th view of the WHOLE walk instead of a prefix; --every 2 reproduces the published cloud")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    import cv2

    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.recon.rgbd import fuse_frames
    from levanta.scene import Camera, Frame

    meta = json.loads((args.out / "walk_poses.json").read_text(encoding="utf-8"))
    K = np.array(meta["K"], dtype=np.float64)
    poses = [np.array(p, dtype=np.float64) for p in meta["poses"]]
    render = args.out / "render"
    truth = floor_truth(load_mesh(args.scene / "mesh.ply"))

    rows = []
    for n in args.views:
        n = min(n, len(poses))
        keep = list(range(0, len(poses), args.every))[:n] if args.every > 1 else list(range(n))
        frames = []
        for k in keep:
            depth = np.load(render / f"depth_{k:05d}.npy").astype(np.float32)
            depth[~np.isfinite(depth)] = 0.0
            img = cv2.imread(str(render / f"frame_{k:05d}.png"))
            img = img[:, :, ::-1].copy() if img is not None else np.zeros((*depth.shape, 3), np.uint8)
            h, w = depth.shape
            frames.append(Frame(image=img, depth=depth, camera=Camera(K=K, T=poses[k], width=w, height=h)))
        cloud = fuse_frames(frames, stride=args.stride, voxel=args.voxel, depth_max=12.0, edge_rel=0.06)
        res = extract_floor_plan(cloud, PlanOptions())
        plan = res.plan.label_openings()
        s, R, t, rms = umeyama(res.cloud.cameras[:, :3, 3], np.array([poses[k][:3, 3] for k in keep]))
        m = match_rooms(plan, truth, (s, R, t))
        errs = [x["error_pct"] for x in m["per_room"] if x["error_pct"] is not None]
        total = float(sum(r.area for r in plan.rooms))
        row = {
            "views": n,
            "walk_m": None,
            "rooms": len(plan.rooms),
            "matched": m["rooms_matched"],
            "walls": len(plan.walls),
            "area_m2": total,
            "area_error_pct": 100.0 * (total - TRUTH_FLOOR_M2) / TRUTH_FLOOR_M2,
            "per_room_pct": errs,
            "mean_abs_per_room_pct": float(np.mean(np.abs(errs))) if errs else None,
            # one blob credited against two true rooms scores like two good rooms; at 60
            # views that produced a mean error of 11 % from a single fused room, so the
            # mean is not readable without this column beside it
            "fused": m["rooms_fused"],
            "missed": m["rooms_missed"],
            "seen_floor_pct": 100.0 * seen_floor_of_the_flat(np.asarray(res.cloud.xyz), (s, R, t), truth),
            "camera_rms_m": rms,
        }
        path = np.array([poses[k][:3, 3] for k in keep])
        row["walk_m"] = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
        rows.append(row)
        errs_txt = ", ".join(f"{e:+.0f} %" for e in errs) or "none matched"
        print(f"  {n:3d} views ({row['walk_m']:5.1f} m walked): {len(plan.rooms)} rooms, matched {m['rooms_matched']}/3, "
              f"{total:5.1f} m2 ({row['area_error_pct']:+.0f} %), per room [{errs_txt}], "
              f"mean |e| {row['mean_abs_per_room_pct'] or float('nan'):5.1f} %, fused {m['rooms_fused']}, floor seen {row['seen_floor_pct']:.0f} %")

    print()
    print("| views | walked | rooms found | fused | area | per-room error | mean |e| | floor seen |")
    print("|" + "---|" * 8)
    for r in rows:
        per = ", ".join(f"{e:+.0f} %" for e in r["per_room_pct"]) or "—"
        mean = "—" if r["mean_abs_per_room_pct"] is None else f"{r['mean_abs_per_room_pct']:.0f} %"
        print(f"| {r['views']} | {r['walk_m']:.0f} m | {r['matched']} of 3 | {r['fused']} | {r['area_m2']:.1f} m² ({r['area_error_pct']:+.0f} %) | {per} | {mean} | {r['seen_floor_pct']:.0f} % |")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
