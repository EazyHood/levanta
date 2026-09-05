"""Back-project RGB-D frames with known poses into a fused, oriented point cloud.

This is the workhorse shared by every backend: MapAnything also ends up producing
per-view depth + intrinsics + pose, which flow through the very same code path.

Normals are computed on the depth image (central differences of the back-projected
grid), which is both faster and cleaner than a PCA on the fused cloud, and they are
oriented towards the camera so that the planner knows which side of a wall was seen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from levanta.geometry import unit, voxel_downsample_indices
from levanta.scene import Camera, Frame, PointCloud


def pixel_rays(camera: Camera) -> np.ndarray:
    """(H, W, 3) back-projection directions with z = 1, distortion-corrected if needed."""
    h, w = camera.height, camera.width
    fx, fy = camera.K[0, 0], camera.K[1, 1]
    cx, cy = camera.K[0, 2], camera.K[1, 2]
    u, v = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    dist = camera.dist
    if dist is not None and np.any(np.asarray(dist) != 0):
        import cv2

        pix = np.stack([u.ravel(), v.ravel()], axis=1).reshape(-1, 1, 2)
        norm = cv2.undistortPoints(pix, camera.K.astype(np.float64), np.asarray(dist, dtype=np.float64))
        x = norm[:, 0, 0].reshape(h, w)
        y = norm[:, 0, 1].reshape(h, w)
    else:
        x = (u - cx) / fx
        y = (v - cy) / fy
    return np.dstack([x, y, np.ones_like(x)])


def _erode(mask: np.ndarray, r: int) -> np.ndarray:
    """True where every pixel of the (2r+1)^2 neighbourhood is True."""
    out = mask.copy()
    for k in range(1, r + 1):
        out[:, k:] &= mask[:, :-k]
        out[:, :-k] &= mask[:, k:]
        out[k:, :] &= mask[:-k, :]
        out[:-k, :] &= mask[k:, :]
    return out


@dataclass
class BackprojectResult:
    xyz: np.ndarray  # (N, 3) world
    normals: np.ndarray  # (N, 3) world, unit, facing the camera
    colors: np.ndarray | None  # (N, 3) uint8
    pixels: np.ndarray  # (N, 2) int (u, v) of the kept samples


def backproject_frame(
    frame: Frame,
    stride: int = 4,
    depth_min: float = 0.2,
    depth_max: float = 8.0,
    edge_rel: float = 0.05,
    rays: np.ndarray | None = None,
    normal_radius: int = 3,
    smooth: bool = True,
) -> BackprojectResult:
    """Lift one frame's depth to world space.

    Parameters
    ----------
    stride
        Keep one pixel every ``stride`` in both directions (normals are still computed on
        the full-resolution grid).
    edge_rel
        A pixel whose depth differs from its neighbour ``normal_radius`` pixels away by
        more than ``edge_rel * depth`` is a depth discontinuity and is dropped (its normal
        would be meaningless).
    normal_radius
        Half-baseline (pixels) of the central differences used for normals.  Consumer depth
        sensors are noisy at the centimetre level, so a 1-pixel baseline gives normals that
        are wrong by tens of degrees; 3 pixels (~3 cm at 2.5 m) keeps them within ~10 deg.
    smooth
        Apply a 5x5 median to the depth before back-projecting (edge preserving).
    rays
        Optional cached output of :func:`pixel_rays` for this camera.
    """
    if frame.depth is None or frame.camera is None:
        raise ValueError("backproject_frame needs a frame with depth and camera")
    cam = frame.camera
    depth = np.asarray(frame.depth, dtype=np.float32)
    valid = (depth > depth_min) & (depth < depth_max) & np.isfinite(depth)
    if smooth:
        import cv2

        depth = cv2.medianBlur(np.where(valid, depth, 0).astype(np.float32), 5)
    depth = depth.astype(np.float64)
    if rays is None:
        rays = pixel_rays(cam)
    pts = depth[..., None] * rays  # camera frame, (H, W, 3)

    # Central differences over a 2r baseline -> normals in the camera frame.
    r = max(1, int(normal_radius))
    dx = np.zeros_like(pts)
    dy = np.zeros_like(pts)
    dx[:, r:-r] = pts[:, 2 * r :] - pts[:, : -2 * r]
    dy[r:-r, :] = pts[2 * r :, :] - pts[: -2 * r, :]
    n = np.cross(dx, dy)
    n = unit(n)
    # Orient towards the camera (camera at the origin of its own frame).
    flip = np.einsum("hwc,hwc->hw", n, pts) > 0
    n[flip] *= -1.0

    # Depth discontinuities, holes in the neighbourhood and border pixels invalidate the normal.
    ok = valid.copy()
    ok[:, : r + 1] = False
    ok[:, -r - 1 :] = False
    ok[: r + 1, :] = False
    ok[-r - 1 :, :] = False
    jump = np.zeros_like(valid)
    jump[:, r:-r] |= np.abs(depth[:, 2 * r :] - depth[:, : -2 * r]) > edge_rel * depth[:, r:-r]
    jump[r:-r, :] |= np.abs(depth[2 * r :, :] - depth[: -2 * r, :]) > edge_rel * depth[r:-r, :]
    nb_valid = _erode(valid, r)
    ok &= ~jump & nb_valid & (np.linalg.norm(n, axis=-1) > 0.5)

    sel = np.zeros_like(ok)
    sel[::stride, ::stride] = True
    keep = ok & sel
    vv, uu = np.nonzero(keep)

    R, t = cam.T[:3, :3], cam.T[:3, 3]
    xyz = pts[keep] @ R.T + t
    normals = n[keep] @ R.T
    colors = None
    if frame.image is not None:
        colors = np.asarray(frame.image)[keep][:, :3].astype(np.uint8)
    return BackprojectResult(xyz=xyz, normals=normals, colors=colors, pixels=np.stack([uu, vv], 1))


def fuse_frames(
    frames: Sequence[Frame],
    stride: int = 4,
    voxel: float | None = 0.02,
    depth_min: float = 0.2,
    depth_max: float = 8.0,
    edge_rel: float = 0.05,
    seed: int = 0,
) -> PointCloud:
    """Back-project every frame and merge into one cloud, remembering which camera saw each point.

    When ``voxel`` is set the merged cloud is thinned to one point per voxel; the
    representative is a random one, so the surviving ``view`` indices stay a fair sample
    of the cameras that observed each spot.
    """
    xyz_l, nrm_l, col_l, view_l, cams = [], [], [], [], []
    ray_cache: dict[tuple[int, int, bytes], np.ndarray] = {}
    has_color = all(f.image is not None for f in frames)
    for fr in frames:
        if fr.camera is None or fr.depth is None:
            continue
        key = (fr.camera.width, fr.camera.height, fr.camera.K.tobytes())
        if key not in ray_cache:
            ray_cache[key] = pixel_rays(fr.camera)
        res = backproject_frame(
            fr, stride=stride, depth_min=depth_min, depth_max=depth_max, edge_rel=edge_rel, rays=ray_cache[key]
        )
        cams.append(fr.camera.T)
        cam_idx = len(cams) - 1
        xyz_l.append(res.xyz)
        nrm_l.append(res.normals)
        if has_color and res.colors is not None:
            col_l.append(res.colors)
        view_l.append(np.full(len(res.xyz), cam_idx, dtype=np.int32))
    if not xyz_l:
        raise ValueError("no frame had both depth and a camera")
    cloud = PointCloud(
        xyz=np.concatenate(xyz_l),
        normals=np.concatenate(nrm_l),
        colors=np.concatenate(col_l) if col_l and has_color else None,
        view=np.concatenate(view_l),
        cameras=np.stack(cams),
        meta={"source": "rgbd", "frames": len(cams), "stride": stride},
    )
    if voxel:
        idx = voxel_downsample_indices(cloud.xyz, voxel, seed=seed)
        cloud = cloud.select(idx)
        cloud.meta["voxel"] = voxel
    return cloud


class RGBDBackend:
    """Backend for frames that already carry depth and poses."""

    name = "rgbd"

    def __init__(self, stride: int = 4, voxel: float | None = 0.02, depth_max: float = 8.0) -> None:
        self.stride = stride
        self.voxel = voxel
        self.depth_max = depth_max

    def reconstruct(self, frames: Sequence[Frame]) -> PointCloud:
        return fuse_frames(frames, stride=self.stride, voxel=self.voxel, depth_max=self.depth_max)
