"""Small, dependency-light numeric helpers shared by every stage.

All functions take and return plain ``numpy`` arrays.  Rotations are 3x3 matrices,
poses are 4x4 camera-to-world matrices in the OpenCV convention (x right, y down,
z forward) unless stated otherwise.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def unit(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Normalise the last axis of ``v`` to unit length (zero vectors stay zero)."""
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, eps)


def quat_to_rot(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """Unit quaternion (x, y, z, w) to a 3x3 rotation matrix."""
    q = np.array([qx, qy, qz, qw], dtype=np.float64)
    q /= np.linalg.norm(q)
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def rot_z(theta: float) -> np.ndarray:
    """Rotation of ``theta`` radians about +z."""
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def rotation_from_a_to_b(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest rotation ``R`` such that ``R @ a`` is parallel to ``b`` (Rodrigues)."""
    a = unit(a)
    b = unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        # 180 degrees: rotate about any axis orthogonal to a.
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis = unit(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def make_pose(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Assemble a 4x4 homogeneous transform from ``R`` (3x3) and ``t`` (3,)."""
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, dtype=np.float64).reshape(3)
    return T


def apply_transform(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 4x4 transform to an (N, 3) array of points."""
    pts = np.asarray(pts, dtype=np.float64)
    return pts @ T[:3, :3].T + T[:3, 3]


def voxel_downsample_indices(points: np.ndarray, voxel: float, seed: int = 0) -> np.ndarray:
    """Return indices of one representative point per occupied voxel of size ``voxel``.

    The representative is chosen deterministically (first point in a stable sort of a
    random permutation), so the result is reproducible for a given ``seed`` while not
    being biased toward the raster order of the input.
    """
    if len(points) == 0:
        return np.zeros(0, dtype=np.int64)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(points))
    keys = np.floor(points[perm] / voxel).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return np.sort(perm[first])


def estimate_normals_pca(points: np.ndarray, k: int = 16, workers: int = -1) -> np.ndarray:
    """Unoriented unit normals from the PCA of each point's ``k`` nearest neighbours."""
    points = np.asarray(points, dtype=np.float64)
    if len(points) < k + 1:
        return np.tile([0.0, 0.0, 1.0], (len(points), 1))
    tree = cKDTree(points)
    _, idx = tree.query(points, k=k + 1, workers=workers)
    nbrs = points[idx[:, 1:]]  # (N, k, 3)
    centred = nbrs - nbrs.mean(axis=1, keepdims=True)
    cov = np.einsum("nki,nkj->nij", centred, centred) / k
    # Smallest-eigenvalue eigenvector of each 3x3 covariance.
    _, v = np.linalg.eigh(cov)
    normals = v[:, :, 0]
    return unit(normals)


def orient_normals_towards(points: np.ndarray, normals: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Flip normals so they point towards the per-point ``targets`` (e.g. camera centres)."""
    d = np.asarray(targets, dtype=np.float64) - np.asarray(points, dtype=np.float64)
    flip = np.einsum("ij,ij->i", normals, d) < 0
    out = np.array(normals, dtype=np.float64, copy=True)
    out[flip] *= -1.0
    return out


def smooth_1d(x: np.ndarray, radius: int = 2) -> np.ndarray:
    """Triangular smoothing of a 1-D array (edges are zero-padded).

    A triangular kernel keeps an isolated spike a *peak* (a box kernel would turn it into
    a plateau whose maximum is ambiguous).
    """
    if radius <= 0:
        return np.asarray(x, dtype=np.float64)
    kernel = np.r_[np.arange(1, radius + 2), np.arange(radius, 0, -1)].astype(np.float64)
    kernel /= kernel.sum()
    padded = np.pad(np.asarray(x, dtype=np.float64), radius)
    return np.convolve(padded, kernel, mode="valid")


def find_peaks_1d(
    y: np.ndarray, min_height: float, min_distance: int = 1, prominence: float = 0.0
) -> np.ndarray:
    """Indices of local maxima of ``y`` above ``min_height`` separated by ``min_distance`` bins.

    A peak must also rise at least ``prominence`` above the lowest valley between it and the
    nearest higher peak on each side.  Peaks are returned strongest first.
    """
    y = np.asarray(y, dtype=np.float64)
    n = len(y)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    left = np.r_[-np.inf, y[:-1]]
    right = np.r_[y[1:], -np.inf]
    cand = np.flatnonzero((y >= left) & (y > right) & (y >= min_height))
    if len(cand) == 0:
        return cand
    if prominence > 0:
        keep = []
        for i in cand:
            # Walk left/right until a higher value is met; the min on the way is the base.
            # Reaching the array edge counts as dropping to zero.
            j = i
            base_l = y[i]
            while j > 0 and y[j - 1] <= y[i]:
                j -= 1
                base_l = min(base_l, y[j])
            if j == 0:
                base_l = min(base_l, 0.0)
            j = i
            base_r = y[i]
            while j < n - 1 and y[j + 1] <= y[i]:
                j += 1
                base_r = min(base_r, y[j])
            if j == n - 1:
                base_r = min(base_r, 0.0)
            if y[i] - max(base_l, base_r) >= prominence:
                keep.append(i)
        cand = np.asarray(keep, dtype=np.int64)
    order = cand[np.argsort(-y[cand], kind="stable")]
    chosen: list[int] = []
    for i in order:
        if all(abs(i - j) >= min_distance for j in chosen):
            chosen.append(int(i))
    return np.asarray(chosen, dtype=np.int64)


def angle_wrap(theta: np.ndarray, period: float) -> np.ndarray:
    """Wrap angles into ``[0, period)``."""
    return np.mod(theta, period)


def circular_mean(theta: np.ndarray, period: float, weights: np.ndarray | None = None) -> float:
    """Mean of angles with the given ``period`` (e.g. ``pi/2`` for Manhattan directions)."""
    theta = np.asarray(theta, dtype=np.float64)
    if weights is None:
        weights = np.ones_like(theta)
    scale = 2.0 * np.pi / period
    s = np.sum(weights * np.sin(theta * scale))
    c = np.sum(weights * np.cos(theta * scale))
    return float(np.mod(np.arctan2(s, c) / scale, period))
