# FAQ

*(Versión en español: [preguntas-frecuentes.md](preguntas-frecuentes.md))*

**Do I need a GPU?**
Only for the video path (MapAnything). `levanta plan` on a point cloud, `levanta tum`,
`levanta site`, `levanta render` and `levanta demo` run on any laptop. Without a CUDA
GPU MapAnything still runs on the CPU, but expect many minutes per view and 8+ GB of
RAM.

**Which phone works?**
Any. levanta only needs the video file. iPhone Pro/iPad Pro owners with LiDAR can also
export RGB-D with poses from apps like Record3D and feed `levanta plan` with a metric
cloud, which removes the scale uncertainty entirely.

**How do I open the results?**
Double-click `plan.html`: it has the 2D plan, an interactive 3D view and a table of
measurements. `plan.png` is for sending on WhatsApp; `plan.svg` for editing in
Inkscape/Illustrator; `plan.dxf` for AutoCAD, LibreCAD, SketchUp; `plan.glb` for
Blender, Windows 3D Viewer or any web viewer; `plan.json` for programs.

**The plan says "incomplete" on a room.**
One side of the room was not seen as a wall floor-to-ceiling. The outline on that side
follows the floor the camera saw and is drawn dashed. Film that wall again (see the
capture guide) or accept the outline.

**No rooms at all.**
Open `plan_debug.png`. Grey is where the camera looked, black dots are wall points,
coloured rectangles are detected walls, green is a room. If there are no coloured
rectangles the walls were not scanned floor-to-ceiling; if there are walls but no green,
the room is not closed on three sides and the floor was not seen.

**The plan is rotated / mirrored.**
The plan frame is aligned to the walls (Manhattan frame), not to north. Rotate in your
CAD program. A mirror image cannot happen; if it looks mirrored you are looking at it
from below in the 3D viewer.

**Walls where there are none.**
Wardrobes, fridges, open doors and bookshelves that reach near the ceiling are
indistinguishable from walls for a scanner. Close doors, and delete the extra wall in
`plan.json` (remove it from `walls`), then `levanta render plan.json`.

**The sizes are a bit small.**
Video-only scale is typically 5–15 % short. Pass `--focal-px`, or measure a door and use
`--door-width 0.90` (also works afterwards with `levanta render`).

**Can it do several floors?**
Film one floor per video and run levanta once per floor. Stairs are not modelled.

**Can it get the interior from Google Maps / satellite?**
No, and neither can anything else: no sensor sees through a roof. `levanta site` gives
what overhead data does contain, footprint and height, as an LOD1 block.

**Is my data uploaded anywhere?**
No. Everything runs on your machine. The only network access is the optional download of
model weights (HuggingFace) and the public map APIs for `levanta site`.

**Can I use it commercially?**
Yes. MIT license: keep the copyright notice.
