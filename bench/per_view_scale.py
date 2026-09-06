"""One scale per view, estimated from its overlap with its neighbours.

Rounds 6 and 7 both ended at the same place.  The network's *shape* is good to 5.6 %, its
poses are not the problem (handing it the exact ones changed nothing), and what breaks the
reconstruction is that each view's depth carries its own scale: median 0.54 of the truth,
and swinging from 0.37 to 0.70 between neighbouring views.  A cloud fused from views that
disagree about distance by a factor of two cannot produce a room.

The fix follows from the diagnosis.  If view *i* and view *j* see the same surface point,
that point has to land in the same place in the world:

    R_i (s_i d_i r_i) + t_i  =  R_j (s_j d_j r_j) + t_j

which is **linear in the two scales**, with the baseline t_j - t_i on the right.  Every
correspondence between two overlapping views gives three such rows, so the scales of a
whole walk come out of one least-squares solve, and the baselines fix the absolute scale
too rather than only the relative one.  Correspondences come from the poses themselves:
project view i's points into view j and read the depth they land on, then iterate, because
the projection is wrong exactly as much as the scales are.

**Thresholds, written before the first run.**  Stage 1 is a control on the rendered walk,
where the depth is exact and the scale error is injected, so the estimator is being asked
to recover something known:

- the spread of estimated/injected must fall from the injected 1.9 (p90/p10) to **≤ 1.15**;
- the median error of a recovered scale must be **≤ 5 %**.

If it cannot do that on data whose *only* error is the scale, it will not do it on real
predictions, and the idea dies here having cost no GPU at all.  Stage 2, on the network's
own depth, then has to bring the measured 0.37-0.70 spread under **1.3** and gain at least
one room or 15 points of area on the flat.

Usage:
    python bench/per_view_scale.py out/replica_apt0            # stage 1, the control
    python bench/per_view_scale.py out/replica_apt0 --pred DIR # stage 2, predicted depth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def pixel_rays(K: np.ndarray, h: int, w: int, stride: int) -> tuple[np.ndarray, np.ndarray]:
    """(N, 3) directions with z = 1 and their (N, 2) integer pixels, every ``stride`` px."""
    u, v = np.meshgrid(np.arange(0, w, stride), np.arange(0, h, stride))
    u, v = u.ravel().astype(np.float64), v.ravel().astype(np.float64)
    x = (u - K[0, 2]) / K[0, 0]
    y = (v - K[1, 2]) / K[1, 1]
    return np.stack([x, y, np.ones_like(x)], axis=1), np.stack([u, v], axis=1).astype(int)


def correspondences(i: int, j: int, depths, poses, K, rays, pix, scales, min_pts: int = 60, geom=None):
    """Points of view ``i`` that land inside view ``j``, paired with what ``j`` sees there.

    Returns ``(a_i, a_j)``: the two world-space directions whose scaled sum must close the
    baseline.  Occlusions are cut by dropping pairs whose depths disagree by more than 30 %
    after the current scales, which is loose enough to survive a bad initial guess.

    ``geom`` is the depth used to *find* the match, which is not the depth being estimated:
    matching with the same quantity you are solving for is circular, and measurably so.
    Pass the truth here to ask whether the linear system itself works; in production the
    match comes from appearance (optical flow), never from depth.
    """
    Di, Dj = depths[i], depths[j]
    Gi = Di if geom is None else geom[i]
    h, w = Di.shape
    di = Gi[pix[:, 1], pix[:, 0]]
    ok = np.isfinite(di) & (di > 0.2)
    if ok.sum() < min_pts:
        return None
    Ri, ti = poses[i][:3, :3], poses[i][:3, 3]
    Rj, tj = poses[j][:3, :3], poses[j][:3, 3]
    gscale = 1.0 if geom is not None else scales[i]
    world = (Ri @ (gscale * di[ok, None] * rays[ok]).T).T + ti
    cam_j = (Rj.T @ (world - tj).T).T
    front = cam_j[:, 2] > 0.2
    if front.sum() < min_pts:
        return None
    uv = (K @ cam_j[front].T).T
    uv = uv[:, :2] / uv[:, 2:3]
    inside = (uv[:, 0] >= 0) & (uv[:, 0] < w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1)
    if inside.sum() < min_pts:
        return None
    src = np.nonzero(ok)[0][front][inside]
    qu, qv = uv[inside, 0].astype(int), uv[inside, 1].astype(int)
    dj = (Dj if geom is None else geom[j])[qv, qu]
    # the match is found with ``geom`` but the equation uses the depth being estimated, so
    # both have to be valid: filtering only on ``geom`` let masked predictions in as zeros
    # and drove the estimated scale to 0.18 before this was caught
    good = np.isfinite(dj) & (dj > 0.2) & (Dj[qv, qu] > 0.2) & (Di[pix[src, 1], pix[src, 0]] > 0.2)
    if good.sum() < min_pts:
        return None
    src, qu, qv, dj = src[good], qu[good], qv[good], dj[good]
    seen = cam_j[front][inside][good][:, 2]
    jscale = 1.0 if geom is not None else scales[j]
    keep = np.abs(jscale * dj - seen) < 0.30 * seen  # the same surface, not one behind it
    if keep.sum() < min_pts:
        return None
    src, qu, qv = src[keep], qu[keep], qv[keep]
    ray_j = np.stack([(qu - K[0, 2]) / K[0, 0], (qv - K[1, 2]) / K[1, 1], np.ones(len(qu))], axis=1)
    a_i = (Ri @ (Di[pix[src, 1], pix[src, 0]][:, None] * rays[src]).T).T
    a_j = (Rj @ (Dj[qv, qu][:, None] * ray_j).T).T
    return a_i, a_j


def flow_matches(img_i: np.ndarray, img_j: np.ndarray, pix: np.ndarray, max_err: float = 1.5):
    """Where each sampled pixel of view i appears in view j, from appearance alone.

    Dense optical flow both ways, keeping only the pixels that survive the round trip.  This
    is the honest source of a correspondence: it never looks at the depth being estimated.
    """
    import cv2

    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fwd = dis.calc(img_i, img_j, None)
    bwd = dis.calc(img_j, img_i, None)
    u, v = pix[:, 0], pix[:, 1]
    fu, fv = fwd[v, u, 0], fwd[v, u, 1]
    qu, qv = u + fu, v + fv
    h, w = img_i.shape
    inside = (qu >= 0) & (qu < w - 1) & (qv >= 0) & (qv < h - 1)
    qi, qj = np.clip(qv.astype(int), 0, h - 1), np.clip(qu.astype(int), 0, w - 1)
    bu, bv = bwd[qi, qj, 0], bwd[qi, qj, 1]
    err = np.hypot(qu + bu - u, qv + bv - v)
    ok = inside & (err < max_err)
    return np.nonzero(ok)[0], qu[ok], qv[ok]


def solve_scales(depths, poses, K, *, stride: int = 16, neighbours: int = 3, rounds: int = 3, max_pairs_pts: int = 400, geom=None, images=None, smooth: float = 0.0) -> np.ndarray:
    """Least squares over every overlapping pair, iterated so the correspondences improve.

    ``smooth`` ties neighbouring views together with rows ``smooth * (s_i - s_{i+1}) = 0``.
    That is not a convenience: measured on the network's own depth over a rendered walk, the
    per-view scale has autocorrelation +0.70 at one step and +0.36 at two, and its
    step-to-step change is 0.055 in log terms where independent draws would give 0.238.  The
    error *drifts*; a free scale per view is over-parameterised for it and lets a bad
    correspondence move one view alone.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import lsqr

    n = len(depths)
    h, w = depths[0].shape
    rays, pix = pixel_rays(K, h, w, stride)
    scales = np.ones(n)
    rng = np.random.default_rng(7)
    for _ in range(rounds):
        rows, cols, vals, rhs = [], [], [], []
        r = 0
        for i in range(n):
            for j in range(i + 1, min(n, i + neighbours + 1)):
                if images is not None:
                    src, qu, qv = flow_matches(images[i], images[j], pix)
                    if len(src) < 60:
                        continue
                    di = depths[i][pix[src, 1], pix[src, 0]]
                    dj = depths[j][qv.astype(int), qu.astype(int)]
                    fine = np.isfinite(di) & np.isfinite(dj) & (di > 0.2) & (dj > 0.2)
                    if fine.sum() < 60:
                        continue
                    src, qu, qv, di, dj = src[fine], qu[fine], qv[fine], di[fine], dj[fine]
                    ray_j = np.stack([(qu - K[0, 2]) / K[0, 0], (qv - K[1, 2]) / K[1, 1], np.ones(len(qu))], axis=1)
                    a_i = (poses[i][:3, :3] @ (di[:, None] * rays[src]).T).T
                    a_j = (poses[j][:3, :3] @ (dj[:, None] * ray_j).T).T
                else:
                    got = correspondences(i, j, depths, poses, K, rays, pix, scales, geom=geom)
                    if got is None:
                        continue
                    a_i, a_j = got
                if len(a_i) > max_pairs_pts:
                    sel = rng.choice(len(a_i), max_pairs_pts, replace=False)
                    a_i, a_j = a_i[sel], a_j[sel]
                b = poses[j][:3, 3] - poses[i][:3, 3]
                for k in range(len(a_i)):
                    for axis in range(3):
                        rows += [r, r]
                        cols += [i, j]
                        vals += [a_i[k, axis], -a_j[k, axis]]
                        rhs.append(b[axis])
                        r += 1
        if not rhs:
            return scales
        for i in range(n - 1):
            if smooth > 0:
                rows += [r, r]
                cols += [i, i + 1]
                vals += [smooth, -smooth]
                rhs.append(0.0)
                r += 1
        A = coo_matrix((vals, (rows, cols)), shape=(r, n)).tocsr()
        sol = lsqr(A, np.asarray(rhs), damp=1e-3)[0]
        sol = np.where(np.isfinite(sol) & (sol > 0.05) & (sol < 20), sol, np.median(sol[sol > 0]) if (sol > 0).any() else 1.0)
        scales = sol
    return scales


