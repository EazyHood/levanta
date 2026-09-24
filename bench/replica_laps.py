"""Does a long chain of sound chunks hold the scale?  The same flat, one lap against three.

The fps sweep could not answer it: raising the fps lengthened the chain and shortened every
chunk at once, and the chain experiment then showed six-second chunks getting their own size
wrong (median 0.69, 0.20-1.23) while the 23-second chunks of the default did not (median
0.93).  The question a user's long take asks, many chunks of the default length, was never
measured: the longest walk with ground truth on disk is 9 chunks.

**Design, written and committed before any video was built or any run started.**

- Scene: Replica ``apartment_0``, the walk of round 5 (116 steps, a frame per step, rendered
  frames and their exact depth already on disk under ``out/replica_apt0/render``).
- Walk A, **one lap**: the 116 frames in order.  Walk B, **three laps**: there, back and there
  again with the same frames (the second lap in reverse order, no frame repeated at the turns),
  346 frames.  Every chunk has the same kind of motion and the same 24 views; only the length of
  the chain changes, 6 chunks against 18 before any frame is filtered.
- Both through `levanta video` exactly as a user runs it: 1 fps, 24 views per chunk, 4 shared,
  no focal length given.  Scored against the mesh: scale (cameras against the exact poses),
  floor IoU (the plan's rooms in the mesh's frame against the true floor), area with its scale,
  rooms, camera error, and how far apart in size the chain's chunks ended up.

**The rule**: at three laps, scale within ±15 % of the truth, and floor IoU no more than 0.05
below the IoU at one lap.

- If it holds, a chain of sound chunks keeps its scale at least to that length, and the "not
  measured" of `levanta check` past 9 chunks becomes "measured up to N chunks on a rendered
  flat".
- If it does not, the length ceiling exists with sound chunks too, and the report says so with
  both rows side by side.

Beside the verdict, and not part of it: the same two walks with every chunk solved on its own
and kept raw (``--independent-chunks --keep-chunks``), for each chunk's own scale measured two
ways, by its cameras against the exact poses and by its depth against the exact rendered depth
(median of predicted over true per view), which does not depend on how far the camera moved.

**What this cannot say.**  Replica is synthesis: flat shading, no motion blur, perfect
exposure, and here the second and third laps show the network exactly the same pictures again,
which no real walk does.  Holding the scale here is necessary for a phone video, not
sufficient.

Every GPU step waits until the card is free and stops if a game opens, as the sweep did.

Usage:
    python bench/replica_laps.py                 # build the videos, run, score, verdict
    python bench/replica_laps.py --score-only    # score what is on disk
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

SCENE_DIR = Path("C:/Users/jhona/replica_data/apartment_0")
SOURCE = ROOT / "out" / "replica_apt0"  # render/ (frames and exact depth), walk_poses.json
LAPS = {"one_lap": 1, "three_laps": 3}
SCALE_TOL = 0.15
IOU_DROP = 0.05


def lap_sequence(n: int, laps: int) -> list[int]:
    """Frame order for ``laps`` laps of an ``n``-frame walk: there, back, there, with no frame
    shown twice in a row at a turn."""
    seq = list(range(n))
    for lap in range(1, laps):
        seq += list(range(n - 2, -1, -1)) if lap % 2 == 1 else list(range(1, n))
    return seq


def holds(one: dict, three: dict) -> tuple[bool, list[str]]:
    """The rule in the module docstring, written before any run."""
    why = []
    s = three.get("scale_factor")
    if s is None or abs(s - 1.0) > SCALE_TOL:
        why.append(f"scale at three laps {s if s is None else round(s, 3)}, outside 1 ± {SCALE_TOL}")
    need = (one.get("floor_iou") or 0.0) - IOU_DROP
    if (three.get("floor_iou") or 0.0) < need:
        why.append(f"floor IoU at three laps {three.get('floor_iou'):.3f}, under one lap's {one.get('floor_iou'):.3f} - {IOU_DROP}")
    return not why, why


def floor_iou(run: Path, truth: dict, poses: list[np.ndarray]) -> float | None:
    """The plan's rooms, carried into the mesh's frame by the cameras' similarity, against the
    true floor raster."""
    from arkitscenes import umeyama
    from replica import CELL
    from shapely import contains_xy
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from levanta.scene import PointCloud

    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    idx = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
    cams = PointCloud.load_ply(run / "plan_cloud.ply").cameras[:, :3, 3]
    truth_c = np.array([poses[min(round(f["time_s"]), len(poses) - 1)][:3, 3] for f in idx])
    s, R, t, _rms = umeyama(cams, truth_c)
    h = truth["horiz"]
    polys = []
    for r in plan["rooms"]:
        pts = np.array([[x, y, 0.0] for x, y in r["polygon"]])
        w = s * (R @ pts.T).T + t
        polys.append(Polygon([(p[h[0]], p[h[1]]) for p in w]).buffer(0))
    if not polys:
        return 0.0
    rooms = unary_union(polys)
    filled, lo = truth["filled"], truth["lo"]
    gi, gj = np.meshgrid(np.arange(filled.shape[0]), np.arange(filled.shape[1]), indexing="ij")
    inside = contains_xy(rooms, lo[0] + gi.ravel() * CELL, lo[1] + gj.ravel() * CELL).reshape(filled.shape)
    union = (inside | filled).sum()
    return float((inside & filled).sum() / union) if union else None


def build_videos(out: Path, n: int) -> dict[str, list[int]]:
    from replica import frames_to_video

    seqs = {}
    for name, laps in LAPS.items():
        seq = lap_sequence(n, laps)
        video = out / f"{name}.mp4"
        if not video.exists():
            frames_to_video([SOURCE / "render" / f"frame_{i:05d}.png" for i in seq], video)
        seqs[name] = seq
    (out / "sequences.json").write_text(json.dumps(seqs), encoding="utf-8")
    return seqs


def guarded_run(video: Path, run: Path, extra: list[str], log_path: Path) -> dict:
    """`levanta video` as a user runs it, only while nobody plays, stopped if a game opens."""
    from fps_sweep import interpreter, supervise
    from when_idle import game_open, wait_until_idle

    done = run.parent / f"{run.name}.timing.json"
    if done.exists() and json.loads(done.read_text(encoding="utf-8")).get("rc") == 0 and (run / "plan.json").exists():
        return json.loads(done.read_text(encoding="utf-8"))
    cmd = [interpreter(), "-m", "levanta.cli", "video", str(video), "-o", str(run), "--fps", "1", "--max-views", "24", "--lang", "en", "--paper", "A3", *extra]
    run.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        while True:
            wait_until_idle(log)
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} idle, running {run.name}\n")
            log.flush()
            done.write_text(json.dumps({"started": time.time(), "cmd": cmd}), encoding="utf-8")
            rec = supervise(cmd, run.parent / f"{run.name}.log", should_stop=game_open)
            done.write_text(json.dumps({"cmd": cmd, **rec}), encoding="utf-8")
            if not rec.get("stopped"):
                break
            log.write(f"{time.strftime('%H:%M:%S')} {run.name} stopped: {rec['stopped']} opened; waiting to retry\n")
            log.flush()
        log.write(f"{time.strftime('%H:%M:%S')} {run.name} rc {rec['rc']} in {rec['seconds']:.0f} s\n")
    return rec


def score(run: Path, truth: dict, poses: list[np.ndarray]) -> dict:
    from replica import evaluate

    from levanta.plan.types import FloorPlan

    r = evaluate(run, truth, poses, len(poses))
    if not r.get("ok"):
        return r
    fp = FloorPlan.from_json(run / "plan.json")
    r["floor_iou"] = floor_iou(run, truth, poses)
    r["chunks"] = fp.meta.get("chunks")
    r["views"] = fp.meta.get("views")
    chain = fp.scale_chain_broken
    scales = [float(s) for s in (fp.meta.get("chunk_scales") or [])]
    acc, lo, hi = 1.0, 1.0, 1.0
    for s in scales:
        acc *= s
        lo, hi = min(lo, acc), max(hi, acc)
    r["chunks_apart_in_size"] = hi / lo
    r["scale_chain_broken"] = list(chain) if chain else None
    return r


def per_chunk(run: Path, seq: list[int], poses: list[np.ndarray]) -> list[dict]:
    """Each raw chunk's own scale, by its cameras against the exact poses and by its depth
    against the exact rendered depth.  1 is the right size, below 1 too big."""
    from arkitscenes import umeyama
    from chain_policies import load_chunks
    from known_poses import compare_depth, depth_truth

    index = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
    out = []
    for k, c in enumerate(load_chunks(run / "chunks")):
        steps = [min(round(index[int(i)]["time_s"]), len(seq) - 1) for i in c["idx"]]
        src = np.array([c["T"][j][:3, 3] for j in range(len(steps))])
        dst = np.array([poses[st][:3, 3] for st in steps])
        s_cam, _R, _t, rms = umeyama(src, dst)
        ratios = []
        for j, st in enumerate(steps):
            true = depth_truth(SOURCE / "render", seq[st])
            if true is None:
                continue
            got = compare_depth(c["depth"][j].astype(np.float32), c["mask"][j], true)
            if got:
                ratios.append(got["scale"])
        out.append({"chunk": k, "views": len(steps), "scale_by_cameras": float(s_cam), "camera_fit_rms_m": float(rms),
                    "scale_by_depth": float(1.0 / np.median(ratios)) if ratios else None,
                    "travel_m": float(np.linalg.norm(np.diff(dst, axis=0), axis=1).sum())})
    return out


def main() -> None:
    from area_report import area_with_scale
    from replica import floor_truth, load_mesh

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "replica_laps")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--skip-per-chunk", action="store_true", help="only the runs the verdict needs")
    ap.add_argument("--focal-px", type=float, default=None, help="the renderer's true focal at the frames' width (731.2 at 1024 px); the product path passes a known focal")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    base = [np.array(p) for p in json.loads((SOURCE / "walk_poses.json").read_text(encoding="utf-8"))["poses"]]
    seqs = build_videos(args.out, len(base))
    focal = ["--focal-px", f"{args.focal_px:.2f}"] if args.focal_px else []
    truth = floor_truth(load_mesh(SCENE_DIR / "mesh.ply"))
    log = args.out / "replica_laps.log"
    rows = {}
    for name in LAPS:
        poses = [base[i] for i in seqs[name]]
        run = args.out / name
        if not args.score_only:
            rec = guarded_run(args.out / f"{name}.mp4", run, focal, log)
            if rec.get("rc") != 0:
                print(f"{name}: levanta failed ({rec.get('rc')}), see {run.parent / (run.name + '.log')}")
                continue
        rows[name] = score(run, truth, poses)
        print(f"{name}: {json.dumps({k: v for k, v in rows[name].items() if k != 'per_room'})}")
    chunks_tables = {}
    if not args.skip_per_chunk:
        for name in LAPS:
            poses = [base[i] for i in seqs[name]]
            run = args.out / f"{name}_independent"
            if not args.score_only:
                rec = guarded_run(args.out / f"{name}.mp4", run, [*focal, "--independent-chunks", "--keep-chunks"], log)
                if rec.get("rc") != 0:
                    continue
            if (run / "chunks").exists():
                chunks_tables[name] = per_chunk(run, seqs[name], poses)
    (args.out / "replica_laps.json").write_text(json.dumps({"runs": rows, "per_chunk": chunks_tables}, indent=1), encoding="utf-8")
    dash = "\u2014"
    fmt = lambda v, f="{:.2f}": dash if v is None else f.format(v)  # noqa: E731
    lines = ["| walk | frames | chunks | area error | floor IoU | rooms | camera error | chunks apart in size |", "|" + "---|" * 8]
    for name, r in rows.items():
        if r.get("ok"):
            lines.append(f"| {name.replace('_', ' ')} | {r.get('views')} | {r.get('chunks')} | {area_with_scale(r['area_total_error_pct'], r['scale_factor'])} "
                         f"| {fmt(r.get('floor_iou'))} | {r['rooms_levanta']} ({r['rooms_truth']}) | {fmt(r.get('camera_rms_m'))} m | {fmt(r.get('chunks_apart_in_size'), '{:.3g}')} |")
    if "one_lap" in rows and "three_laps" in rows and rows["one_lap"].get("ok") and rows["three_laps"].get("ok"):
        ok, why = holds(rows["one_lap"], rows["three_laps"])
        lines += ["", f"Rule (written before any run): at three laps scale within 1 ± {SCALE_TOL} and floor IoU >= one lap's - {IOU_DROP}.",
                  "Verdict: " + ("HOLDS" if ok else "does not hold: " + "; ".join(why))]
    for name, table in chunks_tables.items():
        by_cam = [c["scale_by_cameras"] for c in table]
        by_depth = [c["scale_by_depth"] for c in table if c["scale_by_depth"] is not None]
        lines += ["", f"Own scale per chunk, {name.replace('_', ' ')} ({len(table)} chunks, solved independently):",
                  f"- by cameras: median {np.median(by_cam):.2f}, range {min(by_cam):.2f} to {max(by_cam):.2f}",
                  f"- by depth: median {np.median(by_depth):.2f}, range {min(by_depth):.2f} to {max(by_depth):.2f}" if by_depth else "- by depth: no pixels"]
    (args.out / "replica_laps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
