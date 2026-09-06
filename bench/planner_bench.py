"""The planner on every scene at once: one command, seven rows, no network and no GPU.

Two rounds in a row a planner change that helped one scene quietly hurt another, and the
regression lived until someone re-ran the TUM by hand.  This replans clouds that are
already on disk and scores each against its own truth, so a change is judged on all of
them together.

Scenes:

- five ARKitScenes rooms — the clouds `levanta video` produced, the LiDAR mesh as truth,
  and the ARKit trajectory to place the plan in the mesh's frame;
- the TUM office — no mesh, so it is scored against the published example, which is what
  a regression there would break;
- the Replica flat with a *perfect* cloud (exact depth, exact poses).  Exact is not
  complete: the camera walks at 1.5 m and furniture hides the rest, so floor points land
  on only 36 % of the flat's floor and everything below 2.5 m covers 53 %, even though
  the path passes within 2 m of 80-94 % of every room.  This is the planner with no
  network error in the way, not the planner with full information.

Metrics per scene: wall recall and precision against the mesh (how much of the real wall
became a wall, and how much of what was drawn is wall), rooms found vs. real, doors found
vs. doorways, and total room area against the floor.

**One planner change per round.**  Round 4 shipped two changes at once, a new scoring in
`snap_edges_to_walls` and a longer snap reach; the pair helped, so both were kept.  Round 6
swept them separately and found the scoring was worse or equal on all seven scenes and the
reach was the whole gain.  A useless change had been sitting in the planner for two rounds
because the bench was run once, over the sum.  So: change one thing, run this, keep it only
if the table says so.  If two changes are unavoidable, sweep each alone as well.

Usage:
    python bench/planner_bench.py                    # the table
    python bench/planner_bench.py --json out.json    # machine readable, for CI
    python bench/planner_bench.py --set room_snap_dist=1.0 min_wall_len=0.3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import read_traj, umeyama
from replica import CELL, floor_truth, load_mesh, partition_mask, wall_scores, wall_truth

ROOT = Path(__file__).resolve().parent.parent
ARKIT = Path("C:/Users/jhona/arkitscenes_data/raw/Validation")
REPLICA = Path("C:/Users/jhona/replica_data")

# what the published example shows; a change that moves these broke the TUM
TUM_REFERENCE = {"walls": 3, "rooms": 1, "openings": 1, "area_m2": 24.49, "wall_lengths": [5.80, 4.93, 4.07]}


def scene_list() -> list[dict]:
    out = []
    rows = json.loads((ROOT / "bench/results/arkitscenes_2026-09-05_round4.json").read_text(encoding="utf-8"))
    # replanning a saved cloud loses what the *reconstruction* knew about itself, and that
    # is exactly what tells a scene levanta refuses to stand behind from an ordinary one;
    # carry the two numbers `FloorPlan.unreliable` reads back from the run that made it
    runs = {r["video_id"]: r["noK"] for r in json.loads((ROOT / "out/bench3/results.json").read_text(encoding="utf-8"))}
    for r in rows:
        vid = r["video_id"]
        cloud = ROOT / "out/bench3" / vid / "noK" / "plan_cloud.ply"
        mesh = ARKIT / vid / f"{vid}_3dod_mesh.ply"
        if cloud.exists() and mesh.exists():
            run = runs.get(vid, {})
            out.append({"name": vid, "cloud": cloud, "mesh": mesh, "kind": "arkit", "traj": ARKIT / vid / "lowres_wide.traj", "index": cloud.parent / "frames" / "index.json",
                        "recon": {k: run[k] for k in ("chunk_scales", "mask_fraction") if k in run}})
    tum = ROOT / "out/tum_raw.ply"
    if tum.exists():
        out.append({"name": "TUM fr1/room", "cloud": tum, "kind": "reference", "reference": TUM_REFERENCE})
    apt = ROOT / "out/replica_apt0/ideal/plan_cloud.ply"
    if apt.exists() and (REPLICA / "apartment_0/mesh.ply").exists():
        out.append({"name": "Replica apt_0 (perfect cloud)", "cloud": apt, "mesh": REPLICA / "apartment_0/mesh.ply", "kind": "replica", "poses": ROOT / "out/replica_apt0/walk_poses.json", "index": apt.parent / "frames" / "index.json"})
    return out


def truth_cameras(scene: dict, idx: list[dict]) -> np.ndarray | None:
    """Where the cameras really were, one per kept frame."""
    if scene["kind"] == "arkit":
        ts, centres = read_traj(scene["traj"])
        offs = json.loads((ROOT / "out/bench3/results.json").read_text(encoding="utf-8"))
        off = next((r["noK"].get("time_offset_s", 0.0) for r in offs if r["video_id"] == scene["name"]), 0.0)
        return centres[[int(np.argmin(np.abs(ts - (ts[0] + off + f["time_s"])))) for f in idx]]
    if scene["kind"] == "replica":
        meta = json.loads(scene["poses"].read_text(encoding="utf-8"))
        poses = [np.array(p) for p in meta["poses"]]
        return np.array([poses[min(round(f["time_s"]), len(poses) - 1)][:3, 3] for f in idx])
    return None


def run_scene(scene: dict, overrides: dict) -> dict:
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan
    from levanta.scene import PointCloud

    pc = PointCloud.load_ply(scene["cloud"])
    res = extract_floor_plan(pc, PlanOptions(**overrides))
    plan = res.plan.label_openings()
    plan.meta.update(scene.get("recon", {}))
    stages = plan.meta.get("debug", {}).get("rooms", {})
    areas = [r.shapely.area for r in plan.rooms]
    row = {
        "scene": scene["name"],
        "walls": len(plan.walls),
        "rooms": len(plan.rooms),
        "doors": sum(1 for o in plan.openings if o.kind == "door"),
        "area_m2": float(sum(areas)),
        "room_stages": stages,
        "unreliable": plan.unreliable is not None,
    }
    if scene["kind"] == "reference":
        ref = scene["reference"]
        row.update({
            "truth_rooms": ref["rooms"], "truth_doors": ref["openings"], "truth_area_m2": ref["area_m2"],
            "area_error_pct": (row["area_m2"] - ref["area_m2"]) / ref["area_m2"] * 100.0,
            "walls_expected": ref["walls"],
            "wall_lengths": sorted((round(w.length, 2) for w in plan.walls), reverse=True),
        })
        return row
    mesh = load_mesh(scene["mesh"])
    truth = floor_truth(mesh)
    row.update({"truth_rooms": len(truth["rooms"]), "truth_doors": truth["doors"], "truth_area_m2": truth["area_m2"]})
    row["area_error_pct"] = (row["area_m2"] - truth["area_m2"]) / truth["area_m2"] * 100.0
    idx = json.loads(scene["index"].read_text(encoding="utf-8"))
    dst = truth_cameras(scene, idx)
    cams = res.cloud.cameras[:, :3, 3] if res.cloud.cameras is not None else None
    if dst is not None and cams is not None and len(cams) == len(dst) and len(cams) >= 5:
        s, R, t, rms = umeyama(cams, dst)
        row["camera_rms_m"] = rms
        walls = [{"a": w.a, "b": w.b, "thickness": w.thickness} for w in plan.walls]
        wt = wall_truth(mesh, truth)
        pm = partition_mask(truth, wt)
        sc = wall_scores(walls, truth, wt, (s, R, t), parts={"partition": pm, "facade": wt & ~pm})
        row["wall_recall"] = sc["wall_recall"]
        row["wall_precision"] = sc["wall_precision"]
        row["partition_recall"] = sc["recall_partition"]
        row["facade_recall"] = sc["recall_facade"]
        row.update(match_rooms(plan, truth, (s, R, t)))
    return row


def _outside_floor(g, truth: dict) -> float:
    """Per cent of a detected room that lands where the mesh has no floor at all.

    A room can be too big for two different reasons and they need different fixes: it
    swallowed the room next door (area over real floor), or it spilled into space that
    was never a room (area over nothing).
    """
    from shapely import contains_xy

    if g.is_empty:
        return 0.0
    lo, filled = truth["lo"], truth["filled"]
    x0, y0, x1, y1 = g.bounds
    xs = np.arange(x0, x1 + CELL, CELL)
    ys = np.arange(y0, y1 + CELL, CELL)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    inside = contains_xy(g, gx.ravel(), gy.ravel())
    if not inside.any():
        return 0.0
    iy = np.clip(((gx.ravel()[inside] - lo[0]) / CELL).astype(int), 0, filled.shape[0] - 1)
    ix = np.clip(((gy.ravel()[inside] - lo[1]) / CELL).astype(int), 0, filled.shape[1] - 1)
    return float(100.0 * (~filled[iy, ix]).mean())


def match_rooms(plan, truth: dict, sim) -> dict:
    """Room by room against its own truth, because a total can be right for two wrong reasons.

    Each true room owns a territory: the floor cells closer to its core than to any other
    room's.  A detected room is placed in the mesh's frame and the true room it covers most
    is its match, so the pairing does not depend on a centre falling inside a polygon.

    Areas are reported in the plan's **own** metres, never rescaled by the alignment, so
    they add up to the total column and still carry levanta's metric error.  Two failures
    read differently here: a *fusion* is one detected room matching two true rooms, which
    inflates the total while both rooms are wrong; a short outline is a room matched 1:1
    that covers only part of its territory.
    """
    from shapely import contains_xy
    from shapely.geometry import Polygon

    s, R, t = sim
    h, lo = truth["horiz"], truth["lo"]
    detected, own_m2, off_floor = [], [], []
    for r in plan.rooms:
        pts = np.array([[x, y, 0.0] for x, y in r.polygon])
        w = s * (R @ pts.T).T + t
        g = Polygon([(p[h[0]], p[h[1]]) for p in w]).buffer(0)
        detected.append(g)
        own_m2.append(float(r.shapely.area))
        off_floor.append(_outside_floor(g, truth))
    per_room, best_of = [], {}
    for tr in truth["rooms"]:
        cy, cx = np.nonzero(tr["territory"])
        xs, ys = lo[0] + cy * CELL, lo[1] + cx * CELL
        cover = [float(contains_xy(g, xs, ys).mean()) if not g.is_empty else 0.0 for g in detected]
        k = int(np.argmax(cover)) if cover else -1
        truth_m2 = tr["territory_m2"]
        if k < 0 or cover[k] < 0.20:
            per_room.append({"truth_m2": truth_m2, "levanta_m2": None, "covered_pct": 100.0 * max(cover, default=0.0), "error_pct": None})
            continue
        best_of.setdefault(k, []).append(tr["id"])
        per_room.append({"truth_m2": truth_m2, "levanta_m2": own_m2[k], "covered_pct": 100.0 * cover[k], "outside_pct": off_floor[k], "error_pct": (own_m2[k] - truth_m2) / truth_m2 * 100.0})
    return {
        "per_room": per_room,
        "rooms_matched": len(best_of),
        "rooms_fused": sum(1 for v in best_of.values() if len(v) > 1),
        "rooms_missed": sum(1 for m in per_room if m["levanta_m2"] is None),
        "rooms_spurious": len(detected) - len(best_of),
    }


def _pct(row: dict, key: str) -> str:
    return "—" if row.get(key) is None else f"{100 * row[key]:.0f} %"


def fmt(rows: list[dict]) -> str:
    head = "| scene | truth: floor / rooms / doorways | walls | rooms | doors | area | wall recall | partition recall | wall precision |"
    out = [head, "|" + "---|" * 9]
    for r in rows:
        exp = f" (ref {r['walls_expected']})" if "walls_expected" in r else ""
        flag = " ⚠" if r.get("unreliable") else ""
        out.append(
            f"| {r['scene']}{flag} | {r['truth_area_m2']:.1f} m² / {r['truth_rooms']} / {r['truth_doors']} "
            f"| {r['walls']}{exp} | {r['rooms']} | {r['doors']} | {r['area_m2']:.1f} m² ({r['area_error_pct']:+.0f} %) "
            f"| {_pct(r, 'wall_recall')} | {_pct(r, 'partition_recall')} | {_pct(r, 'wall_precision')} |"
        )
    rooms = [(r, m) for r in rows for m in r.get("per_room", [])]
    if rooms:
        out += ["", "| scene | room (truth) | levanta | error | of the room covered | off the floor |", "|" + "---|" * 6]
        for r, m in rooms:
            got = "not found" if m["levanta_m2"] is None else f"{m['levanta_m2']:.1f} m²"
            err = "—" if m["error_pct"] is None else f"{m['error_pct']:+.0f} %"
            off = "—" if m["levanta_m2"] is None else f"{m['outside_pct']:.0f} %"
            out.append(f"| {r['scene']} | {m['truth_m2']:.1f} m² | {got} | {err} | {m['covered_pct']:.0f} % | {off} |")
    return "\n".join(out)


def summary(rows: list[dict]) -> str:
    """The averages, over the scenes the plan does not already refuse to stand behind.

    47430051 reconstructs 3 % of its walls and levanta stamps it NOT RECONSTRUCTIBLE; its
    −100 % is the warning working, not the planner failing, and averaging it in moves every
    mean by a scene levanta never claimed.  It is reported apart, and it still has to stay
    flagged: a sweep that silences the warning would be caught here.
    """
    good = [r for r in rows if not r.get("unreliable")]
    bad = [r for r in rows if r.get("unreliable")]
    out = []
    if good:
        area = np.mean([abs(r["area_error_pct"]) for r in good])
        rec = [r["wall_recall"] for r in good if r.get("wall_recall") is not None]
        found = sum(r["rooms_matched"] for r in good if "rooms_matched" in r)
        want = sum(r["truth_rooms"] for r in good if "rooms_matched" in r)
        out.append(f"{len(good)} scenes levanta stands behind: area error {area:.0f} % on average"
                   + (f", wall recall {100 * np.mean(rec):.0f} %" if rec else "")
                   + (f", rooms {found} of {want}" if want else ""))
    for r in bad:
        out.append(f"apart, flagged unreliable by levanta itself: {r['scene']}, area {r['area_error_pct']:+.0f} %, wall recall {100 * (r.get('wall_recall') or 0):.0f} %")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--set", nargs="*", default=[], help="PlanOptions overrides, e.g. room_snap_dist=1.0")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    overrides: dict = {}
    for item in args.set:
        k, v = item.split("=", 1)
        if v in ("True", "False"):
            overrides[k] = v == "True"
        elif v.replace("-", "").isdigit():
            overrides[k] = int(v)  # an int option (max_rays) breaks if it arrives as a float
        elif "." in v and v.replace("-", "").replace(".", "").isdigit():
            overrides[k] = float(v)
        else:
            overrides[k] = v
    rows = []
    for scene in scene_list():
        if args.only and scene["name"] not in args.only:
            continue
        row = run_scene(scene, overrides)
        rows.append(row)
        print(f"  {row['scene']}: {json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items() if k not in ('scene', 'per_room', 'room_stages')})}")
        for m in row.get("per_room", []):
            got = "not found" if m["levanta_m2"] is None else f"{m['levanta_m2']:.1f} m² ({m['error_pct']:+.0f} %)"
            spill = "" if m["levanta_m2"] is None else f", {m['outside_pct']:.0f} % of it off the floor"
            print(f"      room of {m['truth_m2']:.1f} m² -> {got}, {m['covered_pct']:.0f} % of it covered{spill}")
        if row.get("room_stages"):
            print(f"      how the rooms were found: {json.dumps(row['room_stages'])}")
    print()
    print(fmt(rows))
    print()
    print(summary(rows))
    if args.json:
        args.json.write_text(json.dumps({"overrides": overrides, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