def plan_with(depths, poses, K, render: Path, n: int, label: str) -> dict:
    """Fuse these depths with these poses and plan the result.

    The estimator is only worth a GPU turn if the *plan* changes, so the last word is a
    floor plan against the flat's truth (51.8 m2, three rooms), not a scale statistic.
    """
    import cv2

    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.recon.rgbd import fuse_frames
    from levanta.scene import Camera, Frame

    frames = []
    for k in range(n):
        img = cv2.imread(str(render / f"frame_{k:05d}.png"))
        img = img[:, :, ::-1].copy() if img is not None else np.zeros((*depths[k].shape, 3), np.uint8)
        h, w = depths[k].shape
        frames.append(Frame(image=img, depth=depths[k].astype(np.float32), camera=Camera(K=K, T=poses[k], width=w, height=h)))
    cloud = fuse_frames(frames, stride=4, voxel=0.02, depth_max=12.0, edge_rel=0.06)
    plan = extract_floor_plan(cloud, PlanOptions()).plan
    areas = sorted((r.area for r in plan.rooms), reverse=True)
    total = float(sum(areas))
    print(f"  {label:26s} {len(plan.rooms)} rooms, {len(plan.walls):2d} walls, {total:5.1f} m2 ({100 * (total - 51.8) / 51.8:+.0f} %)  {[round(a, 1) for a in areas[:4]]}")
    return {"rooms": len(plan.rooms), "walls": len(plan.walls), "area_m2": total}


