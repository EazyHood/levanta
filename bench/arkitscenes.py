"""levanta against ground truth: ARKitScenes (real iPhone walks + LiDAR mesh + ARKit poses).

For every scene directory (``raw/Validation/<video_id>/`` with ``<video_id>.mov``,
``<video_id>_3dod_mesh.ply``, ``lowres_wide.traj`` and ``vga_wide_intrinsics/``):

1. truth from the LiDAR mesh: the floor polygon (up-facing triangles at floor height,
   unioned), its area, and its rooms (connected parts after eroding 0.45 m, so an open
   doorway of up to 0.9 m separates two rooms);
2. ``levanta video`` on the .mov, twice: scale from the network alone, and with the
   focal length ARKit recorded for the camera (``--focal-px``);
3. levanta's cameras are aligned to ARKit's trajectory with a similarity (Umeyama):
   the fitted scale is the scale error, the residual says whether the alignment is
   trustworthy; levanta's rooms are carried into the mesh frame and compared with the
   floor polygon (IoU, area error, room count, doors).

Metrics fixed before the first run: scale factor s (1.00 ideal), total area error in %,
floor IoU, rooms detected vs. rooms in the truth, doors detected (no truth), trajectory
RMS after alignment in metres.

Usage: python bench/arkitscenes.py data/arkitscenes/raw/Validation out/bench [--max-views 24]
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

# -- PLY (binary little endian or ascii; vertices x y z [...], faces as lists) ----------------


def read_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as fh:
        header = []
        while True:
            line = fh.readline().decode("ascii", "replace").strip()
            header.append(line)
            if line == "end_header":
                break
        fmt = next(ln.split()[1] for ln in header if ln.startswith("format"))
        elements = []
        for ln in header:
            if ln.startswith("element"):
                _, name, n = ln.split()
                elements.append([name, int(n), []])
            elif ln.startswith("property"):
                elements[-1][2].append(ln.split()[1:])
        if fmt == "ascii":
            data = fh.read().decode("ascii").split("\n")
            pos = 0
            out = {}
            for name, n, props in elements:
                rows = data[pos : pos + n]
                pos += n
                if name == "vertex":
                    out["vertex"] = np.array([[float(x) for x in r.split()[:3]] for r in rows])
                elif name == "face":
                    out["face"] = np.array([[int(x) for x in r.split()[1:4]] for r in rows])
            return out["vertex"], out["face"]
        endian = "<" if fmt == "binary_little_endian" else ">"
        types = {"float": "f", "float32": "f", "double": "d", "uchar": "B", "uint8": "B", "char": "b", "int": "i", "int32": "i", "uint": "I", "uint32": "I", "short": "h", "ushort": "H"}
        out = {}
        for name, n, props in elements:
            if all(p[0] != "list" for p in props):
                fmt_row = endian + "".join(types[p[0]] for p in props)
                size = struct.calcsize(fmt_row)
                buf = fh.read(size * n)
                arr = np.frombuffer(buf, dtype=np.dtype([(f"p{i}", endian + types[p[0]]) for i, p in enumerate(props)]))
                if name == "vertex":
                    out["vertex"] = np.c_[arr["p0"], arr["p1"], arr["p2"]].astype(np.float64)
            else:
                faces = []
                for _ in range(n):
                    row = []
                    for p in props:
                        if p[0] == "list":
                            cnt = struct.unpack(endian + types[p[1]], fh.read(struct.calcsize(types[p[1]])))[0]
                            idx_fmt = endian + types[p[2]] * cnt
                            row.append(struct.unpack(idx_fmt, fh.read(struct.calcsize(idx_fmt))))
                        else:
                            fh.read(struct.calcsize(types[p[0]]))
                    faces.append(row[0][:3])
                if name == "face":
                    out["face"] = np.array(faces, dtype=np.int64)
        return out["vertex"], out["face"]


# -- truth from the mesh ------------------------------------------------------------------


def floor_truth(vertices: np.ndarray, faces: np.ndarray) -> dict:
    """Floor polygon (in the mesh's horizontal plane), its area and its rooms."""
    tri = vertices[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(n, axis=1)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    # which axis is up: the one with the most triangle area pointing along it
    scores = [float(area[np.abs(n[:, k]) > 0.9].sum()) for k in range(3)]
    up = int(np.argmax(scores))
    sign = 1.0 if float((n[:, up] * area).sum()) >= 0 else -1.0
    h = tri[:, :, up].mean(axis=1)
    facing_up = n[:, up] * sign > 0.9
    hist, edges = np.histogram(h[facing_up], bins=200, weights=area[facing_up])
    # the floor is the lowest strong band of up-facing area
    strong = np.nonzero(hist > 0.15 * hist.max())[0]
    floor_h = float(edges[strong[0]] + 0.5 * (edges[1] - edges[0]))
    keep = facing_up & (np.abs(h - floor_h) < 0.12)
    horiz = [k for k in range(3) if k != up]
    polys = []
    for t in tri[keep]:
        pts = [(float(p[horiz[0]]), float(p[horiz[1]])) for p in t]
        try:
            pg = Polygon(pts)
            if pg.is_valid and pg.area > 1e-8:
                polys.append(pg.buffer(0.01))
        except Exception:
            continue
    floor = unary_union(polys).buffer(-0.01).buffer(0)
    if isinstance(floor, MultiPolygon):
        floor = max(floor.geoms, key=lambda g: g.area)
    seen = float(floor.area)  # floor the LiDAR actually saw (furniture excluded)
    # the floor plate: holes left by furniture and by gaps in the scan are filled
    floor = Polygon(floor.exterior.coords, [h.coords for h in floor.interiors if Polygon(h.coords).area > 4.0]).buffer(0)
    rooms = floor.buffer(-0.40)
    parts = [g for g in (rooms.geoms if hasattr(rooms, "geoms") else [rooms]) if g.area > 1.0]  # a 2 x 2 m bathroom survives the erosion
    return {"up": up, "sign": sign, "floor_h": floor_h, "horiz": horiz, "floor": floor, "area": float(floor.area), "seen_area": seen, "rooms": len(parts)}


# -- ARKit trajectory and intrinsics ------------------------------------------------------------


def read_traj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(timestamps, camera centres in the ARKit world) from lowres_wide.traj
    (timestamp, rotation vector xyz, translation xyz of world->camera)."""
    rows = np.loadtxt(path)
    ts = rows[:, 0]
    rvec, tvec = rows[:, 1:4], rows[:, 4:7]
    centres = []
    for r, tt in zip(rvec, tvec, strict=True):
        th = np.linalg.norm(r)
        k = r / th if th > 1e-12 else np.array([1.0, 0, 0])
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        R = np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K
        centres.append(-R.T @ tt)
    return ts, np.array(centres)


def read_first_pincam(folder: Path) -> tuple[int, int, float, float]:
    if folder.suffix == ".zip" or not folder.exists():
        z = folder if folder.suffix == ".zip" else folder.with_suffix(".zip")
        with zipfile.ZipFile(z) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".pincam"))
            vals = zf.read(name).decode().split()
    else:
        vals = next(folder.glob("*.pincam")).read_text().split()
    w, h, fx, fy = int(float(vals[0])), int(float(vals[1])), float(vals[2]), float(vals[3])
    return w, h, fx, fy


def umeyama(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float]:
    """Similarity dst ~ s R src + t; returns (s, R, t, rms)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    var_s = (xs**2).sum() / len(src)
    s = float(np.trace(np.diag(D) @ S) / var_s)
    t = mu_d - s * R @ mu_s
    res = dst - (s * (R @ src.T).T + t)
    return s, R, t, float(np.sqrt((res**2).sum(1).mean()))


# -- one scene ---------------------------------------------------------------------------------


def run_levanta(mov: Path, out: Path, max_views: int, focal_px: float | None) -> Path:
    cmd = [sys.executable, "-m", "levanta.cli", "video", str(mov), "-o", str(out), "--fps", "1", "--max-views", str(max_views), "--lang", "en", "--paper", "A3"]
    if focal_px:
        cmd += ["--focal-px", f"{focal_px:.2f}"]
    log = out.parent / f"{out.name}.log"
    out.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    return out


def evaluate(scene: Path, out_dir: Path, truth: dict, run: Path) -> dict:
    from levanta.scene import PointCloud

    plan = json.loads((run / "plan.json").read_text(encoding="utf-8")) if (run / "plan.json").exists() else None
    res = {"run": run.name, "ok": plan is not None}
    if plan is None:
        return res
    # cameras: levanta's (plan frame = cloud frame after gravity/Manhattan) vs ARKit's
    idx = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
    cloud = PointCloud.load_ply(run / "plan_cloud.ply")
    cams = cloud.cameras[:, :3, 3] if cloud.cameras is not None else None
    ts, centres = read_traj(scene / "lowres_wide.traj")
    # the .mov and the trajectory start together within a second or two: fit the offset
    s = rms = None
    R = t = None
    src: list = []
    best_off = 0.0
    if cams is not None and len(cams) == len(idx):
        for off in np.arange(-3.0, 3.01, 0.25):
            sr, ds = [], []
            for k, f in enumerate(idx):
                j = int(np.argmin(np.abs(ts - (ts[0] + off + f["time_s"]))))
                if abs(ts[j] - (ts[0] + off + f["time_s"])) < 0.2:
                    sr.append(cams[k])
                    ds.append(centres[j])
            if len(sr) >= 5:
                s_, R_, t_, rms_ = umeyama(np.array(sr), np.array(ds))
                if rms is None or rms_ < rms:
                    s, R, t, rms, best_off, src = s_, R_, t_, rms_, float(off), sr
    # rooms into the mesh frame: the plan frame is the cloud frame (PlanResult.cloud), so
    # the cameras' similarity carries the room polygons (z = 0, the floor) directly
    rooms_union = None
    if R is not None:
        polys = []
        for r in plan["rooms"]:
            pts = np.array([[x, y, 0.0] for x, y in r["polygon"]])
            ark = s * (R @ pts.T).T + t
            h = truth["horiz"]
            polys.append(Polygon([(p[h[0]], p[h[1]]) for p in ark]).buffer(0))
        if polys:
            rooms_union = unary_union(polys)
        _overlay(run / "overlay.png", truth["floor"], rooms_union, np.array([s * (R @ c) + t for c in cams])[:, truth["horiz"]] if cams is not None else None)
    lev_area = float(sum(Polygon(r["polygon"]).area for r in plan["rooms"]))
    res.update(
        {
            "levanta_area_m2": lev_area,
            "levanta_rooms": len(plan["rooms"]),
            "levanta_doors": sum(1 for o in plan["openings"] if o["kind"] == "door"),
            "levanta_walls": len(plan["walls"]),
            "scale_factor": s,
            "traj_rms_m": rms,
            "time_offset_s": best_off,
            "matched_cams": len(src),
            "area_error_pct": (lev_area - truth["area"]) / truth["area"] * 100.0,
            "area_error_scaled_pct": ((lev_area * s * s) - truth["area"]) / truth["area"] * 100.0 if s else None,
            "floor_iou": float(rooms_union.intersection(truth["floor"]).area / rooms_union.union(truth["floor"]).area) if rooms_union is not None and not rooms_union.is_empty else None,
        }
    )
    return res


def _overlay(path: Path, floor, rooms, cams) -> None:
    """Truth floor (grey) with levanta's rooms (green outline) and cameras (magenta)."""
    from PIL import Image, ImageDraw

    geoms = [floor] + ([rooms] if rooms is not None and not rooms.is_empty else [])
    minx = min(g.bounds[0] for g in geoms) - 0.5
    miny = min(g.bounds[1] for g in geoms) - 0.5
    maxx = max(g.bounds[2] for g in geoms) + 0.5
    maxy = max(g.bounds[3] for g in geoms) + 0.5
    ppm = 80.0
    W, H = int((maxx - minx) * ppm) + 1, int((maxy - miny) * ppm) + 1
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)

    def P(x, y):
        return ((x - minx) * ppm, (maxy - y) * ppm)

    for g in floor.geoms if hasattr(floor, "geoms") else [floor]:
        d.polygon([P(*c) for c in g.exterior.coords], fill=(200, 200, 200), outline=(90, 90, 90))
        for hole in g.interiors:
            d.polygon([P(*c) for c in hole.coords], fill="white", outline=(150, 150, 150))
    if rooms is not None and not rooms.is_empty:
        for g in rooms.geoms if hasattr(rooms, "geoms") else [rooms]:
            d.polygon([P(*c) for c in g.exterior.coords], outline=(0, 140, 0), width=3)
    if cams is not None:
        for x, y in cams:
            px, py = P(x, y)
            d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(200, 0, 200))
    d.text((6, 6), "grey: LiDAR floor  green: levanta rooms  magenta: cameras", fill=(0, 0, 0))
    im.save(path)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--max-views", type=int, default=24)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--runs", nargs="*", default=["noK", "withK"], help="which runs to (re)do; the others are read from disk")
    ap.add_argument("--eval-only", action="store_true", help="do not run levanta, evaluate what is on disk")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for scene in sorted(p for p in args.scenes_dir.iterdir() if p.is_dir()):
        vid = scene.name
        if args.only and vid not in args.only:
            continue
        mov = scene / f"{vid}.mov"
        mesh = scene / f"{vid}_3dod_mesh.ply"
        if not mov.exists() or not mesh.exists():
            print(f"{vid}: missing mov or mesh, skipped")
            continue
        t0 = time.time()
        v, f = read_ply(mesh)
        truth = floor_truth(v, f)
        print(f"{vid}: truth floor {truth['area']:.1f} m2, {truth['rooms']} room(s), up axis {truth['up']} ({time.time() - t0:.0f} s)")
        w, h, fx, fy = read_first_pincam(scene / "vga_wide_intrinsics")
        # the network sees frames 1024 px wide (long side): scale the focal to that
        import cv2

        cap = cv2.VideoCapture(str(mov))
        mw, mh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        long_side = max(mw, mh)
        frame_long = min(1024, long_side)
        f_frame = fx * frame_long / max(w, h)
        print(f"{vid}: mov {mw}x{mh}; ARKit fx {fx:.1f} at {w}x{h} -> {f_frame:.1f} px at {frame_long} px")
        rows = {"video_id": vid, "truth_area_m2": truth["area"], "truth_rooms": truth["rooms"], "mov": f"{mw}x{mh}", "focal_px_frame": f_frame}
        for name, focal in (("noK", None), ("withK", f_frame)):
            run = args.out / vid / name
            if name in args.runs and not args.eval_only:
                run = run_levanta(mov, run, args.max_views, focal)
            r = evaluate(scene, args.out, truth, run) if run.exists() else {"run": name, "ok": False}
            rows[name] = r
            print(f"  {name}: {json.dumps(r)}")
        results.append(rows)
        (args.out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    # the table
    lines = ["| scene | truth floor m² / rooms | scale, no K | scale, with K | area error, no K | area error, with K | floor IoU (K) | rooms (K) | doors (K) | camera RMS (K) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        a, b = r["noK"], r["withK"]
        fmt = lambda v, f="{:.2f}": "—" if v is None else f.format(v)  # noqa: E731
        lines.append(
            f"| {r['video_id']} | {r['truth_area_m2']:.1f} / {r['truth_rooms']} | {fmt(a.get('scale_factor'))} | {fmt(b.get('scale_factor'))} | {fmt(a.get('area_error_pct'), '{:+.0f} %')} | {fmt(b.get('area_error_pct'), '{:+.0f} %')} | {fmt(b.get('floor_iou'))} | {b.get('levanta_rooms', '—')} | {b.get('levanta_doors', '—')} | {fmt(b.get('traj_rms_m'))} m |"
        )
    (args.out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
