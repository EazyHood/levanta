# levanta against ground truth: ARKitScenes, 5 validation scenes (2026-09-05)

Real iPhone videos (1920×1440, 60 fps, 46–188 s) with the LiDAR mesh and the ARKit
trajectory that Apple ships with them. `python bench/arkitscenes.py`, levanta at commit
`445bffa`, MapAnything `facebook/map-anything-apache`, RTX 5060 8 GB, `--max-views 24`.

**Truth.** Floor polygon = up-facing mesh triangles at floor height, unioned, furniture
holes filled; rooms = connected parts after eroding 0.40 m (at least one per scan).
**Alignment.** levanta's cameras are fitted to ARKit's with a similarity (Umeyama) after
searching the .mov/trajectory time offset; the fitted scale is the scale error and the
residual (RMS) says how well the two walks agree. levanta's rooms are carried into the
mesh frame with that similarity for the IoU.

**Metrics fixed before the first run:** scale factor (1.00 ideal), total area error,
floor IoU, rooms detected vs. truth, doors detected (no truth), camera RMS.

| scene | truth floor m² / rooms | video | scale, no K | scale, with K | area error, no K | area error, with K | floor IoU, no K / K | rooms | doors | camera RMS |
|---|---|---|---|---|---|---|---|---|---|---|
| 41069021 | 17.5 / 1 | 188 s | **1.00** | 1.07 | −22 % | −30 % | 0.61 / 0.60 | 2 (1) | 1 | 0.42 / 0.36 m |
| 42897526 | 4.9 / 1 | 46 s | 0.95 | 0.97 | +31 % | +46 % | 0.52 / 0.56 | 1–2 (1) | 0 | 0.49 / 0.42 m |
| 45260905 | 25.3 / 1 | 78 s | 1.30 | 1.32 | −24 % | −26 % | 0.69 / 0.68 | 1 (1) | 0 | 0.61 / 0.44 m |
| 47331964 | 24.0 / 2 | 127 s | 0.97 | 1.00 | −44 % | −75 % | 0.40 / 0.19 | 2 (2) | 0 | 0.88 / 0.89 m |
| 47430051 | 4.2 / 1 | 62 s | 0.26 | 0.25 | +78 % | +52 % | 0.07 / 0.06 | 1 (1) | 0 | 0.75 / 0.75 m |

"with K": the focal length ARKit recorded for the camera, scaled to the 1024 px frames
(≈ 850 px), passed with `--focal-px`. Rooms: levanta (truth).

## What it says

- **Scale from the network alone:** within ±5 % on three scenes, 30 % short on one
  (45260905, both with and without K), and collapsed on one small bathroom (47430051:
  56 k points, one wall, scale 0.25). *Knowing the focal length did not help*: it moved
  the scale by at most 7 % and not towards 1.00. On these five the door measurement is
  the only thing that fixes the scale; the PRELIMINARY stamp is right to stay.
- **Areas come out small even when the scale is right:** −22 % and −44 % at scale 1.00 and
  0.97. The room outline follows the floor the camera saw; the strips along the walls,
  behind and under furniture, were never seen in these scans (they were made to capture
  objects, not walls). Two bathrooms (4–5 m²) came out large instead (+31 %, +78 %).
- **Shape:** floor IoU 0.52–0.69 on the three scenes that reconstructed; 0.40 and 0.07 on
  the other two. Rooms: right count on four of five, one room split in two.
- **Doors:** one found in five scans (ARKitScenes rooms are scanned with the doors
  closed; there is no door truth in the dataset).
- **Camera drift:** 0.36–0.89 m RMS after the best similarity, over 1–3 minute walks.
  The chunks are placed on the previous chunk's cameras with no loop closure; the
  error grows with the length of the walk.

## Not in this table

Two of the five scans are tiny bathrooms picked by index, not by hand. The
ARKitScenes license (research, non-commercial) is why the overlays and levanta's sheets
for these scenes are not in the repository; the numbers and the script are.
