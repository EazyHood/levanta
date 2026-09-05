"""Command line: ``levanta --help``.

Commands, in the order a first-time user meets them:

  demo         see it work in ten seconds, no data needed
  check        is my video good enough?  (before spending GPU minutes)
  video        phone video -> plan + 3D model (needs the recon extras and a GPU)
  plan         point cloud (.ply) -> plan + 3D model
  tum          public RGB-D sequence -> plan (no GPU)
  site         a coordinate -> building footprint, height, LOD1 model
  render       re-make every output from a saved plan.json (after editing names)
  doctor       what is installed, what is missing, what to type
"""

from __future__ import annotations

import sys
import time
import webbrowser
from pathlib import Path

import typer

if hasattr(sys.stdout, "reconfigure"):  # UTF-8 console output on Windows
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="From a phone video, a point cloud or public building data to floor plans and 3D models.\n\nStart with [bold]levanta demo[/bold]; then [bold]levanta check your_video.mp4[/bold].",
)

LANG_OPT = typer.Option("en", "--lang", help="Language of the labels: en | es.")
UNITS_OPT = typer.Option("m", "--units", help="Units on the drawings: m | ft.")
TITLE_OPT = typer.Option(None, "--title", help="Title printed on the plan.")
NAMES_OPT = typer.Option(None, "--names", help="Room names in order of size, comma separated: 'Living,Kitchen,Bath'.")
OPEN_OPT = typer.Option(False, "--open", help="Open the HTML viewer when done.")
CEILING_OPT = typer.Option(False, "--ceiling", help="Include a ceiling slab in the 3D model.")
SCALE_OPT = typer.Option(None, "--scale", help="Multiply every length by this factor (fix the global scale of a video reconstruction).")
DOOR_OPT = typer.Option(None, "--door-width", help="Rescale so that the median detected door is this wide (e.g. 0.90). A good fix when the video scale is off.")
PROJECT_OPT = typer.Option(None, "--project", help="Project name for the title block.")
AUTHOR_OPT = typer.Option(None, "--author", help="Author for the title block.")
SHEET_OPT = typer.Option(None, "--sheet", help="Sheet number for the title block (e.g. A-01).")
REV_OPT = typer.Option(None, "--revision", help="Revision letter/number for the title block.")
LEVEL_OPT = typer.Option(None, "--level", help="Finished floor level label, e.g. '+0.00' or '+3.20'.")
NORTH_OPT = typer.Option(None, "--north", help="Where north points: degrees clockwise from the plan's up direction (0 = north is up).")
PAPER_OPT = typer.Option("A4", "--paper", help="Paper for the PDF: A4 | A3 | A2 | A1 | Letter | Tabloid (landscape).")
DXF_UNITS_OPT = typer.Option("m", "--dxf-units", help="Units of the DXF: m | cm | mm.")


# ----------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------


def _step(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.CYAN)


def _ok(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.GREEN)


def _warn(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.YELLOW)


def _fail(msg: str, code: int = 1) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _parse_vec(s: str | None) -> tuple[float, float, float] | None:
    if not s:
        return None
    parts = [float(v) for v in s.replace(";", ",").split(",")]
    if len(parts) != 3:
        raise typer.BadParameter("expected three comma-separated numbers, e.g. 0,0,1")
    return (parts[0], parts[1], parts[2])


