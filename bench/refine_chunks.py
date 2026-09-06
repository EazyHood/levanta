"""Straighten a chunk: refine every view's pose against the chunk's own fused surface.

The bench showed the drift lives *inside* a chunk of 24 views (RMS 0.12-0.56 m against
ARKit, per-chunk scale 0.65-1.32 against the truth) and not between chunks.  Here each
chunk is fused into a TSDF from the network's depths (Open3D), every view is
registered to the fused surface with point-to-plane ICP, the poses are updated, and the
fusion repeated; two or three rounds.  The ARKit trajectory is used only to *measure*,
never as input.

Thresholds written before running (per chunk, Umeyama against ARKit): RMS from 0.12-0.56
to <= 0.25 m on 4 of 5 scenes (median over the scene's chunks), and the spread of the
per-chunk scales (max/min over a scene) below 1.3x.

Usage: python bench/refine_chunks.py <scenes_dir> <bench_out_dir> [--iters 3] [--voxel 0.03]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import read_traj, umeyama


def load_views(views_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((views_dir / "views.json").read_text(encoding="utf-8"))
    views = []
    for e in meta["views"]:
        z = np.load(views_dir / e["npz"])
        views.append({"i": e["i"], "depth": z["depth"].astype(np.float32), "mask": z["mask"], "K": z["K"], "T": z["T"]})
    return meta, views


def chunk_ranges(n: int, max_views: int, overlap: int) -> list[tuple[int, int]]:
    out = []
    a = 0
    while a < n:
        b = min(a + max_views, n)
        out.append((a, b))
        if b >= n:
            break
        a = b - overlap
    return out


def _cloud_of(view: dict, stride: int = 2):
    import open3d as o3d

    d = view["depth"].copy()
    d[~view["mask"]] = 0.0
    h, w = d.shape
    K = view["K"]
    vv, uu = np.mgrid[0:h:stride, 0:w:stride]
    z = d[::stride, ::stride]
    ok = z > 0.05
    x = (uu[ok] - K[0, 2]) / K[0, 0] * z[ok]
    y = (vv[ok] - K[1, 2]) / K[1, 1] * z[ok]
    pts = np.c_[x, y, z[ok]].astype(np.float64)
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    return pc


def fuse(views: list[dict], voxel: float):
    import open3d as o3d

    vol = o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=voxel, sdf_trunc=4 * voxel, color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
    for v in views:
        d = v["depth"].copy()
        d[~v["mask"]] = 0.0
        h, w = d.shape
        K = v["K"]
        intr = o3d.camera.PinholeCameraIntrinsic(w, h, K[0, 0], K[1, 1], K[0, 2], K[1, 2])
        depth = o3d.geometry.Image((d * 1000.0).astype(np.uint16))
        color = o3d.geometry.Image(np.zeros((h, w, 3), np.uint8))
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(color, depth, depth_scale=1000.0, depth_trunc=12.0, convert_rgb_to_intensity=False)
        vol.integrate(rgbd, intr, np.linalg.inv(v["T"]))  # extrinsic = world -> camera
    pc = vol.extract_point_cloud()
    pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3 * voxel, max_nn=30))
    return pc


def refine_chunk(views: list[dict], iters: int, voxel: float) -> list[dict]:
    import open3d as o3d

    cur = [dict(v) for v in views]
    for _ in range(iters):
        surface = fuse(cur, voxel)
        if len(surface.points) < 1000:
            break
        for v in cur:
            src = _cloud_of(v)
            if len(src.points) < 200:
                continue
            reg = o3d.pipelines.registration.registration_icp(
                src, surface, max_correspondence_distance=4 * voxel, init=v["T"],
                estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                criteria=o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=30),
            )
            if reg.fitness > 0.3:
                v["T"] = reg.transformation.copy()
    return cur


def per_chunk_rms(views: list[dict], ranges, dst: np.ndarray) -> list[tuple[float, float]]:
    out = []
    for a, b in ranges:
        src = np.array([views[i]["T"][:3, 3] for i in range(a, b)])
        if len(src) >= 5:
            s, _, _, rms = umeyama(src, dst[a:b])
            out.append((rms, s))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("bench_out", type=Path)
    ap.add_argument("--run", default="noK")
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--voxel", type=float, default=0.03)
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    results = {r["video_id"]: r for r in json.loads((args.bench_out / "results.json").read_text(encoding="utf-8"))}
    summary = []
    for vid, r in results.items():
        if args.only and vid not in args.only:
            continue
        run = args.bench_out / vid / args.run
        if not (run / "views" / "views.json").exists():
            print(f"{vid}: no views dumped, skipped")
            continue
        meta, views = load_views(run / "views")
        idx = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
        ts, C = read_traj(args.scenes_dir / vid / "lowres_wide.traj")
        off = r[args.run]["time_offset_s"]
        dst = C[[int(np.argmin(np.abs(ts - (ts[0] + off + f["time_s"])))) for f in idx]]
        ranges = chunk_ranges(len(views), meta["max_views"], meta["overlap"])
        before = per_chunk_rms(views, ranges, dst)
        refined = []
        for a, b in ranges:
            refined.append(refine_chunk(views[a:b], args.iters, args.voxel))
        # stitch: every chunk's refined poses replace its views (shared views take the later chunk)
        stitched = [dict(v) for v in views]
        for (a, _b), ch in zip(ranges, refined, strict=True):
            for k, v in enumerate(ch):
                stitched[a + k]["T"] = v["T"]
        after = per_chunk_rms(stitched, ranges, dst)
        s_all_b, _, _, rms_all_b = umeyama(np.array([v["T"][:3, 3] for v in views]), dst)
        s_all_a, _, _, rms_all_a = umeyama(np.array([v["T"][:3, 3] for v in stitched]), dst)
        med_b, med_a = float(np.median([x[0] for x in before])), float(np.median([x[0] for x in after]))
        spr_b = max(x[1] for x in before) / min(x[1] for x in before)
        spr_a = max(x[1] for x in after) / min(x[1] for x in after)
        print(f"{vid}: chunks {len(ranges)} | per-chunk RMS median {med_b:.2f} -> {med_a:.2f} m | scale spread {spr_b:.2f}x -> {spr_a:.2f}x | whole walk RMS {rms_all_b:.2f} -> {rms_all_a:.2f} m (scale {s_all_b:.2f} -> {s_all_a:.2f})")
        print("   per chunk before:", [(round(a, 2), round(s, 2)) for a, s in before])
        print("   per chunk after: ", [(round(a, 2), round(s, 2)) for a, s in after])
        summary.append({"video_id": vid, "chunks": len(ranges), "rms_median_before": med_b, "rms_median_after": med_a, "spread_before": spr_b, "spread_after": spr_a, "walk_rms_before": rms_all_b, "walk_rms_after": rms_all_a})
    (args.bench_out / f"refine_{args.run}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    ok_rms = sum(1 for s in summary if s["rms_median_after"] <= 0.25)
    ok_spr = sum(1 for s in summary if s["spread_after"] < 1.3)
    print(f"\nthreshold: per-chunk RMS median <= 0.25 m on {ok_rms} of {len(summary)}; scale spread < 1.3x on {ok_spr} of {len(summary)}")


if __name__ == "__main__":
    main()
