"""Core data containers: cameras, frames and point clouds.

A :class:`PointCloud` is the hand-off between reconstruction (:mod:`levanta.recon`) and
plan extraction (:mod:`levanta.plan`).  It keeps, per point, the index of the camera that
observed it, because visibility is what lets the planner tell a doorway from an unseen
piece of wall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from levanta.geometry import apply_transform, voxel_downsample_indices


@dataclass
class Camera:
    """Pinhole camera: intrinsics ``K`` (3x3) and camera-to-world pose ``T`` (4x4, OpenCV)."""

    K: np.ndarray
    T: np.ndarray
    width: int
    height: int
    dist: np.ndarray | None = None  # OpenCV distortion (k1 k2 p1 p2 k3) or None

    @property
    def center(self) -> np.ndarray:
        return self.T[:3, 3]

    @property
    def up(self) -> np.ndarray:
        """World-space 'up' of the device: minus the camera y axis (OpenCV y points down)."""
        return -self.T[:3, 1]

    @property
    def forward(self) -> np.ndarray:
        return self.T[:3, 2]


@dataclass
class Frame:
    """One captured frame; ``depth`` is metric (metres) when present."""

    image: np.ndarray | None = None  # (H, W, 3) uint8 RGB
    depth: np.ndarray | None = None  # (H, W) float32 metres, 0 = invalid
    camera: Camera | None = None
    timestamp: float | None = None
    path: Path | None = None


@dataclass
class PointCloud:
    """Metric point cloud with optional per-point attributes and the cameras that saw it."""

    xyz: np.ndarray
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None  # (N, 3) uint8
    view: np.ndarray | None = None  # (N,) index into ``cameras``
    cameras: np.ndarray | None = None  # (M, 4, 4) camera-to-world
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.xyz = np.ascontiguousarray(self.xyz, dtype=np.float64).reshape(-1, 3)
        if self.normals is not None:
            self.normals = np.ascontiguousarray(self.normals, dtype=np.float64).reshape(-1, 3)
        if self.colors is not None:
            self.colors = np.ascontiguousarray(self.colors).reshape(-1, 3)
        if self.view is not None:
            self.view = np.ascontiguousarray(self.view, dtype=np.int32).reshape(-1)
        if self.cameras is not None:
            self.cameras = np.ascontiguousarray(self.cameras, dtype=np.float64).reshape(-1, 4, 4)

    def __len__(self) -> int:
        return len(self.xyz)

    @property
    def camera_centers(self) -> np.ndarray | None:
        return None if self.cameras is None else self.cameras[:, :3, 3]

    @property
    def camera_ups(self) -> np.ndarray | None:
        return None if self.cameras is None else -self.cameras[:, :3, 1]

    def point_camera_centers(self) -> np.ndarray | None:
        """Camera centre for every point (needs ``view`` and ``cameras``)."""
        if self.view is None or self.cameras is None:
            return None
        return self.cameras[self.view, :3, 3]

    def select(self, mask_or_idx: np.ndarray) -> PointCloud:
        """Sub-cloud with the given boolean mask or index array (cameras are kept)."""
        return PointCloud(
            xyz=self.xyz[mask_or_idx],
            normals=None if self.normals is None else self.normals[mask_or_idx],
            colors=None if self.colors is None else self.colors[mask_or_idx],
            view=None if self.view is None else self.view[mask_or_idx],
            cameras=self.cameras,
            meta=dict(self.meta),
        )

    def transformed(self, T: np.ndarray) -> PointCloud:
        """Rigidly transform points, normals and cameras by the 4x4 matrix ``T``."""
        R = T[:3, :3]
        return PointCloud(
            xyz=apply_transform(T, self.xyz),
            normals=None if self.normals is None else self.normals @ R.T,
            colors=self.colors,
            view=self.view,
            cameras=None if self.cameras is None else np.einsum("ij,njk->nik", T, self.cameras),
            meta=dict(self.meta),
        )

    def voxel_downsampled(self, voxel: float, seed: int = 0) -> PointCloud:
        return self.select(voxel_downsample_indices(self.xyz, voxel, seed=seed))

    # -- persistence -------------------------------------------------------------------

    def save_ply(self, path: str | Path) -> Path:
        """Write a binary little-endian PLY with xyz, normals, colours and view index."""
        path = Path(path)
        n = len(self)
        fields: list[tuple[str, str]] = [("x", "f4"), ("y", "f4"), ("z", "f4")]
        cols: list[np.ndarray] = [self.xyz.astype(np.float32)]
        if self.normals is not None:
            fields += [("nx", "f4"), ("ny", "f4"), ("nz", "f4")]
            cols.append(self.normals.astype(np.float32))
        if self.colors is not None:
            fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
            cols.append(self.colors.astype(np.uint8))
        if self.view is not None:
            fields += [("view", "i4")]
            cols.append(self.view.astype(np.int32).reshape(-1, 1))
        dtype = np.dtype([(name, f"<{t}") for name, t in fields])
        rec = np.empty(n, dtype=dtype)
        k = 0
        for arr in cols:
            arr = arr.reshape(n, -1)
            for j in range(arr.shape[1]):
                rec[fields[k][0]] = arr[:, j]
                k += 1
        ply_types = {"f4": "float", "u1": "uchar", "i4": "int"}
        header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
        header += [f"property {ply_types[t]} {name}" for name, t in fields]
        if self.cameras is not None:
            m = len(self.cameras)
            header.append(f"element camera {m}")
            header += [f"property float m{i}{j}" for i in range(3) for j in range(4)]
        header.append("end_header")
        with open(path, "wb") as f:
            f.write(("\n".join(header) + "\n").encode("ascii"))
            f.write(rec.tobytes())
            if self.cameras is not None:
                f.write(self.cameras[:, :3, :].astype("<f4").tobytes())
        return path

    @classmethod
    def load_ply(cls, path: str | Path) -> PointCloud:
        """Read a PLY written by :meth:`save_ply` or any binary/ascii PLY with xyz (via trimesh)."""
        path = Path(path)
        with open(path, "rb") as f:
            header_lines: list[str] = []
            while True:
                line = f.readline().decode("ascii", errors="replace").strip()
                header_lines.append(line)
                if line == "end_header":
                    break
            if "format binary_little_endian 1.0" not in header_lines:
                return cls._load_ply_generic(path)
            elements: list[tuple[str, int, list[tuple[str, str]]]] = []
            for line in header_lines:
                if line.startswith("element"):
                    _, name, count = line.split()
                    elements.append((name, int(count), []))
                elif line.startswith("property") and elements:
                    _, ptype, pname = line.split()
                    elements[-1][2].append((pname, ptype))
            data: dict[str, np.ndarray] = {}
            np_types = {"float": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4", "uint": "<u4"}
            for name, count, props in elements:
                if any(p not in np_types for _, p in props):
                    return cls._load_ply_generic(path)
                dtype = np.dtype([(pname, np_types[ptype]) for pname, ptype in props])
                data[name] = np.frombuffer(f.read(dtype.itemsize * count), dtype=dtype)
        v = data["vertex"]
        names = v.dtype.names or ()
        xyz = np.stack([v["x"], v["y"], v["z"]], axis=1)
        normals = np.stack([v["nx"], v["ny"], v["nz"]], axis=1) if "nx" in names else None
        colors = np.stack([v["red"], v["green"], v["blue"]], axis=1) if "red" in names else None
        view = v["view"].astype(np.int32) if "view" in names else None
        cameras = None
        if "camera" in data:
            c = data["camera"]
            m = np.stack([c[f"m{i}{j}"] for i in range(3) for j in range(4)], axis=1).reshape(-1, 3, 4)
            cameras = np.tile(np.eye(4), (len(m), 1, 1))
            cameras[:, :3, :] = m
        return cls(xyz=xyz, normals=normals, colors=colors, view=view, cameras=cameras)

    @classmethod
    def _load_ply_generic(cls, path: Path) -> PointCloud:
        import trimesh

        obj = trimesh.load(path)
        if isinstance(obj, trimesh.PointCloud):
            colors = None
            if obj.colors is not None and len(obj.colors) == len(obj.vertices):
                colors = np.asarray(obj.colors)[:, :3]
            return cls(xyz=np.asarray(obj.vertices), colors=colors)
        if isinstance(obj, trimesh.Trimesh):
            colors = None
            if obj.visual is not None and hasattr(obj.visual, "vertex_colors"):
                colors = np.asarray(obj.visual.vertex_colors)[:, :3]
            normals = np.asarray(obj.vertex_normals) if len(obj.faces) else None
            return cls(xyz=np.asarray(obj.vertices), normals=normals, colors=colors)
        raise ValueError(f"Unsupported PLY content in {path}")