def _finish(plan, out: Path, stem: str, title: str | None, lang: str, units: str, ceiling: bool, names: str | None, scale: float | None, door_width: float | None, open_html: bool, project: dict | None = None, north: float | None = None, paper: str = "A4", dxf_units: str = "m"):
    """Apply edits (names, scale), write every output, print a human summary."""
    from levanta.i18n import fmt_area, fmt_len, t
    from levanta.io.export import export_all

    if door_width:
        plan, factor = plan.calibrated_to_door_width(door_width)
        if factor != 1.0:
            _step(f"scale x{factor:.3f} so that the median door is {door_width:.2f} m wide")
        else:
            _warn("no door detected: --door-width ignored")
    if scale:
        plan = plan.scaled(scale)
        _step(f"scale x{scale:.3f}")
    if names:
        plan.rename_rooms([n.strip() for n in names.split(",")])
    if project:
        plan.project.update({k: v for k, v in project.items() if v})
    if north is not None:
        plan.north_deg = float(north)
    plan.label_openings()
    out.mkdir(parents=True, exist_ok=True)
    paths = export_all(plan, out, stem=stem, title=title, include_ceiling=ceiling, lang=lang, units=units, paper=paper, dxf_units=dxf_units)
    typer.echo("")
    typer.secho(f"{len(plan.rooms)} {t(lang, 'rooms')} · {fmt_area(plan.total_area, units)} · {t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)} ({t(lang, 'measured') if plan.ceiling_measured else t(lang, 'default')})", bold=True)
    for r in plan.rooms:
        b = r.shapely.bounds
        flag = "" if r.closed else f"  ({t(lang, 'incomplete')})"
        typer.echo(f"  {r.name:<14} {fmt_area(r.area, units):>10}   {fmt_len(b[2] - b[0], units)} × {fmt_len(b[3] - b[1], units)}{flag}")
    for o in plan.openings:
        typer.echo(f"  {o.tag:<4}{t(lang, o.kind):<10} {fmt_len(o.width, units):>10}   z {o.z0:.2f}–{o.z1:.2f} m")
    typer.echo("")
    for q in plan.quality(lang):
        typer.secho(f"  {'!' if q['level'] == 'warn' else '·'} {q['text']}", fg=typer.colors.YELLOW if q["level"] == "warn" else None)
    if not plan.rooms:
        _warn("no room was closed by walls; open the debug PNG to see what was scanned (walls need floor-to-ceiling coverage on at least three sides).")
    typer.echo("")
    _ok(f"open  {paths['html']}")
    typer.echo("also  " + ", ".join(p.name for k, p in paths.items() if k != "html"))
    if open_html:
        webbrowser.open(paths["html"].resolve().as_uri())
    return plan, paths


def _run_plan(cloud, out: Path, stem: str, manhattan: bool, up: str | None, debug_png: bool, voxel: float | None):
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan

    t0 = time.time()
    _step(f"planning from {len(cloud):,} points" + (f" and {len(cloud.cameras)} cameras" if cloud.cameras is not None else ""))
    try:
        result = extract_floor_plan(cloud, PlanOptions(manhattan=manhattan, up_hint=_parse_vec(up), voxel=voxel))
    except ValueError as e:
        _fail(f"planning failed: {e}\n  Is the cloud in metres and roughly upright?  Try --up 0,-1,0 for raw camera-frame clouds.")
    out.mkdir(parents=True, exist_ok=True)
    result.cloud.save_ply(out / f"{stem}_cloud.ply")
    if debug_png:
        from levanta.plan.debug import render_debug

        render_debug(result, path=out / f"{stem}_debug.png")
    _ok(f"plan ready ({time.time() - t0:.0f} s): {len(result.plan.walls)} walls, {len(result.plan.rooms)} rooms, {len(result.plan.openings)} openings")
    return result


# ----------------------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------------------


@app.command()
def demo(
    out: Path = typer.Option(Path("levanta-demo"), "--out", "-o"),
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    open_html: bool = OPEN_OPT,
    project: str | None = PROJECT_OPT,
    author: str | None = AUTHOR_OPT,
    sheet: str | None = SHEET_OPT,
    revision: str | None = REV_OPT,
    level: str | None = LEVEL_OPT,
    north: float | None = NORTH_OPT,
    paper: str = PAPER_OPT,
    dxf_units: str = DXF_UNITS_OPT,
    names: str | None = NAMES_OPT,
    title: str | None = TITLE_OPT,
    scene: str = typer.Option("three_rooms", help="two_rooms | three_rooms"),
) -> None:
    """See levanta work in ten seconds on a synthetic apartment (no data, no GPU)."""
    from levanta.synthetic import sample_apartment, scenes

    if scene not in scenes():
        _fail(f"unknown scene {scene!r}; choose from {sorted(scenes())}")
    apt = scenes()[scene]()
    _step(f"sampling the '{scene}' apartment the way a phone would see it")
    cloud = sample_apartment(apt, seed=7)
    res = _run_plan(cloud, out, "plan", True, None, True, None)
    if names is None:
        names = ",".join(("Living,Bedroom,Hall" if lang == "en" else "Sala,Dormitorio,Pasillo").split(",")[: len(res.plan.rooms)])
    _finish(res.plan, out, "plan", title or ("levanta demo" if lang == "en" else "demo de levanta"), lang, units, False, names, None, None, open_html, project={"name": project, "author": author, "sheet": sheet, "revision": revision, "level": level}, north=north, paper=paper, dxf_units=dxf_units)


