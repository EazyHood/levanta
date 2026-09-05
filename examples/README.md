# Examples

Outputs you can open without installing anything. Each folder holds the SVG plan, the
planner's debug image and the JSON produced by the pipeline.

| Folder | Input | Notes |
|---|---|---|
| `synthetic_three_rooms/` | `tests/synthetic.py` → `three_rooms()` — two rooms and a corridor, 3 doors, 2 windows, low furniture, noise 8 mm | Every quantity has an exact ground truth; this is the scene the tests measure. Also has DXF, GLB and OBJ. |
| `tum_fr1_room/` | TUM RGB-D `freiburg1_room` (CC BY 4.0), 454 Kinect frames with mocap poses, no GPU | Real, cluttered office. Three walls + door found; the fourth wall is glass and never returned depth, so that side follows the seen floor (`closed: false`). |
| `site_bogota_catedral/` | `levanta site --lat 4.5981 --lon -74.0760` | OpenStreetMap footprint of the Catedral Primada de Bogotá (4 levels → 12 m). LOD1 only: footprint × height. |

Regenerate:

```bash
python -c "from tests.synthetic import *; ..."             # see tests/test_export.py
levanta tum rgbd_dataset_freiburg1_room -o out/tum         # after downloading the sequence
levanta site --lat 4.5981 --lon -74.0760 -o out/site
```
