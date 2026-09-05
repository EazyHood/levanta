"""MapAnything backend: plain RGB frames -> metric depth, intrinsics, poses -> point cloud.

MapAnything (Keetha et al., 3DV 2026; Apache-2.0 code, ``facebook/map-anything-apache``
weights under Apache-2.0) regresses metric multi-view geometry in one forward pass.
This module is a thin adapter: it runs the network and hands each view's depth map and
camera to :func:`levanta.recon.rgbd.fuse_frames`, so normals, visibility and thinning are
exactly the same as for RGB-D input.

Install::

    pip install torch --index-url https://download.pytorch.org/whl/cu128   # pick your CUDA
    pip install "git+https://github.com/facebookresearch/map-anything.git"
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from levanta.recon.rgbd import fuse_frames
from levanta.scene import Camera, Frame, PointCloud

MISSING = (
    "MapAnything is not installed. Run:\n"
    "  pip install torch --index-url https://download.pytorch.org/whl/cu128\n"
    '  pip install "git+https://github.com/facebookresearch/map-anything.git"'
)


class MapAnythingBackend:
    """Feed-forward metric reconstruction from RGB frames."""

    name = "mapanything"

    def __init__(
        self,
        model_name: str = "facebook/map-anything-apache",
        device: str | None = None,
        max_views: int = 32,
        confidence_percentile: float = 10.0,
        stride: int = 2,
        voxel: float | None = 0.02,
        depth_max: float = 12.0,
        memory_efficient: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_views = max_views
        self.confidence_percentile = confidence_percentile
        self.stride = stride
        self.voxel = voxel
        self.depth_max = depth_max
        self.memory_efficient = memory_efficient
        self._model = None

    # -- model ---------------------------------------------------------------------------

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import torch
            from mapanything.models import MapAnything
        except ImportError as e:  # pragma: no cover - depends on optional install
            raise ImportError(MISSING) from e
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = MapAnything.from_pretrained(self.model_name).to(device)
        self._model.eval()
        self._device = device
        return self._model

    # -- inference -----------------------------------------------------------------------

    def predict_views(self, image_paths: Sequence[Path], intrinsics: Sequence[np.ndarray | None] | None = None) -> list[dict]:
        """Raw per-view predictions (numpy): depth, intrinsics, pose, mask, image.

        ``intrinsics`` (one 3x3 per image, in the *original* image's pixels) are optional
        but worth passing when known (EXIF focal length, ARCore/ARKit, a calibrated
        camera): MapAnything then solves for geometry with the focal length fixed, which
        removes most of the metric-scale error.
        """
        import torch
        from mapanything.utils.image import load_images

        model = self._load()
        paths = [str(p) for p in image_paths][: self.max_views]
        try:
            views = load_images(paths)
        except Exception:  # some versions only take a directory
            with tempfile.TemporaryDirectory() as tmp:
                for i, p in enumerate(paths):
                    Path(tmp, f"{i:05d}{Path(p).suffix}").write_bytes(Path(p).read_bytes())
                views = load_images(tmp)
        if intrinsics is not None and any(k is not None for k in intrinsics):
            views = _attach_intrinsics(views, paths, intrinsics)
        with torch.inference_mode():
            preds = model.infer(
                views,
                memory_efficient_inference=self.memory_efficient,
                use_amp=True,
                amp_dtype="bf16",
                apply_mask=True,
                mask_edges=True,
                apply_confidence_mask=True,
                confidence_percentile=self.confidence_percentile,
            )
        out = []
        for p in preds:
            depth = _np(p["depth_z"])[0]
            depth = depth[..., 0] if depth.ndim == 3 else depth
            mask = _np(p["mask"])[0]
            mask = mask[..., 0] if mask.ndim == 3 else mask
            img = _np(p["img_no_norm"])[0]
            if img.shape[0] == 3 and img.ndim == 3 and img.shape[-1] != 3:
                img = np.transpose(img, (1, 2, 0))
            out.append(
                {
                    "depth": depth.astype(np.float32),
                    "mask": mask.astype(bool),
                    "K": _np(p["intrinsics"])[0].astype(np.float64),
                    "T": _np(p["camera_poses"])[0].astype(np.float64),
                    "image": (np.clip(img, 0, 1) * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8),
                    "conf": _np(p["conf"])[0] if "conf" in p else None,
                    "metric_scaling_factor": float(_np(p["metric_scaling_factor"]).ravel()[0])
                    if "metric_scaling_factor" in p
                    else None,
                }
            )
        return out

    def reconstruct(self, frames: Sequence[Frame]) -> PointCloud:
        frames = [f for f in frames if f.path is not None]
        if not frames:
            raise ValueError("MapAnythingBackend needs frames with an image path")
        paths = [f.path for f in frames]
        ks = [None if f.camera is None else f.camera.K for f in frames]
        views = self.predict_views(paths, intrinsics=ks if any(k is not None for k in ks) else None)
        out_frames = []
        for v in views:
            depth = v["depth"].copy()
            depth[~v["mask"]] = 0.0
            h, w = depth.shape
            cam = Camera(K=v["K"], T=v["T"], width=w, height=h)
            out_frames.append(Frame(image=v["image"], depth=depth, camera=cam))
        cloud = fuse_frames(out_frames, stride=self.stride, voxel=self.voxel, depth_max=self.depth_max, edge_rel=0.06)
        cloud.meta.update({"source": "mapanything", "model": self.model_name, "views": len(views)})
        return cloud


def _attach_intrinsics(views: list[dict], paths: Sequence[str], intrinsics: Sequence[np.ndarray | None]) -> list[dict]:
    """Add per-view intrinsics to MapAnything's loaded views, rescaled to the network's
    resolution (``load_images`` resizes and crops; we mirror that on K)."""
    import torch
    from PIL import Image

    out = []
    for v, p, K in zip(views, paths, intrinsics, strict=True):
        if K is None:
            out.append(v)
            continue
        with Image.open(p) as im:
            w0, h0 = im.size
        img = v["img"]
        h1, w1 = int(img.shape[-2]), int(img.shape[-1])
        # load_images scales so that the long side matches, then center-crops the other.
        s = max(w1 / w0, h1 / h0)
        K2 = np.array(K, dtype=np.float64).copy()
        K2[0, :] *= s
        K2[1, :] *= s
        K2[0, 2] -= (w0 * s - w1) / 2.0
        K2[1, 2] -= (h0 * s - h1) / 2.0
        v = dict(v)
        v["intrinsics"] = torch.from_numpy(K2).float()[None]
        out.append(v)
    return out


def _np(t) -> np.ndarray:
    if hasattr(t, "detach"):
        return t.detach().float().cpu().numpy()
    return np.asarray(t)
