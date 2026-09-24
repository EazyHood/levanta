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

**Held out, written before any result came back (the supervisor's condition, 2026-09-24).**
Those thresholds are numbers of 41069021 itself, so a policy that holds there is a hypothesis,
not a result.  The only other scene with a video on disk, 42897526, is the held-out one.

**Corrected before the held-out pass ran (second condition, same day).**  The first version
of this rule measured every scene against its own 1 fps IoU, which is the shape of 41069021,
where 1 fps is best.  On 42897526 the best walk today is 4 fps (IoU 0.61), so that version
would have let a policy sink a sound walk from 0.61 to 0.30 and still pass; and there the
chain does not break at 4 fps (9 chunks) but at 8 fps (17 chunks, scale 1.29, IoU 0.32).
The rule now names, per scene, which walks are sound and which chain is broken today, and
asks two things of each, with today's own numbers and nothing chosen afterwards:

- **it does not break a sound walk**: at each sound fps, floor IoU at least today's IoU at
  that same fps minus 0.05;
- **it holds the broken chain**: at the broken fps, scale within ±15 % of the truth and floor
  IoU at least the scene's best IoU today minus 0.15.

| scene | sound walks (IoU at least) | broken chain (scale 1 ± 0.15 and IoU at least) |
|---|---|---|
| 41069021, chosen | 1 fps: 0.6543 − 0.05 = 0.60 | 4 fps, 36 chunks: 0.6543 − 0.15 = 0.50 |
| 42897526, held out | 1 fps: 0.4315 − 0.05 = 0.38; 4 fps: 0.6127 − 0.05 = 0.56 | 8 fps, 17 chunks: 0.6127 − 0.15 = 0.46 |

On 41069021 this is exactly the rule written first, so the choice is unaffected.

1. The **winner** is chosen on 41069021 only: among the policies that hold there, the one with
   the smallest scale error at its broken chain.  With lambda = 1 and nothing retuned, it
   alone is then run on 42897526 (passes at 1, 4 and 8 fps, recomposed on the CPU) and must
   hold there.
2. If only the joint fit holds, and only at another lambda, that lambda is fixed on 41069021
   and judged on 42897526; never the other way round, never on both together.
3. Until a policy holds on both, the default of `levanta video` does not change and the
   warning at 9 chunks stays as it is.  A policy that holds on one and fails on the other is
   a result too: it says the ceiling is real and that this is not the way past it.


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

SCENE = "41069021"  # where the winner is chosen
HELD_OUT = "42897526"  # where it is judged
SWEEP_FPS = (1.0, 2.0, 4.0, 8.0)  # what "today" was measured at
# per scene: the walks that are sound today and the chain that is broken today
PLAN = {
    SCENE: {"sound": (1.0,), "broken": 4.0},
    HELD_OUT: {"sound": (1.0, 4.0), "broken": 8.0},
}
POLICIES = ("chained", "own_scale", "joint")
LAMBDA = 1.0
SCALE_TOL = 0.15
IOU_DROP_SOUND = 0.05  # a sound walk may lose this much IoU against today at the same fps
IOU_DROP_BROKEN = 0.15  # the broken chain must reach the scene's best IoU today minus this


def fps_for(scene_id: str) -> tuple[float, ...]:
    spec = PLAN[scene_id]
    return tuple(sorted({*spec["sound"], spec["broken"]}))


def thresholds(scene_id: str, today_iou: dict[float, float]) -> dict:
    """The numbers the rule sets on this scene, from today's IoU at every swept fps."""
    spec = PLAN[scene_id]
    return {"sound": {f: today_iou[f] - IOU_DROP_SOUND for f in spec["sound"]},
            "broken": (spec["broken"], max(today_iou.values()) - IOU_DROP_BROKEN)}


def holds(rows: list[dict], policy: str, scene_id: str, today_iou: dict[float, float]) -> tuple[bool, list[str]]:
    """Whether ``policy`` does not break the scene's sound walks and holds its broken chain,
    and why not.  The rule in the module docstring, written before the held-out pass."""
    by_fps = {r["fps"]: r for r in rows if r["policy"] == policy}
    th = thresholds(scene_id, today_iou)
    why = []
    for f, need in th["sound"].items():
        r = by_fps.get(f)
        if r is None:
            why.append(f"no run at {f:g} fps")
        elif (r.get("floor_iou") or 0.0) < need:
            why.append(f"sound walk at {f:g} fps broken: IoU {r.get('floor_iou'):.2f}, under {need:.2f}")
    f, need = th["broken"]
    r = by_fps.get(f)
    if r is None:
        why.append(f"no run at {f:g} fps")
    else:
        s = r.get("scale_factor")
        if s is None or abs(s - 1.0) > SCALE_TOL:
            why.append(f"chain at {f:g} fps not held: scale {s if s is None else round(s, 2)}, outside 1 ± {SCALE_TOL}")
        if (r.get("floor_iou") or 0.0) < need:
            why.append(f"chain at {f:g} fps not held: IoU {r.get('floor_iou'):.2f}, under {need:.2f}")
    return not why, why


def winner(rows: list[dict], today_iou: dict[float, float]) -> str | None:
    """Among the policies that hold on the scene where it is chosen, the one with the smallest
    scale error at its broken chain; None if none holds."""
    ok = [p for p in POLICIES if any(r["policy"] == p for r in rows) and holds(rows, p, SCENE, today_iou)[0]]
    if not ok:
        return None
    f = PLAN[SCENE]["broken"]
    return min(ok, key=lambda p: abs(math.log(next(r["scale_factor"] for r in rows if r["policy"] == p and r["fps"] == f))))


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


def place_by_points(chunks: list[dict], pixels: int = 4000, rounds: int = 3, seed: int = 0) -> tuple[dict[int, dict], np.ndarray]:
    """Option B: chunk k placed on chunk k-1 by the similarity that carries its shared frames'
    pixels onto the same pixels as chunk k-1 already placed them.  A shared frame is the same
    picture in both chunks, so the same pixel is the same point of the surface: thousands of
    exact correspondences instead of four camera centres.  Trimmed of its worst residuals and
    refitted.  Returns the placed frames and each chunk's log-scale."""
    from arkitscenes import umeyama

    from levanta.recon.mapanything import Similarity

    rng = np.random.default_rng(seed)
    solved: dict[int, dict] = {}
    xs = []
    for k, c in enumerate(chunks):
        if k == 0:
            sim = Similarity(1.0, np.eye(3), np.zeros(3))
        else:
            src, dst = [], []
            for j in range(int(c["shared"])):
                i = int(c["idx"][j])
                if i not in solved:
                    continue
                prev = solved[i]
                d_new, d_old = c["depth"][j].astype(np.float64), prev["depth"].astype(np.float64)
                if d_new.shape != d_old.shape:
                    continue
                ok = c["mask"][j] & prev["mask"] & (d_new > 0.05) & (d_old > 0.05)
                ys, xs_ = np.nonzero(ok)
                if len(xs_) > pixels:
                    pick = rng.choice(len(xs_), pixels, replace=False)
                    ys, xs_ = ys[pick], xs_[pick]
                uv1 = np.vstack([xs_ + 0.5, ys + 0.5, np.ones(len(xs_))])
                for K, T, d, out in ((c["K"][j], c["T"][j], d_new, src), (prev["K"], prev["T"], d_old, dst)):
                    rays = np.linalg.inv(np.asarray(K, np.float64)) @ uv1
                    rays /= rays[2]
                    pts = np.asarray(T, np.float64)[:3, :3] @ (rays * d[ys, xs_]) + np.asarray(T, np.float64)[:3, 3:4]
                    out.append(pts.T)
            if not src:
                raise ValueError(f"chunk {k} shares no usable pixels with the chunk before")
            a, b = np.concatenate(src), np.concatenate(dst)
            keep = np.ones(len(a), bool)
            for _ in range(rounds):
                s_, R_, t_, _rms = umeyama(a[keep], b[keep])
                res = np.linalg.norm(s_ * (R_ @ a.T).T + t_ - b, axis=1)
                keep = res <= 2.5 * np.median(res[keep]) + 1e-9
            sim = Similarity(s_, R_, t_)
        xs.append(math.log(sim.scale))
        for j, i in enumerate(c["idx"]):
            i = int(i)
            if i in solved:
                continue
            solved[i] = {"T": sim.apply(c["T"][j]), "depth": c["depth"][j].astype(np.float32) * sim.scale, "mask": c["mask"][j], "K": c["K"][j]}
    return solved, np.array(xs)


def wall_yaw(views: list[dict], up: np.ndarray, stride: int = 4) -> tuple[float, float]:
    """Option C's measurement: the direction of a chunk's walls about the vertical, modulo 90°,
    and how clearly it shows (0 to 1).  Normals come from each placed view's own point map;
    only near-horizontal normals (walls, not floor or ceiling) vote, and a room's two wall
    directions fold onto one by taking four times the angle."""
    up = up / np.linalg.norm(up)
    e1 = np.cross(up, [1.0, 0.0, 0.0] if abs(up[0]) < 0.9 else [0.0, 1.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    total, count = 0j, 0
    for v in views:
        d = np.asarray(v["depth"], np.float64)[::stride, ::stride]
        m = np.asarray(v["mask"], bool)[::stride, ::stride] & (d > 0.05)
        h, w = d.shape
        ys, xs = np.mgrid[0:h, 0:w]
        K = np.asarray(v["K"], np.float64)
        rays = np.linalg.inv(K) @ np.vstack([xs.ravel() * stride + 0.5, ys.ravel() * stride + 0.5, np.ones(h * w)])
        rays /= rays[2]
        T = np.asarray(v["T"], np.float64)
        P = (T[:3, :3] @ (rays * d.ravel()) + T[:3, 3:4]).T.reshape(h, w, 3)
        dx = P[1:-1, 2:] - P[1:-1, :-2]
        dy = P[2:, 1:-1] - P[:-2, 1:-1]
        n = np.cross(dx, dy)
        norm = np.linalg.norm(n, axis=2)
        ok = m[1:-1, 1:-1] & m[1:-1, 2:] & m[1:-1, :-2] & m[2:, 1:-1] & m[:-2, 1:-1] & (norm > 1e-9)
        # no normals across a depth edge: the four neighbours must sit near the centre's depth
        dc = d[1:-1, 1:-1]
        for nb in (d[1:-1, 2:], d[1:-1, :-2], d[2:, 1:-1], d[:-2, 1:-1]):
            ok &= np.abs(nb - dc) < 0.06 * dc
        n = n[ok] / norm[ok][:, None]
        horizontal = np.abs(n @ up) < 0.2
        n = n[horizontal]
        if not len(n):
            continue
        theta = np.arctan2(n @ e2, n @ e1)
        total += np.exp(4j * theta).sum()
        count += len(theta)
    if count == 0:
        return 0.0, 0.0
    return float(np.angle(total) / 4.0), float(abs(total) / count)


def place_yaw_from_walls(chunks: list[dict], x: np.ndarray, min_clarity: float = 0.2) -> dict[int, dict]:
    """Option C: placed as the chain places them, then each chunk turned about the vertical,
    through the centre of the frames it shares with the chunk before, so its walls run the
    walk's way (the first chunk's), modulo 90°.  A chunk whose walls do not show clearly
    (clarity under ``min_clarity``) is left as the chain put it."""
    from levanta.recon.mapanything import Similarity, align_similarity

    solved: dict[int, dict] = {}
    up = None
    ref = None
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
        placed = [{"T": sim.apply(c["T"][j]), "depth": c["depth"][j].astype(np.float32) * s, "mask": c["mask"][j], "K": c["K"][j]} for j in range(len(c["idx"]))]
        if k == 0:
            # up: against the cameras' mean "down" axis (OpenCV cameras, y down), held for the walk
            up = -np.mean([v["T"][:3, 1] for v in placed], axis=0)
            up /= np.linalg.norm(up)
            ref, _ = wall_yaw(placed, up)
        else:
            yaw, clarity = wall_yaw(placed, up)
            if clarity >= min_clarity:
                delta = (ref - yaw + math.pi / 4) % (math.pi / 2) - math.pi / 4
                pivot = np.mean([solved[int(c["idx"][j])]["T"][:3, 3] for j in range(int(c["shared"])) if int(c["idx"][j]) in solved], axis=0)
                a = up * math.sin(delta / 2)
                q = np.array([math.cos(delta / 2), *a])
                w_, x_, y_, z_ = q
                Rd = np.array([[1 - 2 * (y_ * y_ + z_ * z_), 2 * (x_ * y_ - z_ * w_), 2 * (x_ * z_ + y_ * w_)],
                               [2 * (x_ * y_ + z_ * w_), 1 - 2 * (x_ * x_ + z_ * z_), 2 * (y_ * z_ - x_ * w_)],
                               [2 * (x_ * z_ - y_ * w_), 2 * (y_ * z_ + x_ * w_), 1 - 2 * (x_ * x_ + y_ * y_)]])
                for v in placed:
                    T = v["T"].copy()
                    T[:3, :3] = Rd @ T[:3, :3]
                    T[:3, 3] = Rd @ (T[:3, 3] - pivot) + pivot
                    v["T"] = T
        for j, i in enumerate(c["idx"]):
            i = int(i)
            if i not in solved:
                solved[i] = placed[j]
    return solved


def write_recomposed(solved: dict[int, dict], x: np.ndarray, source_run: Path, run: Path) -> None:
    """Fuse and plan a recomposed walk into ``run`` the way `levanta video` would, leaving the
    files the evaluations read (plan.json, plan_cloud.ply, frames/index.json)."""
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


def plan_and_score(solved: dict[int, dict], x: np.ndarray, source_run: Path, run: Path, scene: Path, truth: dict) -> dict:
    from arkitscenes import evaluate

    write_recomposed(solved, x, source_run, run)
    r = evaluate(scene, run.parent, truth, run)
    r["composed_spread"] = float(math.exp(x.max() - x.min()))
    return r


def gpu_pass(scenes_dir: Path, out: Path, fps: float, scene_id: str = SCENE) -> dict:
    """levanta on the scene with independent, kept chunks, only while nobody plays."""
    from fps_sweep import interpreter, supervise
    from when_idle import game_open, wait_until_idle

    run_out = out / f"fps_{fps:g}"
    run_out.mkdir(parents=True, exist_ok=True)
    cmd = [interpreter(), str(HERE / "arkitscenes.py"), str(scenes_dir), str(run_out), "--only", scene_id, "--runs", "noK", "--fps", f"{fps:g}", "--independent-chunks"]
    record = run_out / "timing.json"
    with (out / "chain_policies.log").open("a", encoding="utf-8") as log:
        while True:
            wait_until_idle(log)
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} idle, running {scene_id} fps {fps:g}\n")
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


def per_chunk_scales(run_out: Path, scene: Path, scene_id: str) -> list[dict]:
    """Each raw chunk's own scale against the truth: the similarity between its cameras, as
    the network left them, and ARKit's cameras for the same frames.  Below 1 means the chunk
    came out too big, the benches' convention.  The camera travel inside the chunk is kept
    beside it, because a similarity fitted to cameras that barely moved is fragile."""
    from arkitscenes import read_traj, umeyama

    source = run_out / scene_id / "noK"
    index = json.loads((source / "frames" / "index.json").read_text(encoding="utf-8"))
    res = next(r["noK"] for r in json.loads((run_out / "results.json").read_text(encoding="utf-8")) if r["video_id"] == scene_id)
    off = res.get("time_offset_s", 0.0)
    ts, centres = read_traj(scene / "lowres_wide.traj")
    out = []
    for k, c in enumerate(load_chunks(source / "chunks")):
        src, dst = [], []
        for j, i in enumerate(c["idx"]):
            t = ts[0] + off + index[int(i)]["time_s"]
            m = int(np.argmin(np.abs(ts - t)))
            if abs(ts[m] - t) < 0.2:
                src.append(c["T"][j][:3, 3])
                dst.append(centres[m])
        if len(src) < 5:
            out.append({"chunk": k, "frames": len(src), "scale": None})
            continue
        dst_a = np.array(dst)
        s, _R, _t, rms = umeyama(np.array(src), dst_a)
        times = [index[int(i)]["time_s"] for i in c["idx"]]
        out.append({"chunk": k, "frames": len(src), "scale": float(s), "rms_m": float(rms),
                    "video_s": float(max(times) - min(times)),
                    "travel_m": float(np.linalg.norm(np.diff(dst_a, axis=0), axis=1).sum()),
                    "extent_m": float(max(np.linalg.norm(a - b) for a in dst_a for b in dst_a))})
    return out


def today_rows(scene_id: str) -> dict[float, dict]:
    """The fps sweep's own runs of this scene, poses fed in: the reference every rule reads."""
    out = {}
    for fps in SWEEP_FPS:
        rows = json.loads((ROOT / f"out/fps_sweep/fps_{fps:g}/results.json").read_text(encoding="utf-8"))
        out[fps] = next(r["noK"] for r in rows if r["video_id"] == scene_id)
    return out


def today_iou(scene_id: str) -> dict[float, float]:
    return {f: r["floor_iou"] for f, r in today_rows(scene_id).items()}


def verdict_lines(rows: list[dict], scene_id: str, judged: list[str]) -> list[str]:
    th = thresholds(scene_id, today_iou(scene_id))
    sound = ", ".join(f"at {f:g} fps IoU >= {v:.2f}" for f, v in th["sound"].items())
    f, need = th["broken"]
    lines = [f"Rule ({scene_id}, written before the held-out pass): sound walks {sound}; broken chain at {f:g} fps scale within 1 ± {SCALE_TOL} and IoU >= {need:.2f}."]
    for p in judged:
        ok, why = holds(rows, p, scene_id, today_iou(scene_id))
        lines.append(f"- {p}: {'HOLDS' if ok else 'does not hold: ' + '; '.join(why)}")
    return lines


def main() -> None:
    from area_report import area_with_scale
    from arkitscenes import floor_truth, read_ply

    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--recompose-only", action="store_true")
    ap.add_argument("--verdict-only", action="store_true", help="read chain_policies.json and apply the written rule")
    ap.add_argument("--lam", type=float, default=LAMBDA, help="weight of the joint fit's prior (fixed on the choice scene only)")
    ap.add_argument("--winner-from", type=Path, default=None,
                    help=f"chain_policies.json of {SCENE}: run only the policy that won there, on the held-out scene {HELD_OUT}")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    scene_id, policies, lam = SCENE, list(POLICIES), args.lam
    if args.winner_from is not None:
        chosen = json.loads(args.winner_from.read_text(encoding="utf-8"))
        w = winner(chosen, today_iou(SCENE))
        if w is None:
            print(f"no policy held on {SCENE}: nothing to judge on {HELD_OUT}; the ceiling stands")
            return
        scene_id, policies = HELD_OUT, [w]
        lam = next((r.get("lam", LAMBDA) for r in chosen if r["policy"] == w), LAMBDA)
        print(f"winner on {SCENE}: {w} (lambda {lam}); judged on {HELD_OUT} and nowhere else")
    if args.verdict_only:
        rows = json.loads((args.out / "chain_policies.json").read_text(encoding="utf-8"))
    else:
        scene = args.scenes_dir / scene_id
        truth = floor_truth(*read_ply(scene / f"{scene_id}_3dod_mesh.ply"))
        today = today_rows(scene_id)
        rows = []
        for fps in fps_for(scene_id):
            run_out = args.out / f"fps_{fps:g}"
            if not args.recompose_only:
                rec = gpu_pass(args.scenes_dir, args.out, fps, scene_id)
                if rec.get("rc") != 0:
                    print(f"fps {fps:g}: the GPU pass failed ({rec.get('rc')}); see {run_out / 'sweep.log'}")
                    continue
            source = run_out / scene_id / "noK"
            chunks = load_chunks(source / "chunks")
            assert all(int(c["fed_poses"]) == 0 for c in chunks), "these chunks were solved with poses fed in"
            rows.append({"fps": fps, "policy": "today (poses fed in)", "chunks": len(chunks), **today[fps]})
            for policy in policies:
                x = log_scales(chunks, policy, lam=lam)
                r = plan_and_score(place(chunks, x), x, source, run_out / f"recomposed_{policy}", scene, truth)
                rows.append({"fps": fps, "policy": policy, "lam": lam if policy == "joint" else None, "chunks": len(chunks), **r})
                print(f"fps {fps:g} {policy}: scale {r.get('scale_factor')}, IoU {r.get('floor_iou')}, rooms {r.get('levanta_rooms')}, spread {r['composed_spread']:.3g}")
        (args.out / "chain_policies.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    dash = "—"
    fmt = lambda v, f="{:.2f}": dash if v is None else f.format(v)  # noqa: E731
    lines = [f"Scene {scene_id}", "", "| fps | chunks | policy | area error | floor IoU | rooms | camera RMS | chunks apart in size |", "|" + "---|" * 8]
    for r in rows:
        lines.append(f"| {r['fps']:g} | {r['chunks']} | {r['policy']} | {area_with_scale(r.get('area_error_pct'), r.get('scale_factor'))} | {fmt(r.get('floor_iou'))} "
                     f"| {r.get('levanta_rooms', dash)} | {fmt(r.get('traj_rms_m'))} m | {fmt(r.get('composed_spread'), '{:.3g}')} |")
    judged = [p for p in policies if any(r["policy"] == p for r in rows)]
    lines += ["", *verdict_lines(rows, scene_id, judged)]
    if scene_id == SCENE:
        w = winner(rows, today_iou(SCENE))
        lines.append(f"Winner on {SCENE}: {w or 'none; the length ceiling stands'}" + (f", to be judged on {HELD_OUT} with --winner-from" if w else ""))
    (args.out / "chain_policies.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
