"""Is the drift the network's geometry, or where its views are placed?

Rounds 4 and 5 left one question standing: the camera track ends 1.0 m from the truth over
a 35 m walk, and nothing that rearranged or refined the *poses* moved it.  On a rendered
walk both unknowns are available exactly — the pose of every frame and the depth of every
pixel — so the two can finally be separated:

1. **geometry**: the depth MapAnything predicts for a frame against the depth the renderer
   produced for it.  Reported per view as the median ratio (the scale it got) and the
   absolute relative error after that scale is divided out (the shape it got);
2. **placement**: the same frames reconstructed twice, once the normal way and once with
   every view's true pose handed to the network, then planned and measured the same way.

Thresholds written before running:

- if the depth's abs-rel error after scale is **<= 0.05**, the geometry is sound and the
  drift is a placement problem worth attacking;
- if it is **>= 0.10**, the geometry is the ceiling and no pose work can repair it;
- with true poses, **>= 2 of 3 rooms and total area within +-15 %** would mean placement
  was the binding constraint; anything near the 1 of 3 and -49 % of the normal run means
  it was not.

Needs a run of `bench/replica.py --save-depth` (frames and depth maps kept).

Usage: python bench/known_poses.py <replica_scene_dir> out/replica_apt0 [--max-views 24]
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


def depth_truth(render_dir: Path, step: int) -> np.ndarray | None:
    p = render_dir / f"depth_{step:05d}.npy"
    return np.load(p).astype(np.float32) if p.exists() else None


def compare_depth(pred: np.ndarray, mask: np.ndarray, true: np.ndarray) -> dict | None:
    """(median predicted/true, abs-rel error once that scale is divided out)."""
    import cv2

    if true.shape != pred.shape:
        true = cv2.resize(true, (pred.shape[1], pred.shape[0]), interpolation=cv2.INTER_NEAREST)
    ok = mask & (pred > 0.05) & (true > 0.05) & np.isfinite(true)
    if ok.sum() < 500:
        return None
    ratio = float(np.median(pred[ok] / true[ok]))
    rel = float(np.mean(np.abs(pred[ok] / ratio - true[ok]) / true[ok]))
    return {"scale": ratio, "abs_rel_after_scale": rel, "pixels": int(ok.sum())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("out", type=Path, help="a bench/replica.py output directory (walk_poses.json, render/, noK/frames)")
    ap.add_argument("--max-views", type=int, default=24)
    ap.add_argument("--overlap", type=int, default=4)
    ap.add_argument("--frames-from", default="noK", help="which earlier run's frame selection to reuse")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    from levanta.io.export import export_all
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.recon.mapanything import MapAnythingBackend
    from levanta.recon.rgbd import fuse_frames
    from levanta.scene import Camera, Frame

    meta = json.loads((args.out / "walk_poses.json").read_text(encoding="utf-8"))
    K_render = np.array(meta["K"])
    poses = [np.array(p) for p in meta["poses"]]
    render_dir = args.out / "render"
    run = args.out / "known_poses"
    idx_path = args.out / args.frames_from / "frames" / "index.json"
    if idx_path.exists():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        paths = [idx_path.parent / f["file"] for f in idx]
    else:  # pick the frames here, exactly as `levanta video` would
        from levanta.io.video import extract_frames

        kept = extract_frames(args.out / "walk.mp4", run / "frames", fps=1.0)
        idx = [{"file": k.path.name, "frame": k.index, "time_s": round(k.time_s, 2), "sharpness": round(k.sharpness, 1)} for k in kept]
        (run / "frames").mkdir(parents=True, exist_ok=True)
        (run / "frames" / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")
        paths = [k.path for k in kept]
    steps = [min(int(round(f["time_s"])), len(poses) - 1) for f in idx]
    print(f"{len(paths)} frames, {len(poses)} walk steps, render {render_dir.exists()}")

    import cv2

    w0 = cv2.imread(str(paths[0])).shape[1]
    scale_to_frame = w0 / (2 * K_render[0, 2])
    K_frame = K_render.copy()
    K_frame[:2] *= scale_to_frame

    truth = floor_truth(load_mesh(args.scene / "mesh.ply"))
    be = MapAnythingBackend(max_views=args.max_views, overlap=args.overlap)
    results: dict = {"frames": len(paths)}

    # -- 1. geometry: predicted depth against the renderer's depth --------------------------
    t0 = time.time()
    rows = []
    for a in range(0, len(paths), args.max_views):
        batch = paths[a : a + args.max_views]
        views = be.predict_views(batch)
        for k, v in enumerate(views):
            true = depth_truth(render_dir, steps[a + k])
            if true is None:
                continue
            r = compare_depth(v["depth"], v["mask"], true)
            if r:
                rows.append(r)
    if rows:
        sc = np.array([r["scale"] for r in rows])
        rel = np.array([r["abs_rel_after_scale"] for r in rows])
        results["depth"] = {
            "views": len(rows),
            "scale_median": float(np.median(sc)),
            "scale_p10": float(np.percentile(sc, 10)),
            "scale_p90": float(np.percentile(sc, 90)),
            "abs_rel_median": float(np.median(rel)),
            "abs_rel_mean": float(np.mean(rel)),
        }
        d = results["depth"]
        print(f"depth vs render truth ({len(rows)} views, {time.time() - t0:.0f} s): scale median {d['scale_median']:.2f} (p10 {d['scale_p10']:.2f}, p90 {d['scale_p90']:.2f}), abs-rel after scale median {d['abs_rel_median']:.3f} mean {d['abs_rel_mean']:.3f}")

    # -- 2. placement: the same frames with their true poses ---------------------------------
    run.mkdir(parents=True, exist_ok=True)
    (run / "frames").mkdir(exist_ok=True)
    (run / "frames" / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")
    t1 = time.time()
    solved: list[dict] = []
    for a in range(0, len(paths), args.max_views - args.overlap):
        batch = paths[a : a + args.max_views]
        if not batch:
            break
        known = [poses[steps[a + k]] for k in range(len(batch))]
        ks = [K_frame for _ in batch]
        views = be.predict_views(batch, intrinsics=ks, poses=known)
        for k in range(len(batch)):
            if a + k >= len(solved):
                solved.append(views[k])
        if a + len(batch) >= len(paths):
            break
    frames = []
    for k, v in enumerate(solved):
        depth = v["depth"].copy()
        depth[~v["mask"]] = 0.0
        h, w = depth.shape
        frames.append(Frame(image=v["image"], depth=depth, camera=Camera(K=v["K"], T=poses[steps[k]], width=w, height=h)))
    cloud = fuse_frames(frames, stride=2, voxel=0.02, depth_max=12.0, edge_rel=0.06)
    cloud.meta.update({"source": "mapanything", "views": len(frames), "chunks": 1, "known_poses": True})
    cloud.save_ply(run / "plan_cloud_recon.ply")
    print(f"{len(cloud):,} points from {len(frames)} views with true poses ({time.time() - t1:.0f} s)")
    res = extract_floor_plan(cloud, PlanOptions())
    res.cloud.save_ply(run / "plan_cloud.ply")
    for key in ("chunk_scales", "mask_fraction", "views"):
        if key in cloud.meta:
            res.plan.meta[key] = cloud.meta[key]
    export_all(res.plan.label_openings(), run, lang="en", stem="plan")
    r = evaluate(run, truth, poses, len(poses))
    results["known_poses"] = r
    print("known poses:", json.dumps({k: v for k, v in r.items() if k != "per_room"}))
    for m in r.get("per_room", []):
        print(f"   room {m['truth_room']}: {m['truth_m2']:.1f} m2 -> levanta {m['levanta_m2']:.1f} m2 ({m['area_error_pct']:+.0f} %)")
    (args.out / "known_poses.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
