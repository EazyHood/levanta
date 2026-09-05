"""Which ARKitScenes scans are big?  Floor area and room count per mesh, fast.

Rasterises the up-facing triangles at floor height on a 5 cm grid, fills furniture
holes, erodes 0.40 m and counts the connected parts (>= 1 m2).  A few seconds per mesh,
so hundreds of meshes can be screened for "an apartment": >= 40 m2 and >= 3 rooms.

Usage: python bench/scan_scenes.py C:/Users/jhona/arkitscenes_data/raw/Validation
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from arkitscenes import read_ply


def floor_raster(vertices: np.ndarray, faces: np.ndarray, cell: float = 0.05) -> tuple[float, int, np.ndarray]:
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
    keep = facing_up & (np.abs(h - floor_h) < 0.12)
    horiz = [k for k in range(3) if k != up]
    pts = tri[keep][:, :, horiz].reshape(-1, 2)  # triangle vertices; the triangles are ~cm-sized
    cen = tri[keep][:, :, horiz].mean(axis=1)
    pts = np.vstack([pts, cen])
    lo = pts.min(axis=0) - 0.2
    ij = np.floor((pts - lo) / cell).astype(int)
    shape = ij.max(axis=0) + 5
    grid = np.zeros(shape, dtype=bool)
    grid[ij[:, 0], ij[:, 1]] = True
    grid = ndimage.binary_closing(grid, iterations=2)
    filled = ndimage.binary_fill_holes(grid)
    # keep the largest connected floor
    lab, k = ndimage.label(filled)
    if k > 1:
        sizes = ndimage.sum(filled, lab, range(1, k + 1))
        filled = lab == (int(np.argmax(sizes)) + 1)
    area_m2 = float(filled.sum() * cell * cell)
    er = ndimage.binary_erosion(filled, iterations=int(round(0.40 / cell)))
    lab, k = ndimage.label(er)
    rooms = 0
    for i in range(1, k + 1):
        if (lab == i).sum() * cell * cell >= 1.0:
            rooms += 1
    return area_m2, max(1, rooms), filled


def main() -> None:
    root = Path(sys.argv[1])
    rows = []
    for scene in sorted(p for p in root.iterdir() if p.is_dir()):
        mesh = scene / f"{scene.name}_3dod_mesh.ply"
        if not mesh.exists():
            continue
        try:
            v, f = read_ply(mesh)
            a, r, _ = floor_raster(v, f)
        except Exception as e:
            print(f"{scene.name}: {type(e).__name__}: {e}")
            continue
        rows.append((scene.name, a, r, len(f)))
        print(f"{scene.name}: floor {a:6.1f} m2, rooms {r}, faces {len(f):,}", flush=True)
    rows.sort(key=lambda x: -x[1])
    print("\nlargest:")
    for name, a, r, nf in rows[:10]:
        print(f"  {name}: {a:.1f} m2, {r} room(s)")
    big = [x for x in rows if x[1] >= 40 and x[2] >= 3]
    print(f"\n>= 40 m2 and >= 3 rooms: {[x[0] for x in big] or 'none'} of {len(rows)} scanned")


if __name__ == "__main__":
    main()