@app.command()
def check(
    video: Path = typer.Argument(..., exists=True),
    fps: float = typer.Option(1.0, help="Frames per second the reconstruction will use."),
) -> None:
    """Is this video usable?  Length, resolution, sharpness, how many frames would be kept."""
    from levanta.io.video import inspect_video

    rep = inspect_video(video, fps=fps)
    typer.echo(f"{video.name}: {rep['width']}x{rep['height']}, {rep['duration_s']:.0f} s at {rep['fps']:.0f} fps, {rep['frames']} frames")
    typer.echo(f"sharpness: median {rep['sharpness_median']:.0f}, 10th percentile {rep['sharpness_p10']:.0f}  (below 20 is blurry)")
    typer.echo(f"would keep {rep['usable_frames']} frames at {fps:g} fps ({rep['blurry_windows']} windows had nothing sharp)")
    for w in rep["warnings"]:
        _warn("! " + w)
    if not rep["warnings"]:
        _ok("looks good")


@app.command()
def video(
    video: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    stem: str = typer.Option("plan"),
    fps: float = typer.Option(1.0, help="Frames per second to sample from the video."),
    max_views: int = typer.Option(32, help="Frames given to the network (VRAM bound: 8 GB ~ 24-32 views)."),
    model: str = typer.Option("facebook/map-anything-apache", help="HuggingFace checkpoint (Apache-2.0 by default)."),
    focal_px: float | None = typer.Option(None, "--focal-px", help="Focal length in pixels of the (downscaled) frames, if known; improves the metric scale."),
    manhattan: bool = typer.Option(True, "--manhattan/--free", help="Snap walls to two orthogonal directions."),
    up: str | None = typer.Option(None, help="Up hint; defaults to the mean camera up."),
    title: str | None = TITLE_OPT,
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    ceiling: bool = CEILING_OPT,
    names: str | None = NAMES_OPT,
    scale: float | None = SCALE_OPT,
    door_width: float | None = DOOR_OPT,
    open_html: bool = OPEN_OPT,
    project: str | None = PROJECT_OPT,
    author: str | None = AUTHOR_OPT,
    sheet: str | None = SHEET_OPT,
    revision: str | None = REV_OPT,
    level: str | None = LEVEL_OPT,
    north: float | None = NORTH_OPT,
    paper: str = PAPER_OPT,
    dxf_units: str = DXF_UNITS_OPT,
) -> None:
    """Phone video -> frames -> MapAnything -> floor plan + 3D model (GPU recommended)."""
    from levanta.io.video import extract_frames
    from levanta.recon.mapanything import MISSING, MapAnythingBackend
    from levanta.scene import Camera, Frame

    try:
        import mapanything  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        _fail(MISSING + "\n\nNo GPU?  Run 'levanta doctor'.  You can still use 'levanta plan' on a point cloud from any other tool.")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    _step("picking sharp frames")
    kept = extract_frames(video, out / "frames", fps=fps, max_frames=max_views)
    if len(kept) < 4:
        _fail(f"only {len(kept)} usable frames; the video is too short or too blurry (run 'levanta check').")
    _ok(f"{len(kept)} frames ({time.time() - t0:.0f} s)")
    frames = []
    for k in kept:
        cam = None
        if focal_px:
            import cv2

            h, w = cv2.imread(str(k.path)).shape[:2]
            import numpy as np

            cam = Camera(K=np.array([[focal_px, 0, w / 2], [0, focal_px, h / 2], [0, 0, 1.0]]), T=np.eye(4), width=w, height=h)
        frames.append(Frame(path=k.path, camera=cam))
    _step(f"reconstructing with MapAnything ({model}); the first run downloads ~4.6 GB of weights")
    t1 = time.time()
    be = MapAnythingBackend(model_name=model, max_views=max_views)
    try:
        cloud = be.reconstruct(frames)
    except Exception as e:
        _fail(f"reconstruction failed: {type(e).__name__}: {e}\n  Out of memory?  Lower --max-views.  'OS error 1455' on Windows: close other applications.")
    cloud.save_ply(out / f"{stem}_recon.ply")
    _ok(f"{len(cloud):,} points from {len(frames)} views ({time.time() - t1:.0f} s)")
    res = _run_plan(cloud, out, stem, manhattan, up, True, None)
    if not focal_px and not door_width and not scale:
        _warn("scale from video alone is typically 5-15 % short; pass --focal-px, or --door-width 0.90 to calibrate on the doors")
    _finish(res.plan, out, stem, title or video.stem, lang, units, ceiling, names, scale, door_width, open_html, project={"name": project, "author": author, "sheet": sheet, "revision": revision, "level": level}, north=north, paper=paper, dxf_units=dxf_units)


