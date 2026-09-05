# levanta

**Film your house with your phone, get the floor plan and a 3D model.** Also works from
a point cloud, from RGB-D frames, and, for the outside of any building, from public
map data. A Python library and a command-line tool. MIT: keep the author's notice and
it is yours to use, sell, or build on.

*[Versión en español: README.es.md](README.es.md)*

<p align="center">
  <img src="examples/synthetic_three_rooms/plan.png" width="720" alt="2D floor plan produced by levanta: three rooms, doors with swings, windows, dimensions">
</p>
<p align="center">
  <img src="examples/synthetic_three_rooms/plan_3d.png" width="520" alt="3D view of the same plan: walls with door and window openings, floor slabs">
</p>

## Try it in ten seconds

```bash
pip install git+https://github.com/EazyHood/levanta
levanta demo --open
```

That builds a small apartment the way a phone would see it, runs the whole pipeline
and opens `plan.html`: the 2D plan, a 3D view you can orbit, and a table with every
measurement. No GPU, no data, no internet needed except for `pip`.

## Then your own house

1. **Film it.** Slowly, landscape, every wall floor to ceiling, through every door. Ten
   minutes of reading [the capture guide](docs/capture-guide.md) save an hour later.
2. **Check the video** before spending GPU time:
   ```bash
   levanta check walk.mp4
   ```
3. **Run it** (needs the GPU extras, see *Install*):
   ```bash
   levanta video walk.mp4 -o out/house --names "Living,Kitchen,Bedroom,Bath" --open
   ```
4. **Fix the scale** if the doors come out narrow. Measure one door and:
   ```bash
   levanta render out/house/plan.json --door-width 0.90
   ```

You get, in `out/house/`: `plan.html` · `plan.png` · `plan.svg` · `plan_3d.png` ·
`plan.dxf` (CAD) · `plan.glb` / `plan.obj` (3D) · `plan.json` (data) · `plan_debug.png`
(what the planner saw). [What each file is and how to open it.](docs/formats.md)

## What it does, honestly

| Input | What you get | How |
|---|---|---|
| **Phone video** | Metric point cloud, walls with thickness, doors, windows, rooms with areas, ceiling height, 2D plan, 3D model | MapAnything (Meta, 3DV 2026) predicts metric depth and cameras from plain RGB; `levanta.plan` turns the cloud into architecture |
| **RGB-D frames with poses** (ARCore/ARKit/Record3D exports, datasets) | Same, no GPU, exact scale | numpy back-projection |
| **Point cloud** in metres (`.ply`) | Same | `levanta plan` |
| **A latitude/longitude** | Building footprint, height, LOD1 block model, site plan with side lengths | OpenStreetMap or Overture Maps, both derived from overhead imagery |

What a satellite **cannot** give you is the interior: no sensor sees through a roof.
`levanta site` therefore stops at footprint + height, and its output says so. Interior
plans come from walking through the house.

## Install

```bash
pip install git+https://github.com/EazyHood/levanta            # plans, 3D, site models (no GPU)
pip install "levanta[overture] @ git+https://github.com/EazyHood/levanta"   # + Overture Maps source
```

For the video path you also need PyTorch with CUDA and MapAnything (Apache-2.0):

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # pick your CUDA at pytorch.org
pip install -r requirements-recon.txt
levanta doctor                                                                     # tells you what is still missing
```

Python 3.10+. Windows, Linux and macOS for everything except the GPU path, which needs
an NVIDIA GPU with 8 GB or more (24–32 frames) or patience on the CPU. The first video
run downloads 4.6 GB of weights once.

## All commands

```
levanta demo                       see it work on a synthetic apartment
levanta check  walk.mp4            is the video good enough?
levanta video  walk.mp4 -o out     video -> plan + 3D (GPU)
levanta plan   cloud.ply -o out    point cloud -> plan + 3D
levanta tum    <sequence> -o out   public TUM RGB-D sequence -> plan (no GPU)
levanta site   --lat 4.5981 --lon -74.0760 -o out     coordinate -> footprint, height, LOD1
levanta render plan.json           re-make every output after editing the JSON
levanta doctor                     installed / missing / what to type
```

Common options: `--lang es`, `--units ft`, `--names "A,B,C"`, `--title "..."`, `--open`,
`--door-width 0.90`, `--scale 1.07`, `--ceiling`. Every command writes a `*_debug.png`.

As a library:

```python
from levanta import PointCloud, extract_floor_plan, PlanOptions
from levanta.io.export import export_all

