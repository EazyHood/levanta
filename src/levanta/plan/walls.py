"""Wall faces, wall lines and wall segments from an oriented, gravity-aligned cloud.

Vocabulary
----------
direction family
    All walls whose *normal* makes the angle ``alpha`` (mod 180 deg) with +x.  In
    Manhattan mode there are exactly two families, ``alpha = 0`` and ``alpha = 90 deg``.
    Inside a family every point has an *offset* ``s = p . n`` across the wall and a
    *station* ``t = p . d`` along it, with ``n = (cos a, sin a)``, ``d = (-sin a, cos a)``.
face
    One observed surface: a run of points at (almost) the same offset whose normals all
    point to the same side (``sign = +1`` means the normal is ``+n``, i.e. the camera --
    and therefore the room -- was on the ``+n`` side and the wall body is on ``-n``).
wall line
    A face paired with the opposite face of the same wall (thickness measured) or a
    lone face plus a default thickness.  Holds the merged station intervals of all the
    faces on it, so a doorway shows up as a gap between two intervals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from levanta.geometry import circular_mean, find_peaks_1d, smooth_1d


@dataclass
class Face:
    alpha: float
    sign: int
    s: float
    t0: float
    t1: float
    tz: np.ndarray  # (M, 2) station / height of the inlier points
    coverage: float  # median number of height bands per station bin
    n_pts: int

    @property
    def length(self) -> float:
        return self.t1 - self.t0


@dataclass
class WallLine:
    id: int
    alpha: float
    s: float  # centreline offset
    thickness: float
    sides_seen: int
    faces: list[Face] = field(default_factory=list)
    intervals: list[tuple[float, float]] = field(default_factory=list)
    exterior: bool | None = None
    tz_all: np.ndarray | None = None  # (M, 2) station/height of *unfiltered* points on the line

    @property
    def n(self) -> np.ndarray:
        return np.array([np.cos(self.alpha), np.sin(self.alpha)])

    @property
    def d(self) -> np.ndarray:
        return np.array([-np.sin(self.alpha), np.cos(self.alpha)])

    def point(self, t: float, s: float | None = None) -> np.ndarray:
        s = self.s if s is None else s
        return s * self.n + t * self.d

    def face_tz(self, t0: float, t1: float) -> np.ndarray:
        """Station/height samples of every face of this line within ``[t0, t1]``."""
        parts = [f.tz[(f.tz[:, 0] >= t0) & (f.tz[:, 0] <= t1)] for f in self.faces]
        return np.concatenate(parts) if parts else np.zeros((0, 2))

    def samples(self, t0: float, t1: float) -> np.ndarray:
        """Like :meth:`face_tz` but from the unfiltered samples when they were attached."""
        if self.tz_all is None:
            return self.face_tz(t0, t1)
        m = (self.tz_all[:, 0] >= t0) & (self.tz_all[:, 0] <= t1)
        return self.tz_all[m]


def attach_samples(lines: list[WallLine], xy: np.ndarray, nxy: np.ndarray, z: np.ndarray, s_tol: float, angle_tol_deg: float = 20.0) -> None:
    """Give every line the unfiltered (station, height) samples lying on its faces.

    The face extraction works on coverage-filtered points, which is right for finding
    walls but too coarse for the *edges* of doors and windows; those are refined on the
    raw samples.
    """
    cos_min = np.cos(np.deg2rad(angle_tol_deg))
    for ln in lines:
        n, d = ln.n, ln.d
        dots = nxy @ n
        fam = np.abs(dots) >= cos_min
        s = xy[fam] @ n
        t = xy[fam] @ d
        zz = z[fam]
        sign = np.sign(dots[fam])
        keep = np.zeros(len(s), dtype=bool)
        for f in ln.faces:
            keep |= (np.abs(s - f.s) <= s_tol) & (sign == f.sign)
        ln.tz_all = np.stack([t[keep], zz[keep]], axis=1)


def refine_edges(tz: np.ndarray, t_a: float, t_b: float, z_lo: float, z_hi: float, bin_m: float = 0.01, min_pts: int = 2, search: float = 0.25) -> tuple[float, float]:
    """Move the ends of a gap ``[t_a, t_b]`` to the first *solid* station on each side.

    A station is solid when at least ``min_pts`` samples with height in ``[z_lo, z_hi]``
    fall into its 1 cm bin.  Used to sharpen door and window edges to ~1 cm.
    """
    if len(tz) == 0:
        return t_a, t_b
    sel = (tz[:, 1] >= z_lo) & (tz[:, 1] <= z_hi)
    t = tz[sel, 0]
    if len(t) == 0:
        return t_a, t_b
    edges = np.arange(t_a - search, t_b + search + bin_m, bin_m)
    h, _ = np.histogram(t, bins=edges)
    solid = h >= min_pts
    c = (t_a + t_b) / 2.0
    ci = int(np.clip(np.searchsorted(edges, c) - 1, 0, len(h) - 1))
    new_a, new_b = t_a, t_b
    left = np.flatnonzero(solid[:ci])
    if len(left):
        new_a = float(edges[left[-1] + 1])
    right = np.flatnonzero(solid[ci + 1 :])
    if len(right):
        new_b = float(edges[ci + 1 + right[0]])
    if new_b - new_a < 0.2:
        return t_a, t_b
    return new_a, new_b


def manhattan_angle(nxy: np.ndarray, weights: np.ndarray | None = None, bin_deg: float = 1.0, refine_deg: float = 8.0) -> float:
    """Dominant wall-normal angle in ``[0, pi/2)`` (Manhattan-world assumption).

    The *mode* of the angle histogram (folded to 90 deg) is taken first, because a plain
    circular mean is dragged around by the noisy normals of a consumer depth sensor; the
    mode is then refined by the circular mean of the angles within ``refine_deg`` of it.
    """
    ang = np.mod(np.arctan2(nxy[:, 1], nxy[:, 0]), np.pi / 2)
    nb = round(90.0 / bin_deg)
    hist, edges = np.histogram(ang, bins=nb, range=(0.0, np.pi / 2), weights=weights)
    ext = np.r_[hist[-3:], hist, hist[:3]]
    sm = smooth_1d(ext, 3)[3:-3]
    p = int(np.argmax(sm))
    a = float(0.5 * (edges[p] + edges[p + 1]))
    diff = np.abs(np.angle(np.exp(4j * (ang - a)))) / 4.0
    near = diff <= np.deg2rad(refine_deg)
    if near.sum() < 10:
        return a
    return circular_mean(ang[near], period=np.pi / 2, weights=None if weights is None else weights[near])


def direction_families(nxy: np.ndarray, bin_deg: float = 2.0, min_frac: float = 0.06, merge_deg: float = 12.0) -> list[float]:
    """Normal angles (mod pi) of the wall families supported by the data, strongest first."""
    ang = np.mod(np.arctan2(nxy[:, 1], nxy[:, 0]), np.pi)
    nb = round(180.0 / bin_deg)
    hist, edges = np.histogram(ang, bins=nb, range=(0.0, np.pi))
    # circular smoothing
    ext = np.r_[hist[-2:], hist, hist[:2]]
    sm = smooth_1d(ext, 2)[2:-2]
    peaks = find_peaks_1d(sm, min_height=min_frac * sm.max(), min_distance=int(merge_deg / bin_deg))
    centers = 0.5 * (edges[:-1] + edges[1:])
    half = np.deg2rad(merge_deg / 2)
    out: list[float] = []
    for p in peaks:
        a = float(centers[p])
        # refine with the circular mean of the angles around the peak
        diff = np.abs(np.angle(np.exp(2j * (ang - a)))) / 2
        near = ang[diff <= half]
        if len(near):
            a = circular_mean(near, period=np.pi)
        if all(min(abs(a - b), np.pi - abs(a - b)) > np.deg2rad(merge_deg) for b in out):
            out.append(a)
    return out or [0.0, np.pi / 2]


def _station_coverage(t: np.ndarray, z: np.ndarray, t_bin: float, z_band: float) -> tuple[np.ndarray, np.ndarray]:
    """Per station bin, number of distinct height bands hit.  Returns (bin_start, coverage)."""
    tb = np.floor(t / t_bin).astype(np.int64)
    zb = np.floor(z / z_band).astype(np.int64)
    key = np.unique(tb * 100_000 + zb)
    tb_u, counts = np.unique(key // 100_000, return_counts=True)
    return tb_u * t_bin, counts


def extract_faces(
    xy: np.ndarray,
    nxy: np.ndarray,
    z: np.ndarray,
    alpha: float,
    *,
    angle_tol_deg: float = 20.0,
    s_bin: float = 0.02,
    s_tol: float = 0.035,
    gap_tol: float = 0.30,
    min_len: float = 0.40,
    min_peak_points: int = 30,
    z_band: float = 0.15,
    min_bands: float = 3.0,
    t_bin: float = 0.05,
    z_top: float | None = None,
    total_bands: float | None = None,
    top_frac: float = 0.20,
    full_frac: float = 0.75,
) -> list[Face]:
    """Wall faces of one direction family (see module docstring).

    A run of points is accepted as a face when its median height coverage is at least
    ``min_bands``.  When the ceiling height ``z_top`` is known, it must additionally reach
    the ceiling band (``z_top - 0.5``) in ``top_frac`` of its station bins, or span
    ``full_frac`` of all bands: that is what separates a wall from a wardrobe or an open
    door leaf.
    """
    n = np.array([np.cos(alpha), np.sin(alpha)])
    d = np.array([-np.sin(alpha), np.cos(alpha)])
    dots = nxy @ n
    family = np.abs(dots) >= np.cos(np.deg2rad(angle_tol_deg))
    faces: list[Face] = []
    for sign in (+1, -1):
        m = family & (sign * dots > 0)
        if m.sum() < min_peak_points:
            continue
        s_all = xy[m] @ n
        t_all = xy[m] @ d
        z_all = z[m]
        lo, hi = s_all.min() - s_bin, s_all.max() + 2 * s_bin
        edges = np.arange(lo, hi, s_bin)
        hist, _ = np.histogram(s_all, bins=edges)
        sm = smooth_1d(hist, 1)
        centers = 0.5 * (edges[:-1] + edges[1:])
        peaks = find_peaks_1d(sm, min_height=float(min_peak_points), min_distance=3, prominence=0.5 * min_peak_points)
        for p in peaks:
            s0 = float(centers[p])
            inl = np.abs(s_all - s0) <= s_tol
            if inl.sum() < min_peak_points:
                continue
            s0 = float(np.median(s_all[inl]))
            inl = np.abs(s_all - s0) <= s_tol
            t = t_all[inl]
            zz = z_all[inl]
            order = np.argsort(t)
            t, zz = t[order], zz[order]
            breaks = np.flatnonzero(np.diff(t) > gap_tol)
            starts = np.r_[0, breaks + 1]
            ends = np.r_[breaks + 1, len(t)]
            for a, b in zip(starts, ends, strict=True):
                if b - a < 5:
                    continue
                tt, zr = t[a:b], zz[a:b]
                length = float(tt[-1] - tt[0])
                if length < min_len:
                    continue
                _, cov = _station_coverage(tt, zr, t_bin, z_band)
                cov_med = float(np.median(cov))
                if cov_med < min_bands:
                    continue
                if z_top is not None:
                    n_bins = max(1, int(np.ceil(length / t_bin)))
                    top_bins = np.unique(np.floor((tt[zr >= z_top - 0.5] - tt[0]) / t_bin).astype(np.int64))
                    reaches_top = len(top_bins) / n_bins >= top_frac
                    spans_all = total_bands is not None and cov_med >= full_frac * total_bands
                    if not (reaches_top or spans_all):
                        continue
                faces.append(
                    Face(
                        alpha=alpha,
                        sign=sign,
                        s=s0,
                        t0=float(tt[0]),
                        t1=float(tt[-1]),
                        tz=np.stack([tt, zr], axis=1),
                        coverage=cov_med,
                        n_pts=int(b - a),
                    )
                )
    return faces


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge_intervals(iv: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    """Union of intervals, also bridging gaps up to ``gap``."""
    if not iv:
        return []
    iv = sorted(iv)
    out = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(float(a), float(b)) for a, b in out]


def build_wall_lines(
    faces: list[Face],
    alpha: float,
    *,
    min_thickness: float = 0.04,
    max_thickness: float = 0.45,
    default_thickness: float = 0.10,
    min_overlap: float = 0.30,
    same_line_tol: float = 0.04,
    bridge_gap: float = 0.12,
    first_id: int = 0,
) -> list[WallLine]:
    """Pair opposite faces into measured walls; lone faces get ``default_thickness``."""
    fam = [f for f in faces if abs(f.alpha - alpha) < 1e-9]
    minus = sorted([f for f in fam if f.sign == -1], key=lambda f: f.s)
    plus = sorted([f for f in fam if f.sign == +1], key=lambda f: f.s)
    used: set[int] = set()
    raw: list[tuple[float, float, int, list[Face]]] = []  # (centre, thickness, sides, faces)
    for fm in minus:
        best: tuple[float, int] | None = None
        for j, fp in enumerate(plus):
            if j in used:
                continue
            th = fp.s - fm.s
            if not (min_thickness <= th <= max_thickness):
                continue
            ov = _overlap(fm.t0, fm.t1, fp.t0, fp.t1)
            if ov < min(min_overlap, 0.5 * min(fm.length, fp.length)):
                continue
            if best is None or th < best[0]:
                best = (th, j)
        if best is not None:
            th, j = best
            used.add(j)
            raw.append(((fm.s + plus[j].s) / 2.0, th, 2, [fm, plus[j]]))
        else:
            # normal = -n: room on the -n side, body extends towards +n.
            raw.append((fm.s + default_thickness / 2.0, default_thickness, 1, [fm]))
    for j, fp in enumerate(plus):
        if j not in used:
            raw.append((fp.s - default_thickness / 2.0, default_thickness, 1, [fp]))

    # Cluster by centreline offset so the two halves of a wall split by a door join up.
    raw.sort(key=lambda r: r[0])
    lines: list[WallLine] = []
    for centre, th, sides, fcs in raw:
        target = None
        for ln in lines:
            if abs(ln.s - centre) <= same_line_tol and (ln.sides_seen == sides or abs(ln.thickness - th) <= 0.03):
                target = ln
                break
        if target is None:
            lines.append(WallLine(id=first_id + len(lines), alpha=alpha, s=centre, thickness=th, sides_seen=sides, faces=list(fcs)))
        else:
            n_old = sum(f.n_pts for f in target.faces)
            n_new = sum(f.n_pts for f in fcs)
            target.s = (target.s * n_old + centre * n_new) / (n_old + n_new)
            if sides == 2 and target.sides_seen == 2:
                target.thickness = (target.thickness * n_old + th * n_new) / (n_old + n_new)
            elif sides == 2:
                target.thickness, target.sides_seen = th, 2
            target.faces.extend(fcs)
    for ln in lines:
        ln.intervals = merge_intervals([(f.t0, f.t1) for f in ln.faces], bridge_gap)
    return lines


def classify_exterior(line: WallLine, free_or_floor: np.ndarray, grid, probe: tuple[float, float] = (0.25, 0.60), n: int = 24) -> bool:
    """A lone-face wall is exterior when nothing was ever seen behind it."""
    if line.sides_seen == 2:
        return False
    f = line.faces[0]
    body_dir = -f.sign  # the wall body (and whatever lies behind) is opposite the face normal
    hits = []
    for t0, t1 in line.intervals:
        ts = np.linspace(t0, t1, max(3, int((t1 - t0) / 0.15) + 1))
        for off in np.linspace(probe[0], probe[1], 4):
            pts = np.stack([line.point(t, s=f.s + body_dir * off) for t in ts])
            inside = grid.inside(pts)
            if inside.any():
                hits.append(grid.sample(free_or_floor, pts[inside]))
    if not hits:
        return True
    frac = float(np.concatenate(hits).mean())
    return frac < 0.10


def line_intersection(a: WallLine, b: WallLine) -> tuple[float, float] | None:
    """Stations ``(t_a, t_b)`` where the two centrelines cross, or None if (nearly) parallel."""
    den_a = float(a.d @ b.n)
    den_b = float(b.d @ a.n)
    if abs(den_a) < 0.3 or abs(den_b) < 0.3:
        return None
    t_a = (b.s - a.s * float(a.n @ b.n)) / den_a
    t_b = (a.s - b.s * float(b.n @ a.n)) / den_b
    return float(t_a), float(t_b)
