"""Option B, judged: chunks placed by registering their shared frames' pixels.

The protocol is in bench/results/pose_drift_options_2026-09-24.md, written before the baselines
existed.  Two steps, in this order, and the second refuses to run without the first:

1. ``--thresholds``: read the focal baselines (the rendered flat, one lap and three, through the
   pipeline with its true focal) and turn the page's recipes into numbers, written to
   ``bench/results/option_b_thresholds_2026-09-24.json``, which is committed before step 2.
2. ``--judge``: recompose, on the CPU, the chunks solved independently (the rendered flat with its
   focal, and ARKitScenes 41069021 at 1 fps with the network's focal, the product's row there)
   twice: chained as today and by B.  Score each and apply the committed numbers to B.

No GPU in either step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

BASE = ROOT / "out" / "replica_laps_focal"
ARKIT_CHUNKS = ROOT / "out" / "chain_exp" / "fps_1" / "41069021" / "noK"
ARKIT_SCENE = Path("C:/Users/jhona/arkitscenes_data/raw/Validation/41069021")
THRESHOLDS = HERE / "results" / "option_b_thresholds_2026-09-24.json"
OUT = ROOT / "out" / "option_b"
ONE_LAP_SLACK = 0.10  # m, the page's
THREE_LAP_OVER_ONE = 0.22  # m, the page's recipe
THREE_LAP_FRACTION = 0.6  # the supervisor's recipe, taken together with the page's
MAX_ROOMS = 3
ARKIT_IOU = 0.60


def thresholds() -> dict:
    runs = json.loads((BASE / "replica_laps.json").read_text(encoding="utf-8"))["runs"]
    one, three = runs["one_lap"]["camera_rms_m"], runs["three_laps"]["camera_rms_m"]
    return {
        "baseline": {"one_lap_camera_m": one, "three_laps_camera_m": three,
                     "one_lap_rooms": runs["one_lap"]["rooms_levanta"], "three_laps_rooms": runs["three_laps"]["rooms_levanta"]},
        "three_laps_camera_at_most_m": min(one + THREE_LAP_OVER_ONE, THREE_LAP_FRACTION * three),
        "three_laps_rooms_at_most": MAX_ROOMS,
        "one_lap_camera_at_most_m": one + ONE_LAP_SLACK,
        "arkit_iou_at_least": ARKIT_IOU,
    }


def judge(th: dict, rows: dict) -> tuple[bool, list[str]]:
    why = []
    three, one, ark = rows["three_laps"]["points"], rows["one_lap"]["points"], rows["arkit"]["points"]
    if three["camera_rms_m"] > th["three_laps_camera_at_most_m"]:
        why.append(f"three laps: camera error {three['camera_rms_m']:.2f} m over {th['three_laps_camera_at_most_m']:.2f}")
    if three["rooms_levanta"] > th["three_laps_rooms_at_most"]:
        why.append(f"three laps: {three['rooms_levanta']} rooms, more than {th['three_laps_rooms_at_most']}")
    if one["camera_rms_m"] > th["one_lap_camera_at_most_m"]:
        why.append(f"one lap: camera error {one['camera_rms_m']:.2f} m over {th['one_lap_camera_at_most_m']:.2f}")
    if (ark.get("floor_iou") or 0.0) < th["arkit_iou_at_least"]:
        why.append(f"ARKitScenes 1 fps: floor IoU {ark.get('floor_iou'):.2f} under {th['arkit_iou_at_least']}")
    return not why, why


def main() -> None:
    from arkitscenes import floor_truth as arkit_floor_truth
    from arkitscenes import read_ply
    from chain_policies import (
        load_chunks,
        log_scales,
        place,
        place_by_points,
        plan_and_score,
        write_recomposed,
    )
    from replica import floor_truth, load_mesh
    from replica_laps import SCENE_DIR, score

    ap = argparse.ArgumentParser()
    ap.add_argument("--thresholds", action="store_true")
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if args.thresholds:
        th = thresholds()
        THRESHOLDS.write_text(json.dumps(th, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(th, indent=1))
        return
    if not args.judge:
        ap.error("--thresholds first, commit the file, then --judge")
    if not THRESHOLDS.exists():
        sys.exit(f"{THRESHOLDS} is missing: the numbers are fixed and committed before B runs")
    th = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    base = [np.array(p) for p in json.loads((ROOT / "out/replica_apt0/walk_poses.json").read_text(encoding="utf-8"))["poses"]]
    seqs = json.loads((BASE / "sequences.json").read_text(encoding="utf-8"))
    truth = floor_truth(load_mesh(SCENE_DIR / "mesh.ply"))
    rows: dict = {}
    for name in ("one_lap", "three_laps"):
        source = BASE / f"{name}_independent"
        chunks = load_chunks(source / "chunks")
        poses = [base[i] for i in seqs[name]]
        rows[name] = {}
        for policy in ("chained", "points"):
            if policy == "chained":
                x = log_scales(chunks, "chained")
                solved = place(chunks, x)
            else:
                solved, x = place_by_points(chunks)
            run = OUT / f"{name}_{policy}"
            write_recomposed(solved, x, source, run)
            rows[name][policy] = score(run, truth, poses)
            r = rows[name][policy]
            print(f"{name} {policy}: camera {r['camera_rms_m']:.2f} m, scale {r['scale_factor']:.2f}, rooms {r['rooms_levanta']}, IoU {r['floor_iou']:.2f}")
    arkit_truth = arkit_floor_truth(*read_ply(ARKIT_SCENE / "41069021_3dod_mesh.ply"))
    chunks = load_chunks(ARKIT_CHUNKS / "chunks")
    rows["arkit"] = {}
    for policy in ("chained", "points"):
        if policy == "chained":
            x = log_scales(chunks, "chained")
            solved = place(chunks, x)
        else:
            solved, x = place_by_points(chunks)
        r = plan_and_score(solved, x, ARKIT_CHUNKS, OUT / f"arkit_{policy}", ARKIT_SCENE, arkit_truth)
        rows["arkit"][policy] = r
        print(f"arkit {policy}: scale {r.get('scale_factor')}, IoU {r.get('floor_iou')}, camera {r.get('traj_rms_m')}")
    ok, why = judge(th, rows)
    (OUT / "option_b.json").write_text(json.dumps({"thresholds": th, "rows": rows, "holds": ok, "why": why}, indent=1, default=float), encoding="utf-8")
    print("Verdict: " + ("HOLDS" if ok else "does not hold: " + "; ".join(why)))


if __name__ == "__main__":
    main()
