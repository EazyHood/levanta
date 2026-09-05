# levanta

**Floor plans (2D) and a 3D model of a house from a phone video, or from public
satellite-derived building data.** A Python library and command-line tool. MIT licensed;
keep the copyright notice and it is yours to use.

*[Versión en español: README.es.md](README.es.md)*

```
phone video ──▶ frames ──▶ MapAnything ──▶ point cloud ──▶ floor plan ──▶ SVG · DXF · JSON
RGB-D + poses ────────────────────────────▶ point cloud ──▶ floor plan ──▶ GLB · OBJ (3D)
lat / lon ──▶ OpenStreetMap / Overture ──▶ footprint + height ──▶ LOD1 model + site plan
```

<p align="center">
  <img src="examples/synthetic_three_rooms/plan.svg" width="640" alt="Floor plan produced by levanta from a synthetic three-room scan">
</p>

## What it does, honestly

| Input | What you get | Where it comes from |
|---|---|---|
| A **walk-through video** from any phone | Metric point cloud, walls with thickness, doors, windows, rooms with areas, ceiling height; 2D plan (SVG, DXF) and 3D model (GLB, OBJ) | MapAnything (Meta, 3DV 2026) predicts metric depth + cameras from plain RGB; `levanta.plan` turns the cloud into architecture |
| **RGB-D frames with poses** (ARCore/ARKit/Record3D exports, datasets) | Same as above, no GPU needed | Pure numpy back-projection |
| A **point cloud** in metres (`.ply`) | Same plan + model | `levanta plan` |
| A **latitude / longitude** | Building footprint, height, LOD1 block model, site plan with edge lengths | OpenStreetMap (Overpass) or Overture Maps, both derived from overhead imagery |

What a satellite **cannot** give you is the interior: no sensor sees through a roof. The
`site` module therefore stops at footprint + height, and says so in its output. Interior
plans come from walking through the house with a phone.

## Install

```bash
pip install git+https://github.com/EazyHood/levanta          # core: plans from clouds / RGB-D, site models
pip install "levanta[overture] @ git+https://github.com/EazyHood/levanta"   # + Overture Maps source
```

For the video path you also need a GPU-capable PyTorch and MapAnything (Apache-2.0):

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # pick your CUDA
pip install -r requirements-recon.txt
```

Python 3.10+. Tested on Windows 11 and Ubuntu; the planner needs no GPU.

## Use

```bash
# 1. A phone video -> everything (frames are picked for sharpness; ~30 views is plenty)
levanta video walkthrough.mp4 -o out/house --max-views 32

# 2. Steps separately
levanta frames walkthrough.mp4 -o frames --fps 1
levanta reconstruct frames -o cloud.ply --max-views 32      # MapAnything, Apache-2.0 weights by default
levanta plan cloud.ply -o out/house --title "My house"

# 3. RGB-D with poses, no GPU (demo on the public TUM RGB-D benchmark, CC BY 4.0)
levanta tum rgbd_dataset_freiburg1_room -o out/tum

# 4. Public data: the building at a coordinate -> LOD1 model + site plan
levanta site --lat 4.5981 --lon -74.0760 -o out/site            # Bogota, Plaza de Bolivar
levanta site --lat 4.5981 --lon -74.0760 --source overture --all-buildings

# 5. Rebuild the 3D model from a saved plan
levanta model out/house/plan.json -o house.glb --ceiling
```

Every command writes a `*_debug.png` showing what the planner saw (line of sight, wall
points, detected walls, rooms). Look at it first when a plan is wrong.

As a library:

```python
from levanta import PointCloud, extract_floor_plan, PlanOptions
from levanta.io.export import export_all

