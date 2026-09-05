# Examples

Outputs you can open without installing anything. Double-click any `*.html` for the
viewer (2D plan with a measuring tool, 3D view, elevations, measurements, checks); the
`*.pdf` is the printable sheet at a standard scale; the `*.png` files are the same
drawings as images.

| Folder | Input | Notes |
|---|---|---|
| `synthetic_three_rooms/` | `levanta demo` — two rooms and a corridor, 3 doors, 2 windows, low furniture, 8 mm noise | Every quantity has an exact ground truth; this is the scene the tests measure. Has every output format. |
| `tum_fr1_room/` | TUM RGB-D `freiburg1_room` (CC BY 4.0), 454 Kinect frames with mocap poses, no GPU | Real, cluttered office. Three walls and the door found; the fourth wall is glass and never returned depth, so that side is dashed and the room is labelled incomplete. |
| `site_bogota_catedral/` | `levanta site --lat 4.5981 --lon -74.0760 --lang es` | OpenStreetMap footprint of the Catedral Primada de Bogotá (4 levels → 12 m). LOD1 only: footprint × height. |

Regenerate:

```bash
levanta demo -o examples/synthetic_three_rooms --names "Living,Bedroom,Hall"
levanta tum rgbd_dataset_freiburg1_room -o out/tum          # after downloading the sequence
levanta render examples/tum_fr1_room/plan.json --names Office
levanta site --lat 4.5981 --lon -74.0760 -o examples/site_bogota_catedral --lang es
```
