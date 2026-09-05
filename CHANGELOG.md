# Changelog

## 0.3.0 - 2026-09-05

What a drafter expects on a sheet.

- Dimension chains on every perimeter wall (corner - jamb - jamb - corner) plus overall dimensions.
- Opening tags (P1, V1, A1) on the plan, a door & window schedule and an area schedule (net, walls, gross) on the sheet.
- Title block: project, drawing, author, level (F.F.L.), scale, scale bar, date, revision, sheet, north.
- Reference axes (A, B, C / 1, 2, 3) and a north arrow (`--north`).
- Vector PDF at a standard scale (1:50, 1:100 ...) on A4/A3/A2/A1/Letter/Tabloid, with a second page of interior elevations; no PDF library needed.
- Interior elevations: every wall face-on with doors, windows, tags, widths and heights (`plan_elevations.png`).
- DXF: AIA-style layers (A-WALL, A-DOOR, A-GLAZ, A-ANNO-DIMS, A-GRID ...) with lineweights, door and window blocks, dimension chains, axes, schedules, title block; units m/cm/mm (`--dxf-units`).
- DXF 3D (`plan_3d.dxf`): the model as 3DFACE meshes by layer, for AutoCAD/SketchUp users.
- Checks (`FloorPlan.quality`): open rooms, assumed thicknesses, default ceiling, uncalibrated video scale, assumed door heights; printed by the CLI and listed in the HTML.
- Measured vs assumed shown per wall and per opening in the tables; `Wall.exterior` in the JSON.
- Measuring tool in the HTML viewer (click two points).
- Site plan: numbered vertices, coordinate table (local, WGS84, UTM with zone and EPSG), boundary table with azimuth (D°M'S") and length, area in m² and ha, perimeter, traverse closure; PDF and DXF tables too.
- `--project`, `--author`, `--sheet`, `--revision`, `--level`, `--north`, `--paper`, `--dxf-units`.

Drafter's review of the first 0.3.0 sheet (tests in `tests/test_drafter_review.py`, thresholds written before the fixes):

- Axis chains: every interior partition is positioned by a dimension between reference axes (A-B-C / 1-2-3), on both sides of the plan.
- Interior chains: openings on interior partitions are dimensioned inside the larger room (jamb - jamb - corner), not only on the perimeter.
- Every wall carries a tag on the plan (M1, M2 ...) that matches the schedule and the elevations; each elevation says which rooms it faces and its orientation (N, NE, E ...) from the north arrow.
- "assumed" is printed on the sheet: the unseen face of a one-sided wall is dashed and a general note lists those walls and the assumed thickness.
- Every PDF page has its own title block, sheet number (A-01, A-02 ...) and scale.
- The sheet is filled to at least 60 % of the usable page, or the note says which larger scale did not fit.
- `python -m levanta` works.

First real inputs after the review (a public TUM RGB-D room and a CC BY phone walkthrough):

- Wall ends meet the wall they run into: flush at corners, stopped at T-junctions (`square_corners`, `tests/test_square_corners.py`). The TUM sheet drew a 0.15 m stub of the left wall above the corner.
- `levanta video --max-views N` spreads the N frames over the whole clip (the sharpest of N equal stretches) instead of keeping the first N sharp seconds (`tests/test_video_frames.py`). The 220 s walkthrough would have used only its first 24 s; the CLI now prints the span covered.
- Title cards, fades and blank frames never reach the network (`tests/test_video_flat_frames.py`): text on black is the sharpest thing in a clip by variance of the Laplacian, and the first real walkthrough (a real-estate tour) got six title cards among its 24 frames. `levanta check` now counts them ("39 s of title cards or blank frames") and judges every real 1/fps window by the probes that fell in it, so usable + blurry + flat add up to the clip.
- A long walk is reconstructed in overlapping chunks that land in one metric world frame (`MapAnythingBackend.reconstruct`, `tests/test_recon_chunks.py`): every sharp frame goes to the network, `--max-views` at a time; each chunk after the first starts with `--overlap` views of the previous one, handed over with their known poses and intrinsics, and its output is aligned onto them (scale, rotation, translation). Measured before the fix on the 220 s walkthrough: 24 frames spread over the clip were 1-5 m apart and the network masked the rooms out (mask 1-2 % per view, 1-21 points).
- A view that comes back as one flat picture (an intro graphic, a poster filling the frame: valid depth over half the frame on one plane within 2 % of its distance) is skipped and counted (`views_dropped_flat`). The intro of that walkthrough came back as a plane at 0.62 m covering 90 % of the frame and the rooms were masked out around it.
- Room labels stay inside their room and wall tags stay off them (`tests/test_labels_fit.py`, on the real walkthrough plan kept in `tests/data/`): a narrow corridor gets its name, "(incomplete)", area and size on separate lines, shrunk down to 6 pt if it must; a tag whose spot is taken moves along the wall or to its other side.
- `examples/video_u2apartment/`: the outputs of that CC BY walkthrough, with attribution.
- MapAnything's weights go from the safetensors file straight to the GPU: the network is built on the meta device and filled on the card, tied weights included (`tests/test_recon_loading.py`). The host never holds the 4.6 GB, which is what killed the run with "OS error 1455: the paging file is too small" on a 32 GB laptop with other applications open.


## 0.2.0 — 2026-09-05

Made for people who are not going to read the source.

- `levanta demo`: see a full run in ten seconds, no data, no GPU.
- `levanta check video.mp4`: length, resolution, sharpness and usable frames before spending GPU time.
- `levanta doctor`: what is installed, what is missing, what to type.
- `levanta render plan.json`: regenerate every output after editing names or deleting a wall.
- New outputs: `plan.html` (self-contained viewer with 2D plan, interactive 3D and a measurements table), `plan.png`, `plan_3d.png` (axonometric view drawn without OpenGL).
- `--lang es|en`, `--units m|ft`, `--names "Living,Kitchen"`, `--title`, `--open`.
- Scale fixes for video: `--focal-px`, `--door-width 0.90`, `--scale`; `FloorPlan.scaled()` and `calibrated_to_door_width()`.
- Rooms with an unscanned side are drawn with a dashed edge and labelled "incomplete"; their outline is rectilinear.
- Site plans label only the long sides; site outputs gained HTML, PNG and a 3D view.
- Friendlier errors (out of memory, missing extras, no rooms), step-by-step progress.
- Docs: capture guide, FAQ, output formats (English and Spanish).
- One drawing model renders both SVG and PNG, so they always match.
- Tidying pass (`levanta.plan.tidy`): walls seen through doorways are set aside, walls are trimmed to the stretch that bounds a room, desk fronts and jamb returns inside rooms are dropped, open-room outlines lose furniture bites and snap to the walls beside them, and a gap between wall pieces the camera looked through becomes a door. On the TUM office this turns a cluttered sketch into a rectangle with three walls, two doors and one dashed glass side.

## 0.1.0 — 2026-09-04

First public version: point cloud → gravity/Manhattan → walls with measured thickness → doors, passages, windows → rooms → SVG/DXF/GLB/OBJ/JSON; RGB-D and MapAnything backends; OSM/Overture LOD1 site models; synthetic ground-truth tests; TUM RGB-D and Bogotá examples.