cloud = PointCloud.load_ply("cloud.ply")             # metres; normals + cameras used if present
result = extract_floor_plan(cloud, PlanOptions(manhattan=True))
print(result.plan.summary())
export_all(result.plan, "out", stem="plan")          # plan.svg / .dxf / .glb / .obj / .json
```

## How it works

1. **Reconstruction** (`levanta.recon`). RGB-D frames are back-projected with normals
   computed on the depth image (6-pixel baseline + median filter, because consumer depth
   is centimetre-noisy) and oriented towards the camera. For plain video, MapAnything
   predicts per-view metric depth, intrinsics and poses in one forward pass; those views
   flow through the very same code. Every point remembers which camera saw it.
2. **Gravity** (`levanta.plan.gravity`). The mean camera "up" seeds a vertical estimate that
   is sharpened on floor/ceiling normals; a height histogram gives floor and ceiling.
3. **Manhattan frame** (`levanta.plan.walls`). The mode of the wall-normal angles (folded
   to 90°) rotates the cloud so walls run along x/y. `--free` keeps arbitrary directions.
4. **Rasters** (`levanta.plan.occupancy`). Per 5 cm cell, *how many height bands* contain
   wall points — a wall spans floor to ceiling, a sofa does not. Camera-to-point sight
   lines mark free space: a gap in a wall that rays passed through is a doorway; a gap no
   ray crossed is just wall nobody looked at.
5. **Faces → walls**. Per direction, the offset histogram gives wall planes; runs of
   points along each plane give faces; a face seen from the room on the other side is
   paired with it, which *measures* the wall thickness. Lone faces get a default
   thickness and are classified exterior when nothing was seen behind them.
6. **Openings**. Gaps with line of sight → doors (or passages if wider than 1.3 m), with the
   lintel height measured; door and window edges are refined to 1 cm on the raw samples.
   Windows: stretches seen below and above a band but never inside it.
7. **Rooms** (`levanta.plan.rooms`). Doors are bricked up temporarily and the pockets
   between wall bodies become rooms. If walls are incomplete, gaps up to 1.2 m are bridged;
   what is still open follows the seen floor and is flagged `closed: false`.
8. **3D** (`levanta.plan.model`). Walls are boxes split around openings (sill and lintel
   boxes, no booleans), floor slabs per room, optional ceilings; doors and window panes
   are separate materials in the GLB.

## How we know it works

The tests in `tests/test_pipeline_synthetic.py` build apartments with exact ground truth
(`tests/synthetic.py`): noisy wall/floor/ceiling samples, low furniture, cameras that see
through doorways, a tilted and rotated copy. The acceptance thresholds were written down
before the first run. Current results on those scenes:

| Quantity | Ground truth | Measured | Threshold |
|---|---|---|---|
| Room area IoU (5 rooms, 2 scenes) | 1.0 | ≥ 0.999 | ≥ 0.90 |
| Interior wall thickness | 0.120 m | 0.119 m | ± 0.03 m |
| Door widths (4 doors) | 0.90 m | 0.87–0.89 m | ± 0.20 m |
| Window widths / sill / head | 1.20, 1.40 m / 0.90 / 2.10 | 1.19, 1.39 m / 0.85 / 2.10 | ± 0.20 / ± 0.10 m |
| Ceiling height | 2.50 m | 2.4998 m | ± 0.03 m |
| Manhattan residual after 23° yaw + 9° tilt | 0° | < 0.1° | < 1° |

On real data (TUM `freiburg1_room`: a hand-held Kinect walked around a cluttered office,
motion-capture poses, 454 frames, no GPU, 742 k points): three walls, the door (0.83 m
wide, lintel measured at 2.54 m) and the ceiling (2.91 m) are found, and the room comes
out as 5.0 × 5.0 m, 19.7 m². The fourth wall is glass and never returned depth, so the
outline on that side follows the seen floor and the room is reported `closed: false`;
no wall was seen from both sides, so all thicknesses are defaults (`sides_seen: 1`).
Plan, debug image and JSON are in [`examples/tum_fr1_room/`](examples/tum_fr1_room/).

MapAnything on the same sequence from **RGB only** (16 frames, 640×480, RTX 5060 laptop
8 GB, 6.7 GB VRAM, 46 s once the 4.6 GB checkpoint is cached), compared pixel by pixel
with the Kinect depth:

| Inputs to the network | median predicted / Kinect depth | abs-rel depth error | camera step ratio |
|---|---|---|---|
| images only | 0.86 | 0.14 | 0.97 |
| images + known intrinsics | **0.93** | **0.095** | 0.97 |

So the scale from video alone is short by ~7–14 %: pass the intrinsics when you have them
(EXIF focal length, ARCore/ARKit), or measure one door and rescale. The whole video
path was exercised by re-encoding the sequence as an mp4 and running
`levanta video tum_room.mp4 --max-views 20`: 20 sharp frames picked, 83 k points, two
walls and an open room. Twenty frames of a 640×480 Kinect stream are a hard case for the
planner; a phone at 1080p with 30+ frames is the intended input.

## Limits you should know

- **Scale from video is only as good as the network's metric estimate.** Pass intrinsics
  or a known length. RGB-D with device poses (ARCore/ARKit) is exact.
- **Tall furniture looks like a wall.** Wardrobes, fridges and open door leaves reach high
  enough to pass the height-coverage test. Scan with doors closed, and check the debug PNG.
- **Unseen is unknown.** Wall thickness is measured only where both faces were scanned;
  otherwise a default is used and the wall is marked `sides_seen: 1`. Exterior walls
  are guessed exterior when nothing was ever seen behind them.
- **Manhattan mode** snaps walls to two directions; use `--free` for angled walls.
- **Site models are LOD1**: footprint × height. Heights come from the source's `height`
  tag when present, otherwise `levels × 3 m`, otherwise 3 m — and the JSON says which.
- Glass, mirrors and textureless walls are hard for any photogrammetry; they are marked
  as unseen rather than invented.

## Data and licenses used

- [MapAnything](https://github.com/facebookresearch/map-anything) — Apache-2.0 code; the
  default checkpoint `facebook/map-anything-apache` is Apache-2.0 too.
- [TUM RGB-D benchmark](https://cvg.cit.tum.de/data/datasets/rgbd-dataset) — CC BY 4.0
  (Sturm et al., IROS 2012). Not redistributed; `levanta tum` reads a downloaded sequence.
- [OpenStreetMap](https://www.openstreetmap.org) via Overpass — ODbL 1.0,
  © OpenStreetMap contributors. [Overture Maps](https://overturemaps.org) — ODbL /
  CDLA-Permissive-2.0 per source.

## Project layout

```
src/levanta/
  scene.py          Camera, Frame, PointCloud (PLY I/O with cameras)
  geometry.py       small numeric helpers
  io/               video frames, TUM loader, SVG/DXF/GLB/OBJ/JSON writers
  recon/            rgbd back-projection, MapAnything adapter, backend registry
  plan/             gravity, occupancy rasters, walls, rooms/openings, pipeline, 3D model, debug PNG
  site/             WGS84 projection, OSM/Overture sources, LOD1 model + site plan
  cli.py            `levanta` command
tests/              synthetic ground-truth scenes and unit tests (no GPU, no network)
examples/           outputs you can open without running anything
```

## License and attribution

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Jhona (github.com/EazyHood). You may use,
copy, modify and redistribute this software, commercially or not, as long as the copyright
notice and this permission notice stay with it. If you publish work based on it, a
citation ([CITATION.cff](CITATION.cff)) is appreciated.
