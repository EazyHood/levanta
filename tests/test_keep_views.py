"""`--keep-views` writes every view's depth, mask, intrinsics and pose next to the outputs.

Regression: the dump method was pasted outside the class and every benchmark run with
--keep-views died with "'MapAnythingBackend' object has no attribute '_dump'" after the
frame extraction.

Threshold written before the fix ran: with a dump directory set, reconstruct() leaves
view_XXXX.npz per view plus views.json naming max_views and overlap, and the npz holds a
float16 depth, a bool mask, a 3x3 K and a 4x4 pose.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from levanta.recon.mapanything import MapAnythingBackend


def test_dump_writes_one_npz_per_view(tmp_path):
    cv2 = pytest.importorskip("cv2")
    from levanta.scene import Frame

    H, W = 12, 16
    K = np.array([[16.0, 0, 7.5], [0, 16.0, 5.5], [0, 0, 1]])

    class Stub(MapAnythingBackend):
        def predict_views(self, image_paths, intrinsics=None, poses=None):
            out = []
            for k, _p in enumerate(image_paths):
                T = np.eye(4)
                T[:3, 3] = [0.3 * k, 0, 0]
                yy, xx = np.mgrid[0:H, 0:W]
                depth = (2.0 + 0.1 * (np.abs(xx - 7.5) / 7.5 + np.abs(yy - 5.5) / 5.5)).astype(np.float32)
                out.append({"depth": depth, "mask": np.ones((H, W), bool), "K": K.copy(), "T": T, "image": np.zeros((H, W, 3), np.uint8), "conf": None})
            return out

    frames = []
    for i in range(5):
        p = tmp_path / f"frame_{i:05d}.jpg"
        cv2.imwrite(str(p), np.full((H, W, 3), 127, np.uint8))
        frames.append(Frame(path=p))
    be = Stub(max_views=8, overlap=3, voxel=None, stride=1, dump_dir=tmp_path / "views")
    be.reconstruct(frames)
    meta = json.loads((tmp_path / "views" / "views.json").read_text(encoding="utf-8"))
    assert meta["max_views"] == 8 and meta["overlap"] == 3 and len(meta["views"]) == 5
    z = np.load(tmp_path / "views" / "view_0003.npz")
    assert z["depth"].dtype == np.float16 and z["depth"].shape == (H, W)
    assert z["mask"].dtype == bool and z["K"].shape == (3, 3) and z["T"].shape == (4, 4)
    assert abs(z["T"][0, 3] - 0.9) < 1e-6
