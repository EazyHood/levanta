"""Each view's depth scale, from the agreement of its 3D points with the other views'.

**Why.**  On the rendered flat the network puts every surface at about 0.55 of its true
distance while its cameras sit at about the right scale (bench/results/replica_laps_2026-09-24.md),
and with the exact poses the plan still finds one room of three (README, round 6).  Depth and
camera motion from the same network disagree by nearly a factor of two inside one chunk.

**What "consistent" means here, and why not the other reading.**  Comparing depth against
depth where two views overlap (a median ratio) cannot see this: with every view at 0.55 the
ratio comes out 1.  What exposes it is the 3D points.  View i is unprojected with its own
depth, carried into view j with the network's *own* relative pose, and compared with the depth
view j predicts at the pixel it lands on.  Scale the depths wrong and the points of two views
taken a metre apart do not meet; the scales at which they meet are the ones the network's
camera motion implies.  With depths at 0.55 and a baseline at 1 they come out near 1.8 by
themselves.

**No constants.**  Nothing here knows 0.55, 1.8 or anything read off Replica: every scale is
solved from the walk's own depths and poses.

**How.**  Where a point lands depends on the scale being tried, so a least-squares solve
started at 1 stays near 1 (the first version did exactly that on a room whose answer was
known).  So: first one scale for the whole chunk, searched on a log grid with the
correspondences recomputed at every value, keeping the one at which the points of the views
agree best; then one scale per view, from linear least squares (each correspondence gives
``s_i * a - s_j * d_j + b = 0``) started at that common scale, with the correspondences
recomputed each round and the worst residuals (occlusions mostly) trimmed.  The per-view
answer is kept only if the points agree at least as well as with the common one.  If the views
barely moved, the translation term that fixes the scale is too weak: the chunk is left as it
was and reported as not estimable.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

MIN_BASELINE_REL = 0.05  # pairs whose centres are closer than this fraction of the median depth carry no scale
NEIGHBOURS = 6  # pairs are views at most this many places apart in the walk: those overlap
PIXELS_PER_VIEW = 1500
GRID = np.geomspace(0.25, 4.0, 41)
ITERATIONS = 6
TRIM_MAD = 3.0


def _samples(view: dict, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Up to ``n`` valid pixels of a view: (rays with z = 1, 3 x N), depths (N,)."""
    depth, mask = np.asarray(view["depth"], np.float64), np.asarray(view["mask"], bool)
    ok = mask & (depth > 0.05) & np.isfinite(depth)
    ys, xs = np.nonzero(ok)
    if len(xs) > n:
        pick = rng.choice(len(xs), n, replace=False)
        ys, xs = ys[pick], xs[pick]
    Kinv = np.linalg.inv(np.asarray(view["K"], np.float64))
    rays = Kinv @ np.vstack([xs + 0.5, ys + 0.5, np.ones(len(xs))])
    rays /= rays[2]
    return rays, depth[ys, xs]


class _Pairs:
    """The fixed part of every correspondence: view i's points in view j's frame per unit of
    s_i (A) and the relative translation (B); what depends on the scales is where they land."""

    def __init__(self, views: Sequence[dict], seed: int) -> None:
        rng = np.random.default_rng(seed)
        self.views = views
        samples = [_samples(v, PIXELS_PER_VIEW, rng) for v in views]
        Ts = [np.asarray(v["T"], np.float64) for v in views]
        depths = [d for _, d in samples if len(d)]
        med = float(np.median(np.concatenate(depths))) if depths else 1.0
        self.items = []
        for i in range(len(views)):
            rays, di = samples[i]
            if not len(di):
                continue
            for j in range(max(0, i - NEIGHBOURS), min(len(views), i + NEIGHBOURS + 1)):
                if i == j or np.linalg.norm(Ts[i][:3, 3] - Ts[j][:3, 3]) < MIN_BASELINE_REL * med:
                    continue
                Ri, ti, Rj, tj = Ts[i][:3, :3], Ts[i][:3, 3], Ts[j][:3, :3], Ts[j][:3, 3]
                self.items.append((i, j, Rj.T @ Ri @ (rays * di), Rj.T @ (ti - tj)))

    def rows(self, s: np.ndarray) -> tuple[np.ndarray, ...]:
        """Correspondences at scales ``s``: (i, j, a, d_j, b) for every point that lands."""
        out_i, out_j, out_a, out_d, out_b = [], [], [], [], []
        for i, j, A, B in self.items:
            Y = s[i] * A + B[:, None]
            front = Y[2] > 0.05
            if not front.any():
                continue
            v = self.views[j]
            u = np.asarray(v["K"], np.float64) @ Y[:, front]
            px, py = u[0] / u[2], u[1] / u[2]
            dmap, m = np.asarray(v["depth"], np.float64), np.asarray(v["mask"], bool)
            h, w = dmap.shape
            inb = (px >= 0) & (px < w) & (py >= 0) & (py < h)
            xi, yi = px[inb].astype(int), py[inb].astype(int)
            dj = dmap[yi, xi]
            good = m[yi, xi] & (dj > 0.05)
            if good.sum() < 30:
                continue
            idx = np.nonzero(front)[0][inb][good]
            out_i.append(np.full(len(idx), i))
            out_j.append(np.full(len(idx), j))
            out_a.append(A[2, idx])
            out_d.append(dj[good])
            out_b.append(np.full(len(idx), B[2]))
        if not out_a:
            return ()
        return tuple(np.concatenate(x) for x in (out_i, out_j, out_a, out_d, out_b))

    def disagreement(self, s: np.ndarray) -> float:
        """Median relative disagreement of the points that land, at scales ``s``."""
        r = self.rows(s)
        if not r:
            return np.inf
        ri, rj, a, d, b = r
        return float(np.median(np.abs((s[ri] * a - s[rj] * d + b) / (s[rj] * d))))


