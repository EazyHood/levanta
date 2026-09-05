"""Find 'up', the floor and the ceiling; rotate the cloud into the plan frame.

Strategy
--------
1. A hint for 'up' comes from the cameras (a phone is held roughly upright, so the mean
   of ``-y`` camera axes is close to vertical) or from the caller.
2. Normals within a cone of the hint are averaged (with two tightening passes) to get a
   sharp estimate of the vertical from the floor/ceiling surfaces themselves.
3. The cloud is rotated so that 'up' is +z.  A histogram of z over points whose normal is
   vertical exposes the floor (normal up, low) and the ceiling (normal down, high).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from levanta.geometry import find_peaks_1d, make_pose, rotation_from_a_to_b, smooth_1d, unit
from levanta.scene import PointCloud


@dataclass
class GravityResult:
    up: np.ndarray  # unit vector in the *input* frame
    T: np.ndarray  # 4x4 input -> plan (up -> +z, floor -> z = 0)
    floor_z_in: float  # floor height along ``up`` in the input frame
    ceiling_height: float | None  # metres above floor, None if the ceiling was not seen
    floor_support: int  # number of vertical-normal points that voted for the floor
    ceiling_support: int


def estimate_up(cloud: PointCloud, hint: np.ndarray | None = None, cone_deg: tuple[float, ...] = (30.0, 15.0, 8.0)) -> np.ndarray:
    """Unit 'up' vector in the cloud's frame.

    ``hint`` defaults to the mean camera up; without cameras it defaults to +z (override
    with e.g. ``[0, -1, 0]`` for raw OpenCV-frame clouds).
    """
    if hint is None:
        ups = cloud.camera_ups
        hint = unit(ups.mean(axis=0)) if ups is not None and len(ups) else np.array([0.0, 0.0, 1.0])
    hint = unit(np.asarray(hint, dtype=np.float64))
    if cloud.normals is None:
        return hint
    n = cloud.normals
    up = hint
    for cone in cone_deg:
        cos_min = np.cos(np.deg2rad(cone))
        dots = n @ up
        sel = np.abs(dots) >= cos_min
        if sel.sum() < 50:
            break
        signed = n[sel] * np.sign(dots[sel])[:, None]  # flip ceiling normals to point up
        up = unit(signed.mean(axis=0))
    return up


def _height_peaks(z: np.ndarray, bin_m: float = 0.02, smooth_r: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lo, hi = np.percentile(z, [0.5, 99.5])
    edges = np.arange(lo - bin_m, hi + 2 * bin_m, bin_m)
    hist, _ = np.histogram(z, bins=edges)
    sm = smooth_1d(hist, smooth_r)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, hist, sm


def align_to_gravity(
    cloud: PointCloud,
    up: np.ndarray | None = None,
    hint: np.ndarray | None = None,
    vertical_cos: float = 0.9,
    min_room_height: float = 1.8,
    max_room_height: float = 6.0,
) -> tuple[PointCloud, GravityResult]:
    """Rotate/translate ``cloud`` so that up = +z and the floor is at z = 0."""
    if up is None:
        up = estimate_up(cloud, hint=hint)
    up = unit(np.asarray(up, dtype=np.float64))
    R = rotation_from_a_to_b(up, np.array([0.0, 0.0, 1.0]))
    T0 = make_pose(R, np.zeros(3))
    rot = cloud.transformed(T0)

    z = rot.xyz[:, 2]
    floor_z = float(np.percentile(z, 1.0))
    floor_support = 0
    ceiling_h: float | None = None
    ceiling_support = 0
    if rot.normals is not None:
        nz = rot.normals[:, 2]
        up_pts = z[nz > vertical_cos]  # faces pointing up = floors, table tops
        down_pts = z[nz < -vertical_cos]  # faces pointing down = ceilings
        if len(up_pts) > 100:
            centers, hist, sm = _height_peaks(up_pts)
            peaks = find_peaks_1d(sm, min_height=max(20.0, 0.05 * sm.max()), min_distance=5, prominence=0.02 * sm.max())
            if len(peaks):
                # The floor is the lowest strong peak: at least 15% of the strongest one.
                strong = [p for p in peaks if sm[p] >= 0.15 * sm[peaks].max()]
                p = min(strong, key=lambda i: centers[i])
                floor_z = float(centers[p])
                floor_support = int(hist[p])
        if len(down_pts) > 100:
            centers, hist, sm = _height_peaks(down_pts)
            peaks = find_peaks_1d(sm, min_height=max(20.0, 0.05 * sm.max()), min_distance=5, prominence=0.02 * sm.max())
            cands = [p for p in peaks if min_room_height <= centers[p] - floor_z <= max_room_height]
            if cands:
                strong = [p for p in cands if sm[p] >= 0.15 * sm[cands].max()]
                p = max(strong, key=lambda i: centers[i])  # highest strong downward face
                ceiling_h = float(centers[p] - floor_z)
                ceiling_support = int(hist[p])
    T = make_pose(R, np.array([0.0, 0.0, -floor_z]))
    aligned = cloud.transformed(T)
    return aligned, GravityResult(
        up=up, T=T, floor_z_in=floor_z, ceiling_height=ceiling_h, floor_support=floor_support, ceiling_support=ceiling_support
    )