@app.command()
def plan(
    cloud: Path = typer.Argument(..., exists=True, help="Point cloud (.ply) in metres; normals/cameras are used when present."),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    stem: str = typer.Option("plan"),
    manhattan: bool = typer.Option(True, "--manhattan/--free", help="Snap walls to two orthogonal directions."),
    up: str | None = typer.Option(None, help="Up vector hint in the cloud frame, e.g. '0,-1,0' for raw OpenCV frames."),
    voxel: float = typer.Option(0.02, help="Voxel size for thinning (0 = off)."),
    title: str | None = TITLE_OPT,
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    ceiling: bool = CEILING_OPT,
    names: str | None = NAMES_OPT,
    scale: float | None = SCALE_OPT,
    door_width: float | None = DOOR_OPT,
    open_html: bool = OPEN_OPT,
    project: str | None = PROJECT_OPT,
    author: str | None = AUTHOR_OPT,
    sheet: str | None = SHEET_OPT,
    revision: str | None = REV_OPT,
    level: str | None = LEVEL_OPT,
    north: float | None = NORTH_OPT,
    paper: str = PAPER_OPT,
    dxf_units: str = DXF_UNITS_OPT,
    debug_png: bool = typer.Option(True, help="Write a diagnostic PNG next to the outputs."),
) -> None:
    """Point cloud -> floor plan (HTML/PNG/SVG/DXF/JSON) + 3D model (GLB/OBJ)."""
    from levanta.scene import PointCloud

    pc = PointCloud.load_ply(cloud)
    res = _run_plan(pc, out, stem, manhattan, up, debug_png, voxel or None)
    _finish(res.plan, out, stem, title or cloud.stem, lang, units, ceiling, names, scale, door_width, open_html, project={"name": project, "author": author, "sheet": sheet, "revision": revision, "level": level}, north=north, paper=paper, dxf_units=dxf_units)


@app.command()
def tum(
    seq_dir: Path = typer.Argument(..., exists=True, help="TUM RGB-D sequence directory (rgb/, depth/, groundtruth.txt)."),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    stem: str = typer.Option("plan"),
    frame_stride: int = typer.Option(3, help="Use every N-th frame."),
    pixel_stride: int = typer.Option(4, help="Keep one pixel every N in each direction."),
    max_frames: int | None = typer.Option(None),
    manhattan: bool = typer.Option(True, "--manhattan/--free"),
    title: str | None = TITLE_OPT,
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    ceiling: bool = CEILING_OPT,
    names: str | None = NAMES_OPT,
    open_html: bool = OPEN_OPT,
    project: str | None = PROJECT_OPT,
    author: str | None = AUTHOR_OPT,
    sheet: str | None = SHEET_OPT,
    revision: str | None = REV_OPT,
    level: str | None = LEVEL_OPT,
    north: float | None = NORTH_OPT,
    paper: str = PAPER_OPT,
    dxf_units: str = DXF_UNITS_OPT,
) -> None:
    """Public TUM RGB-D sequence (depth + ground-truth poses) -> plan.  No GPU."""
    from levanta.io.tum import load_tum_sequence
    from levanta.recon.rgbd import fuse_frames

    _step("loading frames")
    frames = load_tum_sequence(seq_dir, stride=frame_stride, max_frames=max_frames)
    _step(f"fusing {len(frames)} depth maps")
    cloud = fuse_frames(frames, stride=pixel_stride, voxel=0.02)
    res = _run_plan(cloud, out, stem, manhattan, None, True, None)
    _finish(res.plan, out, stem, title or seq_dir.name, lang, units, ceiling, names, None, None, open_html, project={"name": project, "author": author, "sheet": sheet, "revision": revision, "level": level}, north=north, paper=paper, dxf_units=dxf_units)


