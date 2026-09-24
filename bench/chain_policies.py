"""Can the scale be fixed once for the whole walk, instead of handed down chunk by chunk?

The fps sweep (bench/results/fps_sweep_2026-09-24.md) found the scale error growing with the
number of 24-view chunks, 3 % at 9 and 123 % at 36 on the same walk, and the links drifting
one way (27 of 35 shrinking at 4 fps).  Longer chunks would only be fewer links in the same
chain.  The question the review left is whether the chain can go.

One GPU pass per fps answers it without a new walk: every chunk is solved **on its own** (no
poses of the previous chunk fed in) and kept raw, in its own frame, before any alignment
(`levanta video --independent-chunks --keep-chunks`).  Then the same raw chunks are put
together on the CPU three ways and each result goes through the planner and the ARKitScenes
evaluation:

1. ``chained``: each chunk scaled to meet the one before, as levanta does today (but without
   the poses fed in, which is the second way today's chain inherits);
2. ``own_scale``: each chunk keeps the scale the network gave it, and is only turned and moved
   onto the one before;
3. ``joint``: the log-scales that minimise the links' disagreement plus the chunks' departure
   from their own network scale, weighted equally (lambda = 1), solved once for the walk.

The rows labelled ``today`` are the sweep's own runs, poses fed in, for reference.

Thresholds written before the first run: a policy **holds the scale** if, on the 36-chunk walk
(41069021 at 4 fps), its scale is within ±15 % of the truth (today 0.45, i.e. the plan 2.2
times too big) and its floor IoU is at least 0.50 (today 0.16), while on the 9-chunk walk
(1 fps) its IoU is no more than 0.05 below today's 0.65.  If none holds, the length ceiling
is real and the warning at 9 chunks stays its statement.

Usage:
    python bench/chain_policies.py C:/Users/jhona/arkitscenes_data/raw/Validation out/chain_exp          # GPU pass when idle, then recompose
    python bench/chain_policies.py C:/Users/jhona/arkitscenes_data/raw/Validation out/chain_exp --recompose-only
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

SCENE = "41069021"
FPS = (1.0, 4.0)
POLICIES = ("chained", "own_scale", "joint")
LAMBDA = 1.0


def load_chunks(d: Path) -> list[dict]:
    out = []
    for p in sorted(d.glob("chunk_*.npz")):
        z = np.load(p)
        out.append({k: z[k] for k in z.files})
    if not out:
        raise FileNotFoundError(f"no chunk_*.npz under {d}")
    return out


def link_ratio(prev: dict, cur: dict) -> float:
    """What the chunk before says about the shared frames' depth over what this chunk says:
    the raw-to-raw form of the ratio `align_chunk` takes (median per view, median of views)."""
    pos = {int(i): j for j, i in enumerate(prev["idx"])}
    ratios = []
    for j in range(int(cur["shared"])):
        i = int(cur["idx"][j])
        if i not in pos:
            continue
        dp = prev["depth"][pos[i]].astype(np.float32)
        dn = cur["depth"][j].astype(np.float32)
        m = prev["mask"][pos[i]] & cur["mask"][j] & (dp > 0.05) & (dn > 0.05)
        if m.sum() >= 200:
            ratios.append(float(np.median(dp[m] / dn[m])))
    return float(np.median(ratios)) if ratios else 1.0


def log_scales(chunks: list[dict], policy: str, lam: float = LAMBDA) -> np.ndarray:
    """One log-scale per chunk, relative to the network's own metric for that chunk."""
    n = len(chunks)
    links = np.array([math.log(link_ratio(chunks[k - 1], chunks[k])) for k in range(1, n)])
    if policy == "chained":
        return np.concatenate([[0.0], np.cumsum(links)])
    if policy == "own_scale":
        return np.zeros(n)
    if policy == "joint":
        # minimise sum_k (x_k - x_{k-1} - l_k)^2 + lam * sum_k x_k^2 : a tridiagonal system
        A = lam * np.eye(n)
        b = np.zeros(n)
        for k in range(1, n):
            A[k, k] += 1.0
            A[k - 1, k - 1] += 1.0
            A[k, k - 1] -= 1.0
            A[k - 1, k] -= 1.0
            b[k] += links[k - 1]
            b[k - 1] -= links[k - 1]
        return np.linalg.solve(A, b)
    raise ValueError(policy)


def place(chunks: list[dict], x: np.ndarray) -> dict[int, dict]:
    """Every frame in one world frame: chunk k scaled by exp(x_k), turned by the rotation its
    shared frames need, moved so their centres meet.  A frame keeps the first chunk's view."""
    from levanta.recon.mapanything import Similarity, align_similarity

    solved: dict[int, dict] = {}
    for k, c in enumerate(chunks):
        s = float(math.exp(x[k]))
        if k == 0:
            sim = Similarity(s, np.eye(3), np.zeros(3))
        else:
            sh = [j for j in range(int(c["shared"])) if int(c["idx"][j]) in solved]
            new_T = [c["T"][j] for j in sh]
            old_T = [solved[int(c["idx"][j])]["T"] for j in sh]
            R = align_similarity(new_T, old_T).R
            cs = np.array([T[:3, 3] for T in new_T])
            cd = np.array([T[:3, 3] for T in old_T])
            sim = Similarity(s, R, (cd - s * (R @ cs.T).T).mean(axis=0))
        for j, i in enumerate(c["idx"]):
            i = int(i)
            if i in solved:
                continue
            solved[i] = {"T": sim.apply(c["T"][j]), "depth": c["depth"][j].astype(np.float32) * s, "mask": c["mask"][j], "K": c["K"][j]}
    return solved


