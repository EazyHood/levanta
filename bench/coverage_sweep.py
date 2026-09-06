"""How much of the walk do you actually have to record?

Round 10 went looking for a planner ceiling and found a coverage one instead: the same flat,
the same exact depth and exact poses, planned from the first 48 of the walk's 116 views,
came out 21 % under the truth, and from all 116 it comes out over it.  Forty points from a
variable nobody had characterised, and it is the one variable a person holds in their hand
before they start: how long they walk.

There are two questions inside that, and they need different sweeps, because a prefix of
the walk is not a thinner sample of it:

- **extent** (``--mode prefix``, the default): the first N views.  Every row walks a
  different distance and sees a different part of the flat, so this answers "did I go
  everywhere", and its answer is already in: until the whole flat is walked, the rooms do
  not appear.  It is not monotonic and it should not be read as a density curve, because at
  60 views the camera is halfway through the second room, which is the worst state there is.
- **density** (``--mode density``): N views spread evenly over the *whole* walk, so every
  row covers the same 24 metres and only the spacing changes.  This is the one that says
  whether a person has to walk more slowly.

Fusion is `stride 4` and `voxel 0.03`.  Three numbers have been quoted for "exact depth on
this flat" and they are three different things, so here they are with their labels:

| what was fused | area |
|---|---|
| the published ideal cloud: **58 views, every second one of the walk** | **+19 %** |
| all 116 views, voxel 0.03 | +23 % |
| all 116 views, voxel 0.02 | +22 % |

The first is the one the bench and the README quote, and it is a *subsample* of the whole
walk, not a prefix.  ``--every`` reproduces it; the prefixes answer the other question.

**Written before the prefix run, and wrong in both halves.**  The prediction was that the
room count saturates near 60 views and the per-room error keeps falling to 116.  Rooms found
went 1, 2, 1, 2, 3, and the error went 56, 58, 11, 117, 85 %, where the 11 % was one fused
blob credited against two similar rooms.  Extent is not a curve you can read that way.

**Written before the density run.**  With the whole walk covered at every density, the
prediction is that it *does* flatten: every row visits all three rooms, so the room count
should be 2 or 3 from 20 views up, and the mean per-room error should move less than 20
points between 58 and 116.  If it flattens, the capture guide says walk the whole house at a
normal pace; if it keeps improving to 116, the guide says record twice as much as you think.

Usage:
    python bench/coverage_sweep.py out/replica_apt0 <replica>/apartment_0
    python bench/coverage_sweep.py out/replica_apt0 <replica>/apartment_0 --mode density
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
    ap.add_argument("--mode", choices=("prefix", "density"), default="prefix", help="prefix: the first N views (extent).  density: N views spread over the whole walk, same 24 m every row")
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
        if args.mode == "density":
            keep = sorted(set(np.linspace(0, len(poses) - 1, n).round().astype(int).tolist()))
        elif args.every > 1:
            keep = list(range(0, len(poses), args.every))[:n]
        else:
            keep = list(range(n))
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
