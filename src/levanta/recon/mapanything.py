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


def fill_tied_aliases(model, state_dict: dict) -> int:
    """safetensors stores a shared tensor once; give every other name of it the same entry.

    Returns how many alias entries were added.
    """
    groups: dict[int, list[str]] = {}
    for n, t in list(model.named_parameters(remove_duplicate=False)) + list(model.named_buffers(remove_duplicate=False)):
        groups.setdefault(id(t), []).append(n)
    added = 0
    for names in groups.values():
        have = next((n for n in names if n in state_dict), None)
        if have is None:
            continue
        for n in names:
            if n not in state_dict:
                state_dict[n] = state_dict[have]
                added += 1
    return added


def load_from_state_dict_on_meta(model, state_dict: dict):
    """Fill a network built on the meta device from ``state_dict`` (tensors already on the
    target device).  Refuses to return a network with anything still on meta."""
    fill_tied_aliases(model, state_dict)
    result = model.load_state_dict(state_dict, strict=False, assign=True)
    left = [n for n, t in list(model.named_parameters()) + list(model.named_buffers()) if t.is_meta]
    if result.missing_keys or left:
        raise RuntimeError(f"the checkpoint does not cover the network: missing {result.missing_keys[:5]}, on meta {left[:5]}")
    return model


def load_straight_to_device(cls, model_name: str, device: str):
    """Build ``cls`` from its HuggingFace config on the meta device and fill it from the
    safetensors file directly on ``device``: no host copy of the weights at all."""
    import json

    import torch
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    cfg = json.loads(Path(hf_hub_download(model_name, "config.json")).read_text(encoding="utf-8"))
    enc = cfg.get("encoder_config")
    if isinstance(enc, dict) and enc.get("encoder_str") == "dinov2":
        cfg["encoder_config"] = {**enc, "torch_hub_pretrained": False}  # the checkpoint has them
    with torch.device("meta"):
        model = cls(**cfg)
    sd = load_file(hf_hub_download(model_name, "model.safetensors"), device=device)
    return load_from_state_dict_on_meta(model, sd)


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
        overlap: int = 4,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_views = max_views
        self.overlap = overlap
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
        # The host never holds the 4.6 GB of weights: the network is built on the meta
        # device and filled from the safetensors file straight on the GPU.  The standard
        # path (build on the CPU, then load) needs ~4.5 GB of host commit for the DINOv2
        # giant alone and died with "OS error 1455: the paging file is too small" on a
        # 32 GB laptop with other applications open, even with map_location set.
        try:
            model = load_straight_to_device(MapAnything, self.model_name, device)
        except Exception as e:  # a checkpoint without safetensors, an offline cache ...
            print(f"direct load failed ({type(e).__name__}: {e}); loading the standard way")
            model = MapAnything.from_pretrained(self.model_name, map_location=device)
        self._model = model.to(device)
        self._model.eval()
        self._device = device
        return self._model

    # -- inference -----------------------------------------------------------------------

    def predict_views(
        self,
        image_paths: Sequence[Path],
        intrinsics: Sequence[np.ndarray | None] | None = None,
        poses: Sequence[np.ndarray | None] | None = None,
    ) -> list[dict]:
        """Raw per-view predictions (numpy): depth, intrinsics, pose, mask, image.

        ``intrinsics`` (one 3x3 per image, in the *original* image's pixels) are optional
        but worth passing when known (EXIF focal length, ARCore/ARKit, a calibrated
        camera): MapAnything then solves for geometry with the focal length fixed, which
        removes most of the metric-scale error.  ``poses`` (camera-to-world 4x4, metres)
        pin views whose position is already known; MapAnything requires the first view to
        be one of them when any is.  Output poses are in the frame of the first view.
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
        if poses is not None and any(T is not None for T in poses):
            if poses[0] is None:
                raise ValueError("MapAnything needs a pose on the first view when any view has one")
            views = _attach_poses(views, poses)
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
        """Every frame through the network, ``max_views`` at a time.

        A walk longer than one batch goes in consecutive chunks: each chunk after the
        first starts with ``overlap`` views of the previous one, handed to the network with
        their known poses and intrinsics, and its output is aligned onto those views
        (scale, rotation, translation) so all chunks share one metric world frame.
        """
        frames = [f for f in frames if f.path is not None]
        if not frames:
            raise ValueError("MapAnythingBackend needs frames with an image path")
        n = len(frames)
        overlap = max(1, min(self.overlap, self.max_views - 1))
        step = self.max_views - overlap
        solved: dict[int, dict] = {}  # frame index -> view dict in the world frame
        chunks = 0
        start = 0
        prev: list[int] = []
        while start < n:
            if not prev:
                idx = list(range(0, min(self.max_views, n)))
                known = [None] * len(idx)
            else:
                ov = prev[-overlap:]
                idx = ov + list(range(start, min(start + step, n)))
                known = [solved[i]["T"] for i in ov] + [None] * (len(idx) - len(ov))
            ks = []
            for i, T in zip(idx, known, strict=True):
                f = frames[i]
                if T is not None and i in solved:
                    ks.append(_k_in_original_pixels(solved[i], f.path))
                else:
                    ks.append(None if f.camera is None else f.camera.K)
            views = self.predict_views([frames[i].path for i in idx], intrinsics=ks if any(k is not None for k in ks) else None, poses=known if any(T is not None for T in known) else None)
            chunks += 1
            if prev:
                sim = align_similarity([views[j]["T"] for j in range(len(ov))], [solved[i]["T"] for i in ov])
                for v in views:
                    v["T"] = sim.apply(v["T"])
                    v["depth"] = v["depth"] * sim.scale
            for j, i in enumerate(idx):
                if i not in solved:
                    solved[i] = views[j]
            prev = idx
            start = idx[-1] + 1
        out_frames = []
        dropped = 0
        for i in range(n):
            v = solved[i]
            depth = v["depth"].copy()
            depth[~v["mask"]] = 0.0
            h, w = depth.shape
            if is_flat_picture(depth, v["K"]):
                depth[:] = 0.0  # a title graphic, a photo on the wall filling the frame: not the house
                dropped += 1
            out_frames.append(Frame(image=v["image"], depth=depth, camera=Camera(K=v["K"], T=v["T"], width=w, height=h)))
        cloud = fuse_frames(out_frames, stride=self.stride, voxel=self.voxel, depth_max=self.depth_max, edge_rel=0.06)
        cloud.meta.update({"source": "mapanything", "model": self.model_name, "views": n, "chunks": chunks, "views_dropped_flat": dropped})
        return cloud


def is_flat_picture(depth: np.ndarray, K: np.ndarray, min_cover: float = 0.5, max_rel_rms: float = 0.02) -> bool:
    """True when the valid depth covers most of the frame and lies on one plane within
    ``max_rel_rms`` of the median depth: the network was shown a picture (a title
    graphic, a poster), not a room.  On the first real walkthrough the intro graphic
    came back as a plane at 0.62 m covering 90 % of the frame."""
    valid = depth > 0
    if valid.mean() < min_cover:
        return False
    ys, xs = np.nonzero(valid)
    step = max(1, len(xs) // 4000)
    xs, ys = xs[::step], ys[::step]
    z = depth[ys, xs].astype(np.float64)
    x = (xs - K[0, 2]) / K[0, 0] * z
    y = (ys - K[1, 2]) / K[1, 1] * z
    pts = np.c_[x, y, z]
    pts -= pts.mean(axis=0)
    _, sv, _ = np.linalg.svd(pts, full_matrices=False)
    rms = sv[-1] / np.sqrt(len(pts))
    return bool(rms < max_rel_rms * np.median(z))


class Similarity:
    """x_world = scale * R @ x + t, applied to camera-to-world poses."""

    def __init__(self, scale: float, R: np.ndarray, t: np.ndarray) -> None:
        self.scale, self.R, self.t = float(scale), np.asarray(R, float), np.asarray(t, float)

    def apply(self, T: np.ndarray) -> np.ndarray:
        out = np.eye(4)
        out[:3, :3] = self.R @ T[:3, :3]
        out[:3, 3] = self.scale * (self.R @ T[:3, 3]) + self.t
        return out


def align_similarity(src: Sequence[np.ndarray], dst: Sequence[np.ndarray]) -> Similarity:
    """The similarity that carries camera poses ``src`` onto ``dst`` (both camera-to-world).

    Rotation from the orientations (the closest rotation to the mean of R_dst R_src^T),
    scale from the distances between camera centres, translation from the centres.  Two
    views are enough; the orientations make it well posed even when the centres are
    collinear, which they usually are on a walk.
    """
    if len(src) != len(dst) or len(src) < 2:
        raise ValueError("align_similarity needs at least two matching poses")
    Rs = [np.asarray(d)[:3, :3] @ np.asarray(s_)[:3, :3].T for s_, d in zip(src, dst, strict=True)]
    U, _, Vt = np.linalg.svd(sum(Rs))
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    cs = np.array([np.asarray(s_)[:3, 3] for s_ in src])
    cd = np.array([np.asarray(d)[:3, 3] for d in dst])
    ratios = []
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            ds, dd = np.linalg.norm(cs[i] - cs[j]), np.linalg.norm(cd[i] - cd[j])
            if ds > 1e-6 and dd > 1e-6:
                ratios.append(dd / ds)
    scale = float(np.median(ratios)) if ratios else 1.0
    t = (cd - scale * (R @ cs.T).T).mean(axis=0)
    return Similarity(scale, R, t)


def _k_in_original_pixels(view: dict, path: Path) -> np.ndarray:
    """A solved view's intrinsics, expressed in the pixels of the file on disk (the
    network worked at its own resolution; ``_attach_intrinsics`` undoes this again)."""
    from PIL import Image

    with Image.open(path) as im:
        w0, h0 = im.size
    h1, w1 = view["depth"].shape
    s_ = max(w1 / w0, h1 / h0)
    K = np.array(view["K"], dtype=np.float64).copy()
    K[0, 2] += (w0 * s_ - w1) / 2.0
    K[1, 2] += (h0 * s_ - h1) / 2.0
    K[0, :] /= s_
    K[1, :] /= s_
    return K


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


def _attach_poses(views: list[dict], poses: Sequence[np.ndarray | None]) -> list[dict]:
    """Add known camera-to-world poses (metres) to MapAnything's loaded views."""
    import torch

    out = []
    for v, T in zip(views, poses, strict=True):
        if T is None:
            out.append(v)
            continue
        v = dict(v)
        v["camera_poses"] = torch.from_numpy(np.asarray(T, dtype=np.float64)).float()[None]
        v["is_metric_scale"] = torch.tensor([True])
        out.append(v)
    return out


def _np(t) -> np.ndarray:
    if hasattr(t, "detach"):
        return t.detach().float().cpu().numpy()
    return np.asarray(t)
