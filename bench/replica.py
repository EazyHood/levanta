"""The apartment benchmark ARKitScenes cannot give: a Replica flat, walked virtually.

Replica (Meta) ships real scanned apartments as meshes with colour.  Here:

1. **truth** from the mesh: the floor (up-facing triangles at floor height, 5 cm raster,
   holes filled), rooms as its connected parts after eroding 0.40 m (a doorway of up to
   0.8 m separates rooms), the area of each, and the doorways as the narrow necks between
   two rooms (pairs of rooms whose dilated parts touch);
2. **a walk** through every room: room centres visited in nearest-neighbour order, routed
   on the floor raster (BFS, 0.35 m from walls), 0.30 m per step, the camera 1.5 m above
   the floor looking along the way with a gentle look-around and a full turn in every
   room; rendered off-screen with Open3D at 720p and written as a 1 fps video;
3. **levanta video** on that video as if it were a phone, without and with the focal
   length (`--focal-px`, known exactly here);
4. **metrics**, fixed before running: rooms detected vs. real, area error per matched room
   and in total, doors found vs. doorways, camera RMS (the render poses are exact truth).

The renders and the meshes stay out of the repository (research licence); the numbers and
this script go in.

Usage: python bench/replica.py <replica_dir>/apartment_1 out/replica_apt1 [--max-views 24] [--res 1280x720]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import umeyama

CELL = 0.05
EYE_HEIGHT = 1.5
STEP = 0.30


# -- truth --------------------------------------------------------------------------------------


def load_mesh(path: Path):
    import open3d as o3d

    mesh = o3d.io.read_triangle_mesh(str(path), enable_post_processing=False)
    if not mesh.has_vertex_normals():
        mesh.compute_vertex_normals()
    return mesh


def floor_truth(mesh) -> dict:
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.triangles)
    tri = v[f]
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
    keep = facing_up & (np.abs(h - floor_h) < 0.12)
    horiz = [k for k in range(3) if k != up]
    pts = np.vstack([tri[keep][:, :, horiz].reshape(-1, 2), tri[keep][:, :, horiz].mean(axis=1)])
    lo = pts.min(axis=0) - 0.5
    ij = np.floor((pts - lo) / CELL).astype(int)
    grid = np.zeros(ij.max(axis=0) + 12, dtype=bool)
    grid[ij[:, 0], ij[:, 1]] = True
    grid = ndimage.binary_closing(grid, iterations=2)
    filled = ndimage.binary_fill_holes(grid)
    lab, k = ndimage.label(filled)
    if k > 1:
        sizes = ndimage.sum(filled, lab, range(1, k + 1))
        filled = lab == (int(np.argmax(sizes)) + 1)
    er = ndimage.binary_erosion(filled, iterations=int(round(0.40 / CELL)))
    lab, k = ndimage.label(er)
    rooms = []
    for i in range(1, k + 1):
        m = lab == i
        if m.sum() * CELL * CELL < 1.5:
            continue
        # grow the part back (within the floor) to get the room's own area
        grown = ndimage.binary_dilation(m, iterations=int(round(0.40 / CELL))) & filled
        cy, cx = ndimage.center_of_mass(m)
        rooms.append({"id": len(rooms), "area_m2": float(grown.sum() * CELL * CELL), "centre": (float(lo[0] + cy * CELL), float(lo[1] + cx * CELL)), "mask": grown})
    # doorways: pairs of rooms whose regions touch once grown by one more step
    doors = 0
    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            if (ndimage.binary_dilation(rooms[a]["mask"], iterations=2) & rooms[b]["mask"]).any():
                doors += 1
    return {"up": up, "sign": sign, "floor_h": floor_h, "horiz": horiz, "lo": lo, "filled": filled, "rooms": rooms, "doors": doors, "area_m2": float(filled.sum() * CELL * CELL)}


# -- the walk -----------------------------------------------------------------------------------


def _bfs_path(free: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    prev = {a: None}
    q = deque([a])
    H, W = free.shape
    while q:
        cur = q.popleft()
        if cur == b:
            break
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (cur[0] + d[0], cur[1] + d[1])
            if 0 <= nb[0] < H and 0 <= nb[1] < W and free[nb] and nb not in prev:
                prev[nb] = cur
                q.append(nb)
    if b not in prev:
        return []
    path = []
    cur = b
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def _nearest_free(free: np.ndarray, p: tuple[int, int]) -> tuple[int, int]:
    if free[p]:
        return p
    idx = np.argwhere(free)
    d = ((idx - np.array(p)) ** 2).sum(axis=1)
    return tuple(idx[int(np.argmin(d))])


def plan_walk(truth: dict) -> list[tuple[float, float, float]]:
    """(x, y, yaw) per step along the floor, room by room, with a full turn in each."""
    free = ndimage.binary_erosion(truth["filled"], iterations=int(round(0.35 / CELL)))
    lo = truth["lo"]
    centres = [(int((r["centre"][0] - lo[0]) / CELL), int((r["centre"][1] - lo[1]) / CELL)) for r in truth["rooms"]]
    centres = [_nearest_free(free, c) for c in centres]
    order = [0]
    left = set(range(1, len(centres)))
    while left:
        last = centres[order[-1]]
        nxt = min(left, key=lambda i: (centres[i][0] - last[0]) ** 2 + (centres[i][1] - last[1]) ** 2)
        order.append(nxt)
        left.remove(nxt)
    cells: list[tuple[int, int]] = []
    turns: set[int] = set()
    for k, i in enumerate(order):
        if k == 0:
            cells.append(centres[i])
        else:
            seg = _bfs_path(free, cells[-1], centres[i])
            cells += seg[1:] if seg else [centres[i]]
        turns.add(len(cells) - 1)
    # resample to STEP metres, keep a marker where a room centre is reached
    pts = np.array([(lo[0] + c[0] * CELL, lo[1] + c[1] * CELL) for c in cells])
    turn_pts = {tuple(pts[i]) for i in turns}
    walk = []
    acc = 0.0
    last = pts[0]
    walk.append((float(last[0]), float(last[1]), None))
    for p in pts[1:]:
        d = float(np.linalg.norm(p - last))
        acc += d
        if acc >= STEP or tuple(p) in turn_pts:
            walk.append((float(p[0]), float(p[1]), "turn" if tuple(p) in turn_pts else None))
            acc = 0.0
        last = p
    # yaw from the direction of travel, smoothed, with a gentle look-around; a full turn at
    # every room centre
    out = []
    yaw = 0.0
    for k, (x, y, tag) in enumerate(walk):
        if k + 1 < len(walk):
            dx, dy = walk[k + 1][0] - x, walk[k + 1][1] - y
            if abs(dx) + abs(dy) > 1e-6:
                target = math.atan2(dy, dx)
                dyaw = (target - yaw + math.pi) % (2 * math.pi) - math.pi
                yaw += 0.5 * dyaw
        look = 0.6 * math.sin(k / 6.0)
        out.append((x, y, yaw + look))
        if tag == "turn":
            for j in range(12):
                out.append((x, y, yaw + 2 * math.pi * (j + 1) / 12))
    return out


# -- rendering --------------------------------------------------------------------------------


def render_walk(mesh, truth: dict, walk, out_dir: Path, res: tuple[int, int], fov_deg: float = 70.0) -> tuple[list[Path], list[np.ndarray], np.ndarray]:
    """Frames, camera-to-world poses (OpenCV convention: x right, y down, z forward) and K."""
    import open3d as o3d
    from open3d.visualization import rendering

    W, H = res
    out_dir.mkdir(parents=True, exist_ok=True)
    r = rendering.OffscreenRenderer(W, H)
    mat = rendering.MaterialRecord()
    mat.shader = "defaultUnlit"
    r.scene.add_geometry("mesh", mesh, mat)
    r.scene.set_background([0.02, 0.02, 0.02, 1.0])
    r.scene.scene.set_sun_light([0.3, -0.5, -0.8], [1.0, 1.0, 1.0], 60000)
    r.scene.scene.enable_sun_light(False)
    up, sign, horiz = truth["up"], truth["sign"], truth["horiz"]
    fy = fx = (H / 2) / math.tan(math.radians(fov_deg) / 2) if H < W else (W / 2) / math.tan(math.radians(fov_deg) / 2)
    K = np.array([[fx, 0, W / 2], [0, fy, H / 2], [0, 0, 1.0]])
    r.scene.camera.set_projection(fov_deg, W / H, 0.05, 50.0, rendering.Camera.FovType.Horizontal if W >= H else rendering.Camera.FovType.Vertical)
    frames, poses = [], []
    for k, (x, y, yaw) in enumerate(walk):
        eye = np.zeros(3)
        eye[horiz[0]], eye[horiz[1]] = x, y
        eye[up] = truth["floor_h"] + sign * EYE_HEIGHT
        fwd = np.zeros(3)
        fwd[horiz[0]], fwd[horiz[1]] = math.cos(yaw), math.sin(yaw)
        fwd[up] = -0.12 * sign  # a slight look down, to see where walls meet the floor
        fwd /= np.linalg.norm(fwd)
        upv = np.zeros(3)
        upv[up] = sign
        r.scene.camera.look_at(eye + fwd, eye, upv)
        img = np.asarray(r.render_to_image())
        p = out_dir / f"frame_{k:05d}.png"
        o3d.io.write_image(str(p), o3d.geometry.Image(img))
        frames.append(p)
        # camera-to-world in OpenCV convention
        z = fwd
        xax = np.cross(z, upv)
        xax /= np.linalg.norm(xax)
        yax = np.cross(z, xax)
        T = np.eye(4)
        T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = xax, yax, z, eye
        poses.append(T)
    return frames, poses, K


def frames_to_video(frames: list[Path], path: Path, fps: float = 1.0) -> Path:
    import cv2

    first = cv2.imread(str(frames[0]))
    h, w = first.shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(cv2.imread(str(f)))
    vw.release()
    return path


# -- levanta and the metrics ---------------------------------------------------------------------


def run_levanta(video: Path, out: Path, max_views: int, focal_px: float | None) -> Path:
    cmd = [sys.executable, "-m", "levanta.cli", "video", str(video), "-o", str(out), "--fps", "1", "--max-views", str(max_views), "--lang", "en", "--paper", "A3"]
    if focal_px:
        cmd += ["--focal-px", f"{focal_px:.2f}"]
    out.mkdir(parents=True, exist_ok=True)
    with (out.parent / f"{out.name}.log").open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    return out


def evaluate(run: Path, truth: dict, poses: list[np.ndarray], walk_len: int) -> dict:
    from shapely.geometry import Point, Polygon

    from levanta.plan.types import FloorPlan
    from levanta.scene import PointCloud

    if not (run / "plan.json").exists():
        return {"ok": False}
    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    fp = FloorPlan.from_json(run / "plan.json")
    idx = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
    cloud = PointCloud.load_ply(run / "plan_cloud.ply")
    cams = cloud.cameras[:, :3, 3]
    # the video runs at 1 fps: frame k of the video is walk step k
    truth_c = np.array([poses[min(int(round(f["time_s"])), len(poses) - 1)][:3, 3] for f in idx])
    s, R, t, rms = umeyama(cams, truth_c)
    h = truth["horiz"]
    lev_rooms = []
    for r in plan["rooms"]:
        pts = np.array([[x, y, 0.0] for x, y in r["polygon"]])
        w = s * (R @ pts.T).T + t
        lev_rooms.append(Polygon([(p[h[0]], p[h[1]]) for p in w]).buffer(0))
    # match every true room to the levanta room containing its centre
    matched = []
    for tr in truth["rooms"]:
        c = Point(tr["centre"])
        hit = [(i, g) for i, g in enumerate(lev_rooms) if g.contains(c)]
        if hit:
            i, g = hit[0]
            matched.append({"truth_room": tr["id"], "levanta_room": i, "truth_m2": tr["area_m2"], "levanta_m2": float(Polygon(plan["rooms"][i]["polygon"]).area) * s * s, "area_error_pct": (float(Polygon(plan["rooms"][i]["polygon"]).area) * s * s - tr["area_m2"]) / tr["area_m2"] * 100.0})
    lev_total = sum(Polygon(r["polygon"]).area for r in plan["rooms"])
    return {
        "ok": True,
        "scale_factor": s,
        "camera_rms_m": rms,
        "rooms_levanta": len(plan["rooms"]),
        "rooms_truth": len(truth["rooms"]),
        "rooms_matched": len(matched),
        "doors_levanta": sum(1 for o in plan["openings"] if o["kind"] == "door"),
        "doorways_truth": truth["doors"],
        "area_total_error_pct": (lev_total - truth["area_m2"]) / truth["area_m2"] * 100.0,
        "area_total_error_scaled_pct": (lev_total * s * s - truth["area_m2"]) / truth["area_m2"] * 100.0,
        "per_room": matched,
        "walls": len(plan["walls"]),
        "unreliable": list(fp.unreliable) if fp.unreliable else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--max-views", type=int, default=24)
    ap.add_argument("--res", default="1280x720")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--eval-only", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    W, H = (int(x) for x in args.res.split("x"))
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    mesh = load_mesh(args.scene / "mesh.ply")
    print(f"mesh: {len(mesh.vertices):,} vertices, {len(mesh.triangles):,} faces, colours {mesh.has_vertex_colors()}, textures {mesh.has_textures()} ({time.time() - t0:.0f} s)")
    truth = floor_truth(mesh)
    print(f"truth: floor {truth['area_m2']:.1f} m2, {len(truth['rooms'])} rooms {[round(r['area_m2'], 1) for r in truth['rooms']]}, {truth['doors']} doorways, up axis {truth['up']}")
    video = args.out / "walk.mp4"
    poses_file = args.out / "walk_poses.json"
    if not args.eval_only:
        walk = plan_walk(truth)
        print(f"walk: {len(walk)} steps ({len(walk) / 60:.1f} min at 1 fps)")
        frames, poses, K = render_walk(mesh, truth, walk, args.out / "render", (W, H))
        frames_to_video(frames, video)
        poses_file.write_text(json.dumps({"K": K.tolist(), "poses": [p.tolist() for p in poses]}), encoding="utf-8")
        print(f"rendered {len(frames)} frames at {W}x{H} -> {video} ({time.time() - t0:.0f} s)")
        for f in frames:  # the disk rule: no intermediates left behind
            f.unlink()
    meta = json.loads(poses_file.read_text(encoding="utf-8"))
    K = np.array(meta["K"])
    poses = [np.array(p) for p in meta["poses"]]
    if args.render_only:
        return
    # levanta sees frames 1024 px wide: scale the exact focal to that
    f_frame = K[0, 0] * min(1024, W) / W
    results = {"scene": args.scene.name, "truth": {"area_m2": truth["area_m2"], "rooms": [{"id": r["id"], "area_m2": r["area_m2"]} for r in truth["rooms"]], "doorways": truth["doors"]}, "walk_steps": len(poses), "res": f"{W}x{H}"}
    for name, focal in (("noK", None), ("withK", f_frame)):
        run = args.out / name
        if not args.eval_only:
            run_levanta(video, run, args.max_views, focal)
        r = evaluate(run, truth, poses, len(poses))
        results[name] = r
        print(f"  {name}: {json.dumps({k: v for k, v in r.items() if k != 'per_room'})}")
        for m in r.get("per_room", []):
            print(f"      room {m['truth_room']}: {m['truth_m2']:.1f} m2 -> levanta {m['levanta_m2']:.1f} m2 ({m['area_error_pct']:+.0f} %)")
    (args.out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