cloud = PointCloud.load_ply("cloud.ply")               # metres; normals and cameras used when present
result = extract_floor_plan(cloud, PlanOptions())
plan = result.plan.rename_rooms(["Living", "Kitchen"])
plan, factor = plan.calibrated_to_door_width(0.90)     # optional scale fix
export_all(plan, "out", lang="en", units="m")           # html, png, svg, dxf, glb, obj, json
```

## How it works

1. **Reconstruction** (`levanta.recon`). RGB-D frames are back-projected with normals
   computed on the depth image (6-pixel baseline plus a median filter, because consumer
   depth is centimetre-noisy) and oriented towards the camera. For plain video,
   MapAnything predicts per-view metric depth, intrinsics and poses in one pass; those
   views flow through the same code. Every point remembers which camera saw it.
2. **Gravity** (`levanta.plan.gravity`). The mean camera "up" seeds a vertical that is
   sharpened on floor and ceiling normals; a height histogram gives floor and ceiling.
3. **Manhattan frame** (`levanta.plan.walls`). The mode of the wall-normal angles, folded
   to 90°, rotates the cloud so walls run along x and y. `--free` keeps any direction.
4. **Rasters** (`levanta.plan.occupancy`). Per cell, how many height bands contain wall
   points: a wall spans floor to ceiling, a sofa does not. Camera-to-point sight lines
   mark free space: a gap in a wall that rays passed through is a doorway; a gap no ray
   crossed is wall nobody looked at.
5. **Faces → walls.** Per direction, the offset histogram gives wall planes; runs of
   points along each plane give faces; a face seen from the room on the other side is
   paired with it, which *measures* the thickness. Lone faces get a default thickness
   and count as exterior when nothing was seen behind them.
6. **Openings.** Gaps with line of sight become doors (passages if wider than 1.3 m),
   lintel height measured; door and window edges are refined to 1 cm on the raw samples.
   Windows are stretches seen below and above a band but never inside it.
7. **Rooms** (`levanta.plan.rooms`). Doors are bricked up temporarily and the pockets
   between wall bodies become rooms. Gaps up to 1.2 m are bridged; what is still open
   follows the seen floor, gets a rectilinear outline and the flag `closed: false`.
8. **Drawings and 3D** (`levanta.io`). One drawing model renders both SVG and PNG, so
   they always match. Walls become boxes split around openings (sill and lintel boxes,
   no booleans); the 3D preview is an axonometric projection drawn without OpenGL.

## How we know it works

The tests build apartments with exact ground truth (`levanta.synthetic`): noisy wall,
floor and ceiling samples, low furniture, cameras that see through doorways, a tilted
and rotated copy. The acceptance thresholds were written before the first run.

| Quantity | Ground truth | Measured | Threshold |
|---|---|---|---|
| Room area IoU (5 rooms, 2 scenes) | 1.0 | ≥ 0.999 | ≥ 0.90 |
| Interior wall thickness | 0.120 m | 0.119 m | ± 0.03 m |
| Door widths (4 doors) | 0.90 m | 0.87–0.89 m | ± 0.20 m |
| Window widths / sill / head | 1.20, 1.40 m / 0.90 / 2.10 | 1.19, 1.39 m / 0.85 / 2.10 | ± 0.20 / ± 0.10 m |
| Ceiling height | 2.50 m | 2.4998 m | ± 0.03 m |
| Manhattan residual after 23° yaw + 9° tilt | 0° | < 0.1° | < 1° |

**Real data**, TUM `freiburg1_room` (a hand-held Kinect walked around a cluttered office,
motion-capture poses, 454 frames, no GPU): three walls, the door (0.83 m, lintel measured
at 2.54 m) and the ceiling (2.91 m) are found; the room comes out 5.0 × 5.0 m. The fourth
wall is glass and never returned depth, so that side follows the seen floor and the room
is flagged incomplete. See [`examples/tum_fr1_room/`](examples/tum_fr1_room/).

<p align="center">
  <img src="examples/tum_fr1_room/plan.png" width="520" alt="Plan of the TUM fr1_room office: three walls, a door, one side dashed as not scanned">
</p>

**MapAnything from RGB only** on the same sequence (16 frames of 640×480, RTX 5060 laptop
8 GB, 6.7 GB VRAM, 46 s once the weights are cached), compared pixel by pixel with the
Kinect depth:

| Inputs to the network | median predicted / Kinect depth | abs-rel depth error |
|---|---|---|
| images only | 0.86 | 0.14 |
| images + known intrinsics | **0.93** | **0.095** |

So the scale from video alone is 7–14 % short. That is what `--focal-px` and
`--door-width` are for. Twenty frames of a 640×480 Kinect stream are a hard case for
the planner (two walls and an open room); a phone at 1080p with 30+ frames is the
intended input.

## Limits you should know

- **Scale from video** is only as good as the network's metric estimate: pass the focal
  length or calibrate on a door. RGB-D with device poses is exact.
- **Tall furniture looks like a wall.** Wardrobes, fridges and open door leaves reach high
  enough to pass the height test. Scan with doors closed; delete the extra wall in the
  JSON and `levanta render`.
- **Unseen is unknown.** Thickness is measured only where both faces were scanned;
  otherwise a default is used (`sides_seen: 1`). Rooms with an unscanned side are
  drawn dashed there and labelled *incomplete*, never invented.
- **Manhattan mode** snaps walls to two directions; `--free` for angled walls.
- **Site models are LOD1**: footprint × height. Height comes from the source's `height`
  tag when present, else `levels × 3 m`, else 3 m, and the JSON says which.
- Glass, mirrors and blank walls are hard for any photogrammetry.

More in the [FAQ](docs/faq.md).

## Data and licenses used

- [MapAnything](https://github.com/facebookresearch/map-anything), Apache-2.0 code; the
  default checkpoint `facebook/map-anything-apache` is Apache-2.0 too.
- [TUM RGB-D benchmark](https://cvg.cit.tum.de/data/datasets/rgbd-dataset), CC BY 4.0
  (Sturm et al., IROS 2012). Not redistributed; `levanta tum` reads a downloaded sequence.
- [OpenStreetMap](https://www.openstreetmap.org) via Overpass, ODbL 1.0,
  © OpenStreetMap contributors. [Overture Maps](https://overturemaps.org), ODbL /
  CDLA-Permissive-2.0 per source.
- The HTML viewer loads [three.js](https://threejs.org) (MIT) from a CDN for the
  interactive 3D view; everything else is embedded in the file.

## Project layout

```
src/levanta/
  scene.py, geometry.py    Camera, Frame, PointCloud; numeric helpers
  synthetic.py             ground-truth apartments (tests and `levanta demo`)
  i18n.py                  labels in English and Spanish, metres or feet
  io/                      video frames + quality check, TUM loader, drawing model (SVG+PNG),
                           2D plan, axonometric 3D, HTML viewer, DXF/GLB/OBJ/JSON writers
  recon/                   RGB-D back-projection, MapAnything adapter
  plan/                    gravity, rasters, walls, rooms and openings, pipeline, 3D model, debug PNG
  site/                    WGS84 projection, OSM/Overture sources, LOD1 model + site plan
  cli.py                   the `levanta` command
tests/                     ground-truth scenes, unit tests, CLI tests (no GPU, no network)
docs/                      capture guide, FAQ, formats (English and Spanish)
examples/                  outputs you can open without running anything
```

## License and attribution

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Jhona (github.com/EazyHood). Use it,
copy it, modify it, sell it: just keep the copyright notice and the permission notice
with it. A citation ([CITATION.cff](CITATION.cff)) is appreciated in published work.
