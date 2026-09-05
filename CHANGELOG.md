# Changelog

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
