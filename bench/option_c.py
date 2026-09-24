"""Option C, judged: each chunk turned about the vertical so its walls run the walk's way.

The three laps lay the same rooms down again, turned.  C is the chain as today plus one
correction per chunk: the direction of its walls (modulo 90°, from the normals of its own
point maps) is compared with the first chunk's, and the chunk is turned by the difference
about the centre of the frames it shares with the chunk before (`place_yaw_from_walls`).

Judged with **the same numbers as option B**, committed before either ran
(`bench/results/option_b_thresholds_2026-09-24.json`), untouched: three laps at most 1.153 m
of camera error and three rooms, one lap at most 1.141 m, ARKitScenes at 1 fps floor IoU at
least 0.60.  "C with chunks solved independently" is not tried after seeing the numbers; if C
holds, that combination is a follow-up written first, not a rescue.

No GPU.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))


def main() -> None:
    from arkitscenes import floor_truth as arkit_floor_truth
    from arkitscenes import read_ply
    from chain_policies import (
        load_chunks,
        log_scales,
        place_yaw_from_walls,
        plan_and_score,
        write_recomposed,
    )
    from option_b import ARKIT_CHUNKS, ARKIT_SCENE, BASE, THRESHOLDS, judge
    from replica import floor_truth, load_mesh
    from replica_laps import SCENE_DIR, score

    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    th = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    out = ROOT / "out" / "option_c"
    out.mkdir(parents=True, exist_ok=True)
    base = [np.array(p) for p in json.loads((ROOT / "out/replica_apt0/walk_poses.json").read_text(encoding="utf-8"))["poses"]]
    seqs = json.loads((BASE / "sequences.json").read_text(encoding="utf-8"))
    truth = floor_truth(load_mesh(SCENE_DIR / "mesh.ply"))
    rows: dict = {}
    for name in ("one_lap", "three_laps"):
        source = BASE / f"{name}_independent"
        chunks = load_chunks(source / "chunks")
        x = log_scales(chunks, "chained")
        run = out / f"{name}_walls"
        write_recomposed(place_yaw_from_walls(chunks, x), x, source, run)
        r = score(run, truth, [base[i] for i in seqs[name]])
        rows[name] = {"walls": r}
        print(f"{name} walls: camera {r['camera_rms_m']:.2f} m, scale {r['scale_factor']:.2f}, rooms {r['rooms_levanta']}, IoU {r['floor_iou']:.2f}")
    chunks = load_chunks(ARKIT_CHUNKS / "chunks")
    x = log_scales(chunks, "chained")
    r = plan_and_score(place_yaw_from_walls(chunks, x), x, ARKIT_CHUNKS, out / "arkit_walls", ARKIT_SCENE,
                       arkit_floor_truth(*read_ply(ARKIT_SCENE / "41069021_3dod_mesh.ply")))
    rows["arkit"] = {"walls": r}
    print(f"arkit walls: scale {r.get('scale_factor')}, IoU {r.get('floor_iou')}, camera {r.get('traj_rms_m')}")
    ok, why = judge(th, rows, policy="walls")
    (out / "option_c.json").write_text(json.dumps({"thresholds": th, "rows": rows, "holds": ok, "why": why}, indent=1, default=float), encoding="utf-8")
    print("Verdict: " + ("HOLDS" if ok else "does not hold: " + "; ".join(why)))


if __name__ == "__main__":
    main()