@app.command()
def render(
    plan_json: Path = typer.Argument(..., exists=True, help="A plan.json written by levanta (edit room names in it, then render)."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output directory (default: next to the JSON)."),
    stem: str | None = typer.Option(None, help="Base name (default: the JSON's)."),
    title: str | None = TITLE_OPT,
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    ceiling: bool = CEILING_OPT,
    names: str | None = NAMES_OPT,
    scale: float | None = SCALE_OPT,
    door_width: float | None = DOOR_OPT,
    open_html: bool = OPEN_OPT,
    project: str | None = PROJECT_OPT,
    author: str | None = AUTHOR_OPT,
    sheet: str | None = SHEET_OPT,
    revision: str | None = REV_OPT,
    level: str | None = LEVEL_OPT,
    north: float | None = NORTH_OPT,
    paper: str = PAPER_OPT,
    dxf_units: str = DXF_UNITS_OPT,
) -> None:
    """Re-make every output (HTML, PNG, SVG, DXF, GLB, OBJ) from a saved plan.json."""
    from levanta.plan.types import FloorPlan

    fp = FloorPlan.from_json(plan_json)
    _finish(fp, out or plan_json.parent, stem or plan_json.stem, title, lang, units, ceiling, names, scale, door_width, open_html, project={"name": project, "author": author, "sheet": sheet, "revision": revision, "level": level}, north=north, paper=paper, dxf_units=dxf_units)


@app.command()
def frames(
    video: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("frames"), "--out", "-o"),
    fps: float = typer.Option(1.0, help="Target frames per second to keep."),
    max_frames: int | None = typer.Option(None),
    max_side: int = typer.Option(1024, help="Downscale so the longest side is at most this."),
    min_sharpness: float = typer.Option(20.0, help="Drop frames blurrier than this (Laplacian variance)."),
) -> None:
    """Pick sharp, evenly spaced frames from a video (what 'video' does first)."""
    from levanta.io.video import extract_frames

    kept = extract_frames(video, out, fps=fps, max_frames=max_frames, max_side=max_side, min_sharpness=min_sharpness)
    _ok(f"kept {len(kept)} frames in {out}")


@app.command()
def reconstruct(
    frames_dir: Path = typer.Argument(..., exists=True, help="Directory of JPEG/PNG frames."),
    out: Path = typer.Option(Path("cloud.ply"), "--out", "-o"),
    model: str = typer.Option("facebook/map-anything-apache"),
    max_views: int = typer.Option(32),
    stride: int = typer.Option(2, help="Pixel stride when lifting depth maps."),
) -> None:
    """RGB frames -> metric point cloud with MapAnything (what 'video' does second)."""
    from levanta.recon.mapanything import MapAnythingBackend
    from levanta.scene import Frame

    paths = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not paths:
        _fail(f"no images in {frames_dir}")
    if len(paths) > max_views:
        idx = [round(i * (len(paths) - 1) / (max_views - 1)) for i in range(max_views)]
        paths = [paths[i] for i in idx]
    be = MapAnythingBackend(model_name=model, max_views=max_views, stride=stride)
    cloud = be.reconstruct([Frame(path=p) for p in paths])
    out.parent.mkdir(parents=True, exist_ok=True)
    cloud.save_ply(out)
    _ok(f"wrote {len(cloud):,} points from {len(paths)} views to {out}")


@app.command()
def model(
    plan_json: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("model.glb"), "--out", "-o", help=".glb or .obj"),
    ceiling: bool = CEILING_OPT,
) -> None:
    """Only the 3D model (GLB/OBJ) from a saved plan.json."""
    from levanta.io.export import export_glb, export_obj
    from levanta.plan.types import FloorPlan

    fp = FloorPlan.from_json(plan_json)
    (export_obj if out.suffix.lower() == ".obj" else export_glb)(fp, out, include_ceiling=ceiling)
    _ok(f"wrote {out}")


