"""Loader for the TUM RGB-D benchmark (Sturm et al., IROS 2012; CC BY 4.0).

A sequence directory holds ``rgb/``, ``depth/`` (16-bit PNG, 1/5000 m per unit),
``rgb.txt``, ``depth.txt`` and ``groundtruth.txt`` (``t tx ty tz qx qy qz qw`` of the
optical centre, camera-to-world).  Frames are associated by nearest timestamp, as in
the benchmark's own ``associate.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

from levanta.geometry import make_pose, quat_to_rot
from levanta.scene import Camera, Frame

DEPTH_SCALE = 5000.0

# fx, fy, cx, cy, (k1, k2, p1, p2, k3) for the RGB camera of each Kinect used in the benchmark.
INTRINSICS = {
    "freiburg1": (517.3, 516.5, 318.6, 255.3, (0.2624, -0.9531, -0.0054, 0.0026, 1.1633)),
    "freiburg2": (520.9, 521.0, 325.1, 249.7, (0.2312, -0.7849, -0.0033, -0.0001, 0.9172)),
    "freiburg3": (535.4, 539.2, 320.1, 247.6, (0.0, 0.0, 0.0, 0.0, 0.0)),
}


def _read_list(path: Path) -> list[tuple[float, list[str]]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            rows.append((float(parts[0]), parts[1:]))
    return rows


def _associate(a: np.ndarray, b: np.ndarray, max_diff: float) -> np.ndarray:
    """For every timestamp in ``a`` return the index of the closest in ``b`` (or -1)."""
    order = np.argsort(b)
    bs = b[order]
    pos = np.searchsorted(bs, a)
    best = np.full(len(a), -1, dtype=np.int64)
    for k, (t, p) in enumerate(zip(a, pos, strict=True)):
        cands = [i for i in (p - 1, p) if 0 <= i < len(bs)]
        if not cands:
            continue
        i = min(cands, key=lambda i: abs(bs[i] - t))
        if abs(bs[i] - t) <= max_diff:
            best[k] = order[i]
    return best


def camera_for_sequence(seq_dir: Path, width: int = 640, height: int = 480, undistort: bool = True) -> Camera:
    """Intrinsics of the Kinect that recorded ``seq_dir`` (guessed from the folder name)."""
    name = seq_dir.name.lower()
    key = next((k for k in INTRINSICS if k in name), "freiburg1")
    fx, fy, cx, cy, dist = INTRINSICS[key]
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    return Camera(K=K, T=np.eye(4), width=width, height=height, dist=np.asarray(dist) if undistort else None)


def load_tum_sequence(
    seq_dir: str | Path,
    stride: int = 1,
    max_frames: int | None = None,
    max_time_diff: float = 0.02,
    load_rgb: bool = True,
    undistort: bool = True,
) -> list[Frame]:
    """Load associated (rgb, depth, pose) triplets from a TUM RGB-D sequence directory."""
    return list(
        iter_tum_sequence(
            seq_dir, stride=stride, max_frames=max_frames, max_time_diff=max_time_diff, load_rgb=load_rgb, undistort=undistort
        )
    )


def iter_tum_sequence(
    seq_dir: str | Path,
    stride: int = 1,
    max_frames: int | None = None,
    max_time_diff: float = 0.02,
    load_rgb: bool = True,
    undistort: bool = True,
) -> Iterator[Frame]:
    import cv2

    seq_dir = Path(seq_dir)
    depth_rows = _read_list(seq_dir / "depth.txt")
    rgb_rows = _read_list(seq_dir / "rgb.txt")
    gt_rows = _read_list(seq_dir / "groundtruth.txt")
    t_depth = np.array([t for t, _ in depth_rows])
    t_rgb = np.array([t for t, _ in rgb_rows])
    t_gt = np.array([t for t, _ in gt_rows])
    gt = np.array([[float(x) for x in v] for _, v in gt_rows])  # tx ty tz qx qy qz qw

    rgb_idx = _associate(t_depth, t_rgb, max_time_diff)
    gt_idx = _associate(t_depth, t_gt, max_time_diff)
    base_cam = camera_for_sequence(seq_dir, undistort=undistort)

    count = 0
    for k in range(0, len(depth_rows), stride):
        if rgb_idx[k] < 0 or gt_idx[k] < 0:
            continue
        depth_raw = cv2.imread(str(seq_dir / depth_rows[k][1][0]), cv2.IMREAD_UNCHANGED)
        if depth_raw is None:
            continue
        depth = depth_raw.astype(np.float32) / DEPTH_SCALE
        image = None
        if load_rgb:
            bgr = cv2.imread(str(seq_dir / rgb_rows[rgb_idx[k]][1][0]), cv2.IMREAD_COLOR)
            if bgr is not None:
                image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tx, ty, tz, qx, qy, qz, qw = gt[gt_idx[k]]
        T = make_pose(quat_to_rot(qx, qy, qz, qw), [tx, ty, tz])
        cam = Camera(K=base_cam.K, T=T, width=depth.shape[1], height=depth.shape[0], dist=base_cam.dist)
        yield Frame(image=image, depth=depth, camera=cam, timestamp=float(t_depth[k]), path=seq_dir / depth_rows[k][1][0])
        count += 1
        if max_frames is not None and count >= max_frames:
            break