def _per_view(pairs: _Pairs, s0: np.ndarray) -> np.ndarray | None:
    n = len(s0)
    s = s0.copy()
    for _ in range(ITERATIONS):
        r = pairs.rows(s)
        if not r:
            return None
        ri, rj, a, d, b = r
        e = (s[ri] * a - s[rj] * d + b) / (s[rj] * d)
        dev = np.abs(e - np.median(e))
        keep = dev <= TRIM_MAD * 1.4826 * np.median(dev) + 1e-9
        ri, rj, a, d, b = ri[keep], rj[keep], a[keep], d[keep], b[keep]
        wgt = 1.0 / np.maximum(d, 0.1) ** 2  # relative error: a metre matters less far away
        ata = np.zeros((n, n))
        atb = np.zeros(n)
        np.add.at(ata, (ri, ri), wgt * a * a)
        np.add.at(ata, (rj, rj), wgt * d * d)
        np.add.at(ata, (ri, rj), -wgt * a * d)
        np.add.at(ata, (rj, ri), -wgt * a * d)
        np.add.at(atb, ri, -wgt * a * b)
        np.add.at(atb, rj, wgt * d * b)
        seen = np.diag(ata) > 0
        if seen.sum() < 2 or np.linalg.cond(ata[np.ix_(seen, seen)]) > 1e10:
            return None
        sol = np.linalg.solve(ata[np.ix_(seen, seen)], atb[seen])
        if not np.all(np.isfinite(sol)) or np.any(sol <= 0):
            return None
        s = s0.copy()
        s[seen] = sol
        s[~seen] = float(np.median(sol))
    return s


def consistent_depth_scales(views: Sequence[dict], seed: int = 0) -> tuple[np.ndarray, dict]:
    """One depth scale per view, and a report of how it was found.

    ``views`` carry ``depth`` (H x W, z-depth), ``mask``, ``K`` and ``T`` (camera-to-world), all
    in one frame, as a chunk comes out of the network.  Multiply each view's depth by its scale.
    """
    n = len(views)
    ones = np.ones(n)
    report: dict = {"estimable": False, "pairs": 0}
    if n < 2:
        return ones, report
    pairs = _Pairs(views, seed)
    report["pairs"] = len(pairs.items)
    if not pairs.items:
        return ones, report
    costs = [pairs.disagreement(np.full(n, g)) for g in GRID]
    k = int(np.argmin(costs))
    if not np.isfinite(costs[k]):
        return ones, report
    lo, hi = GRID[max(k - 1, 0)], GRID[min(k + 1, len(GRID) - 1)]
    fine = np.geomspace(lo, hi, 21)
    fine_costs = [pairs.disagreement(np.full(n, g)) for g in fine]
    common = float(fine[int(np.argmin(fine_costs))])
    common_cost = float(min(fine_costs))
    # a chunk whose cost barely changes across the grid carries no scale: the views did not move
    spread = float(np.nanmax([c for c in costs if np.isfinite(c)]) / max(common_cost, 1e-9))
    report.update({"common": common, "common_disagreement": common_cost, "grid_contrast": spread})
    if spread < 1.5:
        return ones, report
    s = np.full(n, common)
    per_view = _per_view(pairs, s)
    if per_view is not None:
        cost = pairs.disagreement(per_view)
        if cost <= common_cost:
            s, report["per_view_disagreement"] = per_view, cost
    report["estimable"] = True
    return s, report