@app.command()
def site(
    lat: float = typer.Option(..., help="Latitude (WGS84)."),
    lon: float = typer.Option(..., help="Longitude (WGS84)."),
    out: Path = typer.Option(Path("site"), "--out", "-o"),
    stem: str = typer.Option("site"),
    source: str = typer.Option("osm", help="'osm' (Overpass, no extras) or 'overture' (pip install levanta[overture])."),
    radius: float = typer.Option(60.0, help="Search radius in metres."),
    all_buildings: bool = typer.Option(False, help="Model every building in the radius, not only the one at the point."),
    lang: str = LANG_OPT,
    units: str = UNITS_OPT,
    open_html: bool = OPEN_OPT,
    paper: str = PAPER_OPT,
) -> None:
    """A coordinate -> building footprint + height from public data -> LOD1 model + site plan."""
    from levanta.site.lod1 import export_site
    from levanta.site.sources import fetch_buildings

    _step(f"asking {source} for buildings within {radius:.0f} m of {lat:.5f}, {lon:.5f}")
    try:
        buildings = fetch_buildings(lat, lon, radius_m=radius, source=source)
    except Exception as e:
        _fail(f"could not fetch buildings: {type(e).__name__}: {e}\n  No internet, or the Overpass API is busy: try again in a minute.")
    if not buildings:
        _fail("no building there in the chosen source; try --radius 150, --source overture, or check the coordinate on openstreetmap.org")
    paths = export_site(buildings, lat, lon, out, stem=stem, only_target=not all_buildings, lang=lang, units=units, paper=paper)
    b = buildings[0]
    h, how = b.height()
    _ok(f"{b.name or b.id}: {h:.1f} m ({how}), {len(b.footprint)} corners, {b.attribution}")
    typer.echo("open  " + str(paths.get("html", paths["svg"])))
    typer.echo("also  " + ", ".join(p.name for k, p in paths.items() if k != "html"))
    if open_html and "html" in paths:
        webbrowser.open(paths["html"].resolve().as_uri())


@app.command()
def doctor() -> None:
    """What is installed, what is missing, and what to type to fix it."""
    import importlib
    import platform

    from levanta import __version__

    typer.echo(f"levanta {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    core = ["numpy", "scipy", "shapely", "trimesh", "ezdxf", "cv2", "PIL"]
    for m in core:
        try:
            importlib.import_module(m)
            _ok(f"  ok   {m}")
        except ImportError:
            typer.secho(f"  MISSING {m}  ->  pip install levanta", fg=typer.colors.RED)
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            _ok(f"  ok   torch {torch.__version__} · GPU {torch.cuda.get_device_name(0)} · {total / 1e9:.1f} GB ({free / 1e9:.1f} free)")
            if total < 7.5e9:
                _warn("       <8 GB VRAM: use --max-views 12-16")
        else:
            _warn(f"  warn torch {torch.__version__} without CUDA: MapAnything will run on the CPU (very slow). Install a CUDA build from https://pytorch.org/get-started/locally/")
    except ImportError:
        _warn("  missing torch  ->  pip install torch --index-url https://download.pytorch.org/whl/cu128  (or see pytorch.org for your CUDA)")
    try:
        importlib.import_module("mapanything")
        _ok("  ok   mapanything")
        cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--facebook--map-anything-apache"
        if cache.exists():
            _ok("  ok   weights cached (facebook/map-anything-apache)")
        else:
            typer.echo("       weights not downloaded yet (4.6 GB, automatic on first 'levanta video')")
    except ImportError:
        _warn('  missing mapanything  ->  pip install "git+https://github.com/facebookresearch/map-anything.git"')
    try:
        importlib.import_module("overturemaps")
        _ok("  ok   overturemaps (optional)")
    except ImportError:
        typer.echo("  optional overturemaps  ->  pip install levanta[overture]   (OpenStreetMap works without it)")
    typer.echo("\nnext: levanta demo   ·   levanta check my_video.mp4   ·   levanta video my_video.mp4 -o out")


@app.command()
def version() -> None:
    from levanta import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
