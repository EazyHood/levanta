"""Does more overlap between chunks buy less drift?

The bench says the drift lives inside a chunk (TSDF+ICP could not move it) and grows as
chunks are chained: on the Replica apartment (94 views, 5 chunks) the camera track ends
1.08 m from the truth and the three rooms come out as one.  The remaining lever named in
round 4 is how views are composed: fewer views per chunk with much more overlap, so each
chunk is placed on more shared evidence.

Runs `levanta video` on one video at several (max_views, overlap) settings and measures
each against the same truth.  Thresholds written before running, against the baseline
(24 views, 4 shared): camera RMS from 1.08 m to <= 0.50 m, and at least 2 of the 3 rooms
found, on at least one setting.

Usage: python bench/overlap_sweep.py <replica_scene_dir> <bench_out_with_walk> [--settings 24:4 16:8 12:6]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from replica import evaluate, floor_truth, load_mesh, run_levanta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--settings", nargs="*", default=["24:4", "16:8", "12:6"])
    ap.add_argument("--focal", action="store_true", help="pass the exact focal length")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    truth = floor_truth(load_mesh(args.scene / "mesh.ply"))
    meta = json.loads((args.out / "walk_poses.json").read_text(encoding="utf-8"))
    K = np.array(meta["K"])
    poses = [np.array(p) for p in meta["poses"]]
    video = args.out / "walk.mp4"
    f_frame = K[0, 0] * min(1024, int(2 * K[0, 2])) / (2 * K[0, 2]) if args.focal else None
    rows = []
    for spec in args.settings:
        mv, ov = (int(x) for x in spec.split(":"))
        run = args.out / f"sweep_{mv}_{ov}{'_K' if args.focal else ''}"
        run_levanta(video, run, mv, f_frame, extra=["--overlap", str(ov)])
        r = evaluate(run, truth, poses, len(poses))
        r["max_views"], r["overlap"] = mv, ov
        rows.append(r)
        print(f"{spec}: {json.dumps({k: v for k, v in r.items() if k != 'per_room'})}", flush=True)
    (args.out / "overlap_sweep.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n| views:overlap | scale | camera RMS | rooms | walls | total area error |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        if r.get("ok"):
            print(f"| {r['max_views']}:{r['overlap']} | {r['scale_factor']:.2f} | {r['camera_rms_m']:.2f} m | {r['rooms_levanta']} ({r['rooms_truth']}) | {r['walls']} | {r['area_total_error_pct']:+.0f} % |")
        else:
            print(f"| {r['max_views']}:{r['overlap']} | — | — | — | — | — |")


if __name__ == "__main__":
    main()
