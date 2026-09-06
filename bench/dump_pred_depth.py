"""Save what the network predicts for every frame of a rendered walk, once.

Stage 2 of `bench/per_view_scale.py` needs MapAnything's own depth for the same frames the
renderer has exact depth for.  That is the only part of the experiment that needs the card,
so it is a single short run that writes `depth_%05d.npy` and `mask_%05d.npy` and then dies:
nothing stays loaded in VRAM between stints.

The predictions come back at the network's own resolution and are resized to the render's,
so the depth maps line up with `walk_poses.json`'s K and the truth in `render/` index for
index, and every later pass is numpy on the CPU.

Usage:
    python bench/dump_pred_depth.py out/replica_apt0 out/replica_apt0/pred --views 48
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path, help="a bench/replica.py directory rendered with --save-depth")
    ap.add_argument("dest", type=Path)
    ap.add_argument("--views", type=int, default=48)
    ap.add_argument("--chunk", type=int, default=24, help="views per forward pass, as in the video pipeline")
    ap.add_argument("--overlap", type=int, default=0, help="views shared between consecutive chunks, as the video pipeline does")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    import cv2

    from levanta.recon.mapanything import MapAnythingBackend

    render = args.out / "render"
    paths = [render / f"frame_{k:05d}.png" for k in range(args.views)]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} frames missing, first {missing[0]}")
    args.dest.mkdir(parents=True, exist_ok=True)
    shape = np.load(render / "depth_00000.npy").shape

    be = MapAnythingBackend(max_views=args.chunk, overlap=args.overlap)
    t0 = time.time()
    kept = 0
    for a in range(0, len(paths), args.chunk):
        views = be.predict_views(paths[a : a + args.chunk])
        for k, v in enumerate(views):
            d = np.asarray(v["depth"], dtype=np.float32)
            m = np.asarray(v["mask"]).astype(np.uint8)
            d = cv2.resize(d, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
            m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
            np.save(args.dest / f"depth_{a + k:05d}.npy", np.where(m > 0, d, 0.0).astype(np.float32))
            np.save(args.dest / f"mask_{a + k:05d}.npy", m)
            kept += 1
        print(f"  {kept}/{len(paths)} views, {time.time() - t0:.0f} s")
    (args.dest / "meta.json").write_text(json.dumps({"views": kept, "chunk": args.chunk, "source": str(render)}, indent=1), encoding="utf-8")
    print(f"{kept} predicted depth maps in {args.dest} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