def plan_and_score(solved: dict[int, dict], x: np.ndarray, source_run: Path, run: Path, scene: Path, truth: dict) -> dict:
    from arkitscenes import evaluate

    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.recon.mapanything import is_flat_picture
    from levanta.recon.rgbd import fuse_frames
    from levanta.scene import Camera, Frame

    run.mkdir(parents=True, exist_ok=True)
    (run / "frames").mkdir(exist_ok=True)
    shutil.copy2(source_run / "frames" / "index.json", run / "frames" / "index.json")
    frames = []
    for i in sorted(solved):
        v = solved[i]
        depth = v["depth"].copy()
        depth[~v["mask"]] = 0.0
        if is_flat_picture(depth, v["K"]):
            depth[:] = 0.0
        h, w = depth.shape
        frames.append(Frame(image=None, depth=depth, camera=Camera(K=v["K"], T=v["T"], width=w, height=h)))
    # the backend's own fusion settings (MapAnythingBackend defaults, as `levanta video` uses them)
    cloud = fuse_frames(frames, stride=2, voxel=0.02, depth_max=12.0, edge_rel=0.06)
    links = [float(math.exp(x[k] - x[k - 1])) for k in range(1, len(x))]
    cloud.meta.update({"source": "mapanything", "views": len(frames), "chunks": len(x), "chunk_scales": links,
                       "mask_fraction": float(np.median([solved[i]["mask"].mean() for i in solved]))})
    res = extract_floor_plan(cloud, PlanOptions())
    res.cloud.save_ply(run / "plan_cloud.ply")
    res.plan.label_openings().to_json(run / "plan.json")
    r = evaluate(scene, run.parent, truth, run)
    r["composed_spread"] = float(math.exp(x.max() - x.min()))
    return r


def gpu_pass(scenes_dir: Path, out: Path, fps: float) -> dict:
    """levanta on the scene with independent, kept chunks, only while nobody plays."""
    from fps_sweep import interpreter, supervise
    from when_idle import game_open, wait_until_idle

    run_out = out / f"fps_{fps:g}"
    run_out.mkdir(parents=True, exist_ok=True)
    cmd = [interpreter(), str(HERE / "arkitscenes.py"), str(scenes_dir), str(run_out), "--only", SCENE, "--runs", "noK", "--fps", f"{fps:g}", "--independent-chunks"]
    record = run_out / "timing.json"
    with (out / "chain_policies.log").open("a", encoding="utf-8") as log:
        while True:
            wait_until_idle(log)
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} idle, running fps {fps:g}\n")
            log.flush()
            record.write_text(json.dumps({"fps": fps, "started": time.time(), "cmd": cmd}), encoding="utf-8")
            rec = supervise(cmd, run_out / "sweep.log", should_stop=game_open)
            record.write_text(json.dumps({"fps": fps, "cmd": cmd, **rec}), encoding="utf-8")
            if not rec.get("stopped"):
                break
            log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} stopped: {rec['stopped']} opened; waiting to retry\n")
            log.flush()
        log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} rc {rec['rc']} in {rec['seconds']:.0f} s\n")
    return rec


def main() -> None:
    from area_report import area_with_scale
    from arkitscenes import floor_truth, read_ply

    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--recompose-only", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    scene = args.scenes_dir / SCENE
    truth = floor_truth(*read_ply(scene / f"{SCENE}_3dod_mesh.ply"))
    rows = []
    for fps in FPS:
        run_out = args.out / f"fps_{fps:g}"
        if not args.recompose_only:
            rec = gpu_pass(args.scenes_dir, args.out, fps)
            if rec.get("rc") != 0:
                print(f"fps {fps:g}: the GPU pass failed ({rec.get('rc')}); see {run_out / 'sweep.log'}")
                continue
        source = run_out / SCENE / "noK"
        chunks = load_chunks(source / "chunks")
        assert all(int(c["fed_poses"]) == 0 for c in chunks), "these chunks were solved with poses fed in"
        today = next((r["noK"] for r in json.loads((ROOT / f"out/fps_sweep/fps_{fps:g}/results.json").read_text(encoding="utf-8")) if r["video_id"] == SCENE), None)
        if today:
            rows.append({"fps": fps, "policy": "today (poses fed in)", "chunks": len(chunks), **today})
        for policy in POLICIES:
            x = log_scales(chunks, policy)
            r = plan_and_score(place(chunks, x), x, source, args.out / f"fps_{fps:g}" / f"recomposed_{policy}", scene, truth)
            rows.append({"fps": fps, "policy": policy, "chunks": len(chunks), **r})
            print(f"fps {fps:g} {policy}: scale {r.get('scale_factor')}, IoU {r.get('floor_iou')}, rooms {r.get('levanta_rooms')}, spread {r['composed_spread']:.3g}")
    (args.out / "chain_policies.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    dash = "\u2014"
    fmt = lambda v, f="{:.2f}": dash if v is None else f.format(v)  # noqa: E731
    lines = ["| fps | chunks | policy | area error | floor IoU | rooms | camera RMS | chunks apart in size |", "|" + "---|" * 8]
    for r in rows:
        lines.append(f"| {r['fps']:g} | {r['chunks']} | {r['policy']} | {area_with_scale(r.get('area_error_pct'), r.get('scale_factor'))} | {fmt(r.get('floor_iou'))} "
                     f"| {r.get('levanta_rooms', dash)} | {fmt(r.get('traj_rms_m'))} m | {fmt(r.get('composed_spread'), '{:.3g}')} |")
    (args.out / "chain_policies.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
