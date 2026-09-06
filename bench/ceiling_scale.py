"""Experiment: can the ceiling height fix the scale of a video reconstruction?

Homes have ceilings of about 2.4-2.7 m; the network sees floor and ceiling in most
walks.  For every benchmark scene, three ways to set the scale are compared with the
truth (the similarity that fits levanta's cameras to ARKit's, ``scale_factor`` in the
bench results):

- network alone: 1.0;
- ceiling: TYPICAL_CEILING / ceiling height the network measured;
- door: 0.80 m / width of the first door found (when one was).

The real ceiling height of each scene is read from the LiDAR mesh (the highest strong
band of down-facing triangles above the floor), to show how far a typical value is from
the truth on these homes.

Threshold written before running: the ceiling wins on a scene when its scale error is
smaller than the network's alone; it becomes automatic calibration if it wins on 4 of 5.

Usage: python bench/ceiling_scale.py <scenes_dir> <bench_out_dir> [--run noK]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import read_ply

TYPICAL_CEILING = 2.50
TYPICAL_DOOR = 0.80


def ceiling_truth(vertices: np.ndarray, faces: np.ndarray) -> tuple[float, float]:
    """(floor height, ceiling height) in the mesh's up axis; ceiling = the highest strong
    band of down-facing area more than 1.8 m above the floor."""
    tri = vertices[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(n, axis=1)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    scores = [float(area[np.abs(n[:, k]) > 0.9].sum()) for k in range(3)]
    up = int(np.argmax(scores))
    sign = 1.0 if float((n[:, up] * area).sum()) >= 0 else -1.0
    h = tri[:, :, up].mean(axis=1)
    facing_up = n[:, up] * sign > 0.9
    hist, edges = np.histogram(h[facing_up], bins=200, weights=area[facing_up])
    strong = np.nonzero(hist > 0.15 * hist.max())[0]
    floor_h = float(edges[strong[0]] + 0.5 * (edges[1] - edges[0]))
    facing_down = n[:, up] * sign < -0.9
    above = facing_down & (h > floor_h + 1.8)
    if not above.any():
        return floor_h, float("nan")
    hist, edges = np.histogram(h[above], bins=100, weights=area[above])
    strong = np.nonzero(hist > 0.25 * hist.max())[0]
    ceil_h = float(edges[strong[-1]] + 0.5 * (edges[1] - edges[0]))
    return floor_h, ceil_h


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("bench_out", type=Path)
    ap.add_argument("--run", default="noK")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    results = {r["video_id"]: r for r in json.loads((args.bench_out / "results.json").read_text(encoding="utf-8"))}
    rows = []
    for vid, r in results.items():
        run = r[args.run]
        if not run.get("ok"):
            continue
        plan = json.loads((args.bench_out / vid / args.run / "plan.json").read_text(encoding="utf-8"))
        v, f = read_ply(args.scenes_dir / vid / f"{vid}_3dod_mesh.ply")
        floor_h, ceil_h = ceiling_truth(v, f)
        true_ceiling = ceil_h - floor_h
        s_true = run["scale_factor"]
        h_net = plan["ceiling_height"]
        measured = plan.get("ceiling_measured", False)
        s_ceiling = TYPICAL_CEILING / h_net if measured and h_net > 0 else None
        doors = [o for o in plan["openings"] if o["kind"] == "door"]
        s_door = None
        if doors:
            w = abs(doors[0]["t1"] - doors[0]["t0"])
            s_door = TYPICAL_DOOR / w if w > 0 else None
        # the same experiment with the *true* ceiling instead of the typical one: the ceiling
        # of this home, as if the user had typed it
        s_ceiling_true = true_ceiling / h_net if measured and h_net > 0 and np.isfinite(true_ceiling) else None

        def err(s, s_true=s_true):
            return None if s is None else abs(s / s_true - 1.0) * 100.0

        rows.append(
            {
                "video_id": vid,
                "true_ceiling_m": true_ceiling,
                "net_ceiling_m": h_net,
                "ceiling_measured": measured,
                "s_true": s_true,
                "err_network_pct": err(1.0),
                "err_ceiling_typical_pct": err(s_ceiling),
                "err_ceiling_true_pct": err(s_ceiling_true),
                "err_door_pct": err(s_door),
                "flagged": bool(run.get("unreliable")),
            }
        )
    fmt = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.0f} %"  # noqa: E731
    print("| scene | real ceiling | network ceiling | scale error: network alone | ceiling (2.50 m) | ceiling (real height) | door (0.80 m) |")
    print("|---|---|---|---|---|---|---|")
    wins = 0
    for r in rows:
        print(f"| {r['video_id']}{' (flagged)' if r['flagged'] else ''} | {r['true_ceiling_m']:.2f} m | {r['net_ceiling_m']:.2f} m{'' if r['ceiling_measured'] else ' (default)'} | {fmt(r['err_network_pct'])} | {fmt(r['err_ceiling_typical_pct'])} | {fmt(r['err_ceiling_true_pct'])} | {fmt(r['err_door_pct'])} |")
        if r["err_ceiling_typical_pct"] is not None and r["err_ceiling_typical_pct"] < r["err_network_pct"]:
            wins += 1
    print(f"\nceiling (2.50 m) beats the network alone on {wins} of {len(rows)} scenes")
    (args.bench_out / f"ceiling_scale_{args.run}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
