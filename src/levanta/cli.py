"""Command line: ``levanta --help``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

if hasattr(sys.stdout, "reconfigure"):  # UTF-8 console output on Windows
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(add_completion=False, no_args_is_help=True, help="From a phone video or public building data to floor plans and 3D models.")


def _parse_vec(s: str | None) -> tuple[float, float, float] | None:
    if not s:
        return None
    parts = [float(v) for v in s.replace(";", ",").split(",")]
    if len(parts) != 3:
        raise typer.BadParameter("expected three comma-separated numbers, e.g. 0,0,1")
    return (parts[0], parts[1], parts[2])


def _run_plan(cloud, out: Path, stem: str, manhattan: bool, up: str | None, title: str | None, ceiling: bool, debug_png: bool, voxel: float):
    from levanta.io.export import export_all
    from levanta.plan.pipeline import PlanOptions, extract_floor_plan

    opts = PlanOptions(manhattan=manhattan, up_hint=_parse_vec(up), voxel=voxel or None)
    result = extract_floor_plan(cloud, opts)
    out.mkdir(parents=True, exist_ok=True)
    paths = export_all(result.plan, out, stem=stem, title=title, include_ceiling=ceiling)
    result.cloud.save_ply(out / f"{stem}_cloud.ply")
    if debug_png:
        from levanta.plan.debug import render_debug

        render_debug(result, path=out / f"{stem}_debug.png")
    typer.echo(result.plan.summary())
    typer.echo("wrote: " + ", ".join(str(p) for p in paths.values()))
    return result


@app.command()
def plan(
    cloud: Path = typer.Argument(..., exists=True, help="Point cloud (.ply) in metres; normals/cameras used when present."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory."),
    stem: str = typer.Option("plan", help="Base name of the output files."),
    manhattan: bool = typer.Option(True, "--manhattan/--free", help="Snap walls to two orthogonal directions."),
    up: str | None = typer.Option(None, help="Up vector hint in the cloud frame, e.g. '0,-1,0' for raw OpenCV frames."),
    title: str | None = typer.Option(None, help="Title printed on the SVG."),
    ceiling: bool = typer.Option(False, help="Include a ceiling slab in the 3D model."),
    debug_png: bool = typer.Option(True, help="Write a diagnostic PNG next to the outputs."),
    voxel: float = typer.Option(0.02, help="Voxel size for thinning (0 = off)."),
) -> None:
    """Floor plan (SVG/DXF/JSON) and 3D model (GLB/OBJ) from a point cloud."""
    from levanta.scene import PointCloud

    pc = PointCloud.load_ply(cloud)
    _run_plan(pc, out, stem, manhattan, up, title, ceiling, debug_png, voxel)


@app.command()
def tum(
    seq_dir: Path = typer.Argument(..., exists=True, help="TUM RGB-D sequence directory (rgb/, depth/, groundtruth.txt)."),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    stem: str = typer.Option("plan"),
    frame_stride: int = typer.Option(3, help="Use every N-th frame."),
    pixel_stride: int = typer.Option(4, help="Keep one pixel every N in each direction."),
    max_frames: int | None = typer.Option(None),
    manhattan: bool = typer.Option(True, "--manhattan/--free"),
    title: str | None = typer.Option(None),
    ceiling: bool = typer.Option(False),
    debug_png: bool = typer.Option(True),
) -> None:
    """Demo on a public TUM RGB-D sequence (depth + ground-truth poses; no GPU needed)."""
    from levanta.io.tum import load_tum_sequence
    from levanta.recon.rgbd import fuse_frames

    frames = load_tum_sequence(seq_dir, stride=frame_stride, max_frames=max_frames)
    typer.echo(f"loaded {len(frames)} frames")
    cloud = fuse_frames(frames, stride=pixel_stride, voxel=0.02)
    typer.echo(f"fused {len(cloud):,} points from {len(cloud.cameras)} cameras")
    _run_plan(cloud, out, stem, manhattan, None, title or seq_dir.name, ceiling, debug_png, 0.0)


@app.command()
def frames(
    video: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("frames"), "--out", "-o"),
    fps: float = typer.Option(2.0, help="Target frames per second to keep."),
    max_frames: int | None = typer.Option(None),
    max_side: int = typer.Option(1024, help="Downscale so the longest side is at most this."),
    min_sharpness: float = typer.Option(20.0, help="Drop frames blurrier than this (Laplacian variance)."),
) -> None:
    """Pick sharp, evenly spaced frames from a video."""
    from levanta.io.video import extract_frames

    kept = extract_frames(video, out, fps=fps, max_frames=max_frames, max_side=max_side, min_sharpness=min_sharpness)
    typer.echo(f"kept {len(kept)} frames in {out}")


@app.command()
def reconstruct(
    frames_dir: Path = typer.Argument(..., exists=True, help="Directory of JPEG/PNG frames."),
    out: Path = typer.Option(Path("cloud.ply"), "--out", "-o"),
    backend: str = typer.Option("mapanything"),
    model: str = typer.Option("facebook/map-anything-apache", help="HuggingFace checkpoint (the Apache-2.0 one by default)."),
    max_views: int = typer.Option(32, help="Views passed to the network (VRAM bound)."),
    stride: int = typer.Option(2, help="Pixel stride when lifting depth maps."),
) -> None:
    """Metric point cloud from RGB frames (needs the recon extras and a GPU for speed)."""
    from levanta.recon.base import get_backend
    from levanta.scene import Frame

    paths = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not paths:
        raise typer.BadParameter(f"no images in {frames_dir}")
    if len(paths) > max_views:
        idx = [round(i * (len(paths) - 1) / (max_views - 1)) for i in range(max_views)]
        paths = [paths[i] for i in idx]
    kwargs = {"model_name": model, "max_views": max_views, "stride": stride} if backend == "mapanything" else {}
    be = get_backend(backend, **kwargs)
    cloud = be.reconstruct([Frame(path=p) for p in paths])
    out.parent.mkdir(parents=True, exist_ok=True)
    cloud.save_ply(out)
    typer.echo(f"wrote {len(cloud):,} points from {len(paths)} views to {out}")


@app.command()
def video(
    video: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    stem: str = typer.Option("plan"),
    fps: float = typer.Option(1.0),
    max_views: int = typer.Option(32),
    model: str = typer.Option("facebook/map-anything-apache"),
    manhattan: bool = typer.Option(True, "--manhattan/--free"),
    up: str | None = typer.Option(None, help="Up hint; defaults to the mean camera up."),
    title: str | None = typer.Option(None),
    ceiling: bool = typer.Option(False),
) -> None:
    """One shot: video -> frames -> MapAnything -> floor plan + 3D model."""
    from levanta.io.video import extract_frames
    from levanta.recon.mapanything import MapAnythingBackend
    from levanta.scene import Frame

    out.mkdir(parents=True, exist_ok=True)
    kept = extract_frames(video, out / "frames", fps=fps, max_frames=max_views)
    typer.echo(f"{len(kept)} frames")
    be = MapAnythingBackend(model_name=model, max_views=max_views)
    cloud = be.reconstruct([Frame(path=k.path) for k in kept])
    cloud.save_ply(out / f"{stem}_recon.ply")
    typer.echo(f"{len(cloud):,} points")
    _run_plan(cloud, out, stem, manhattan, up, title or video.stem, ceiling, True, 0.0)


@app.command()
def model(
    plan_json: Path = typer.Argument(..., exists=True, help="A plan .json written by 'levanta plan'."),
    out: Path = typer.Option(Path("model.glb"), "--out", "-o", help=".glb or .obj"),
    ceiling: bool = typer.Option(False),
) -> None:
    """Rebuild the 3D model (GLB/OBJ) from a saved plan."""
    from levanta.io.export import export_glb, export_obj
    from levanta.plan.types import FloorPlan

    fp = FloorPlan.from_json(plan_json)
    (export_obj if out.suffix.lower() == ".obj" else export_glb)(fp, out, include_ceiling=ceiling)
    typer.echo(f"wrote {out}")


@app.command()
def site(
    lat: float = typer.Option(..., help="Latitude (WGS84)."),
    lon: float = typer.Option(..., help="Longitude (WGS84)."),
    out: Path = typer.Option(Path("site"), "--out", "-o"),
    stem: str = typer.Option("site"),
    source: str = typer.Option("osm", help="'osm' (Overpass, no extras) or 'overture' (needs the overture extras)."),
    radius: float = typer.Option(60.0, help="Search radius in metres."),
    all_buildings: bool = typer.Option(False, help="Model every building in the radius, not only the one at the point."),
) -> None:
    """Building footprint + height from public data -> LOD1 3D model and site plan."""
    from levanta.site.lod1 import export_site
    from levanta.site.sources import fetch_buildings

    buildings = fetch_buildings(lat, lon, radius_m=radius, source=source)
    if not buildings:
        typer.echo("no building found there in the chosen source")
        raise typer.Exit(code=1)
    paths = export_site(buildings, lat, lon, out, stem=stem, only_target=not all_buildings)
    for b in buildings[:1] if not all_buildings else buildings:
        typer.echo(json.dumps(b.describe(), indent=2, ensure_ascii=False))
    typer.echo("wrote: " + ", ".join(str(p) for p in paths.values()))


@app.command()
def version() -> None:
    from levanta import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
