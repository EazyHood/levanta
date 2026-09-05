# Output files

Every run writes these into the output folder (`-o`), all from the same plan:

| File | What it is | Open it with |
|---|---|---|
| `plan.html` | Self-contained viewer: 2D plan, interactive 3D, measurements table, download buttons | any browser (double-click). The 3D view loads a small library from a CDN the first time; offline it shows the static 3D drawing |
| `plan.png` | The 2D plan at 2× resolution | anything; good for messaging |
| `plan.svg` | The same plan as vectors | browser, Inkscape, Illustrator, Figma |
| `plan_3d.png` | Static 3D view (axonometric) | anything |
| `plan.dxf` | CAD drawing in metres, layers `WALLS`, `WALL-FILL`, `ROOMS`, `DOORS`, `WINDOWS`, `PASSAGES`, `TEXT`, `DIMENSIONS` | AutoCAD, LibreCAD, QCAD, SketchUp (import), Revit (link) |
| `plan.glb` | 3D model: walls with openings, door leaves, window panes, floor slabs (materials per element) | Blender, Windows 3D Viewer, three.js, Unity/Unreal, any glTF viewer |
| `plan.obj` | Same model as OBJ | anything that reads OBJ |
| `plan.json` | The data: walls, rooms, openings, ceiling, transform, options; editable | your own code; `levanta render plan.json` |
| `plan_cloud.ply` | The point cloud in the plan frame (metres, z up, floor at 0), with normals, colours and camera index | MeshLab, CloudCompare, Blender |
| `plan_debug.png` | What the planner saw | your eyes, when something is wrong |

## The JSON in one screen

```json
{
  "version": 1,
  "units": "m",
  "ceiling_height": 2.5, "ceiling_measured": true,
  "walls":    [{"id": 0, "a": [0, 0], "b": [4, 0], "thickness": 0.2, "height": 2.5, "sides_seen": 1, "line_id": 3, "length_m": 4.0}],
  "rooms":    [{"id": 0, "name": "Living", "polygon": [[0.1, 0.1], [3.9, 0.1], [3.9, 2.9], [0.1, 2.9]], "holes": [], "closed": true, "area_m2": 10.64}],
  "openings": [{"id": 0, "wall_id": 0, "kind": "door", "t0": 1.0, "t1": 1.9, "z0": 0.0, "z1": 2.05, "rooms": [0], "width_m": 0.9}],
  "transform": [[...4x4: input cloud frame -> plan frame...]],
  "meta": {"options": {...}, "gravity": {...}, "debug": {...}}
}
```

- Walls are centre-lines `a → b` with a `thickness`; `sides_seen: 2` means the thickness
  was measured, `1` that it is a default.
- Openings sit on a wall; `t0/t1` are metres along the wall from `a`, `z0/z1` heights.
- Rooms are polygons (counter-clockwise, metres); `closed: false` means one side
  follows the seen floor instead of a detected wall.
- Edit names, delete a false wall, then `levanta render plan.json` regenerates everything.

## Site outputs (`levanta site`)

`site.html`, `site.png`/`site.svg` (site plan with edge lengths, north arrow, scale bar,
attribution), `site_3d.png`, `site.dxf`, `site.glb`/`site.obj` (LOD1 block on a ground
slab), `site.json` (building, height and its source, local footprint in metres).