def spread(x: np.ndarray) -> float:
    return float(np.percentile(x, 90) / max(np.percentile(x, 10), 1e-9))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path, help="a bench/replica.py directory rendered with --save-depth")
    ap.add_argument("--pred", type=Path, default=None, help="directory of predicted depth_*.npy (stage 2)")
    ap.add_argument("--views", type=int, default=48)
    ap.add_argument("--stride", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--oracle-corr", action="store_true", help="find the matches with the true depth: asks whether the linear system works, before asking whether matching does")
    ap.add_argument("--flow", action="store_true", help="find the matches with optical flow on the images, which is what production would have")
    ap.add_argument("--plan", action="store_true", help="fuse and plan before and after the correction: the only result that decides anything")
    ap.add_argument("--shape-noise", type=float, default=0.0, help="relative smooth error on top of the scale, so the control is not easier than the network (measured: 0.056)")
    ap.add_argument("--smooth", type=float, default=0.0, help="tie neighbouring views' scales together; the real error drifts (autocorrelation +0.70 at one step) rather than jumping")
    ap.add_argument("--ar1", type=float, default=0.0, help="inject a *drifting* scale with this lag-1 autocorrelation instead of independent draws (measured: 0.70)")
    args = ap.parse_args()

    meta = json.loads((args.out / "walk_poses.json").read_text(encoding="utf-8"))
    K = np.array(meta["K"], dtype=np.float64)
    poses = [np.array(p, dtype=np.float64) for p in meta["poses"]]
    render = args.out / "render"
    n = min(args.views, len(poses))
    truth = [np.load(render / f"depth_{k:05d}.npy").astype(np.float64) for k in range(n)]
    for d in truth:
        d[~np.isfinite(d)] = 0.0
    poses = poses[:n]

    if args.pred is None:
        # stage 1: the control.  Inject the scale error that was measured on the network
        # (median 0.54, p10 0.37, p90 0.70) and ask the estimator to undo it.
        rng = np.random.default_rng(args.seed)
        if args.ar1 > 0:
            e = rng.normal(0.0, 0.249 * np.sqrt(1 - args.ar1**2), size=n)
            L = np.zeros(n)
            L[0] = rng.normal(0.0, 0.249)
            for k in range(1, n):
                L[k] = args.ar1 * L[k - 1] + e[k]
            injected = np.exp(np.log(0.54) + L)
        else:
            injected = np.exp(rng.normal(np.log(0.54), 0.249, size=n))
        depths = [t * s for t, s in zip(truth, injected, strict=True)]
        if args.shape_noise > 0:
            # the network's shape is good to 5.6 %, not perfect; a control without that error
            # is an easier problem than the one the estimator will actually face
            import cv2

            h, w = truth[0].shape
            for k in range(n):
                field = rng.normal(0.0, args.shape_noise, size=(8, 8))
                depths[k] = depths[k] * (1.0 + cv2.resize(field, (w, h), interpolation=cv2.INTER_CUBIC))
        extra = f", plus {100 * args.shape_noise:.1f} % smooth shape error" if args.shape_noise > 0 else ""
        print(f"{n} views, injected scale: median {np.median(injected):.3f}, p10 {np.percentile(injected, 10):.3f}, p90 {np.percentile(injected, 90):.3f}, spread {spread(injected):.2f}{extra}")
    else:
        injected = None
        depths = [np.load(args.pred / f"depth_{k:05d}.npy").astype(np.float64) for k in range(n)]
        for d in depths:
            d[~np.isfinite(d)] = 0.0
        ratio = np.array([np.median(d[(d > 0) & (t > 0)] / t[(d > 0) & (t > 0)]) for d, t in zip(depths, truth, strict=True)])
        print(f"{n} views, predicted/true: median {np.median(ratio):.3f}, p10 {np.percentile(ratio, 10):.3f}, p90 {np.percentile(ratio, 90):.3f}, spread {spread(ratio):.2f}")
        injected = ratio

    images = None
    if args.flow:
        import cv2

        images = [cv2.imread(str(render / f"frame_{k:05d}.png"), cv2.IMREAD_GRAYSCALE) for k in range(n)]
        if any(im is None for im in images):
            raise SystemExit("--flow needs the rendered frames next to the depth maps")
    est = solve_scales(depths, poses, K, stride=args.stride, geom=truth if args.oracle_corr else None, images=images, smooth=args.smooth)
    # the estimator says what to multiply each view's depth by; the residual error of the
    # corrected depth against the truth is what matters
    residual = injected * est
    residual = residual / np.median(residual)
    print(f"estimated scale: median {np.median(est):.3f}, p10 {np.percentile(est, 10):.3f}, p90 {np.percentile(est, 90):.3f}")
    print(f"after correction, spread of corrected/true: {spread(residual):.3f}  (threshold 1.15)")
    print(f"median error of a corrected view: {100 * np.median(np.abs(residual - 1)):.1f} %  (threshold 5 %)")
    print(f"worst 10 % of views off by more than: {100 * (np.percentile(np.abs(residual - 1), 90)):.1f} %")

    if args.plan:
        print()
        print("the plan, against a truth of 51.8 m2 in three rooms:")
        plan_with(truth, poses, K, render, n, "exact depth")
        plan_with(depths, poses, K, render, n, "with the scale error")
        plan_with([d * e for d, e in zip(depths, est, strict=True)], poses, K, render, n, "corrected")


if __name__ == "__main__":
    main()
