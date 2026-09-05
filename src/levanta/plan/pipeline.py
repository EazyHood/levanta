"""The point-cloud -> floor-plan pipeline, end to end.

Steps (each is a plain function in a sibling module, so any of them can be swapped):

1. normals (if missing) and oriented towards the observing camera
2. voxel thinning
3. gravity alignment: up = +z, floor = 0, ceiling height measured   (:mod:`gravity`)
4. Manhattan rotation so walls run along x / y                       (:mod:`walls`)
5. rasters: height coverage, floor, camera line-of-sight             (:mod:`occupancy`)
6. wall faces per direction family -> paired into wall lines         (:mod:`walls`)
7. gaps -> doors / passages, corners snapped, windows                (:mod:`rooms`)
8. room polygons from the pockets between wall bodies                (:mod:`rooms`)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from levanta.geometry import estimate_normals_pca, make_pose, orient_normals_towards, rot_z, unit
from levanta.plan.gravity import GravityResult, align_to_gravity
from levanta.plan.occupancy import Grid, count_raster, coverage_raster, dilate, free_space_raster
from levanta.plan.rooms import LineOpening, build_rooms, detect_windows, resolve_gaps, snap_corners
from levanta.plan.tidy import close_outline_gaps, drop_stubs, tidy_walls
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from levanta.plan.walls import (
    Face,
    WallLine,
    attach_samples,
    build_wall_lines,
    classify_exterior,
    direction_families,
    extract_faces,
    manhattan_angle,
    merge_intervals,
)
from levanta.scene import PointCloud


@dataclass
class PlanOptions:
    """Knobs of :func:`extract_floor_plan`.  Distances are metres."""

    manhattan: bool = True
    up_hint: tuple[float, float, float] | None = None
    voxel: float | None = 0.02
    cell: float = 0.02
    coverage_cell: float = 0.10
    station_bin: float = 0.10
    z_band: float = 0.15
    min_coverage_frac: float = 0.35
    cell_coverage_frac: float = 0.25
    wall_z_min: float = 0.10
    wall_top_margin: float = 0.10
    wall_max_nz: float = 0.35
    angle_tol_deg: float = 20.0
    s_bin: float = 0.03
    s_tol: float = 0.06
    gap_tol: float = 0.30
    min_wall_len: float = 0.40
    min_peak_points: int = 30
    min_thickness: float = 0.04
    max_thickness: float = 0.45
    default_interior_thickness: float = 0.10
    default_exterior_thickness: float = 0.20
    snap_dist: float = 0.45
    door_min: float = 0.55
    door_max: float = 1.30
    free_min: float = 0.35
    unseen_merge_max: float = 2.5
    default_door_height: float = 2.05
    default_ceiling: float = 2.50
    min_room_area: float = 1.5
    min_room_inside_frac: float = 0.25
    room_fallback: bool = True
    room_min_jog: float = 0.9
    room_snap_dist: float = 1.0
    tidy: bool = True
    wall_attach_dist: float = 0.20
    wall_trim_margin: float = 0.10
    stub_max_len: float = 0.6
    detect_windows: bool = True
    max_rays: int = 150_000
    seed: int = 0


@dataclass
class PlanResult:
    plan: FloorPlan
    cloud: PointCloud  # in the plan frame
    gravity: GravityResult
    grid: Grid
    rasters: dict[str, np.ndarray]
    lines: list[WallLine]
    faces: list[Face]
    debug: dict[str, Any] = field(default_factory=dict)


def extract_floor_plan(cloud: PointCloud, options: PlanOptions | None = None) -> PlanResult:
    opts = options or PlanOptions()
    debug: dict[str, Any] = {"input_points": len(cloud)}

    # 1. normals
    c = cloud
    oriented = True
    if c.normals is None:
        normals = estimate_normals_pca(c.xyz)
        centers = c.point_camera_centers()
        if centers is not None:
            normals = orient_normals_towards(c.xyz, normals, centers)
        else:
            oriented = False
        c = PointCloud(xyz=c.xyz, normals=normals, colors=c.colors, view=c.view, cameras=c.cameras, meta=dict(c.meta))
    debug["normals_oriented"] = oriented

    # 2. thinning
    if opts.voxel:
        c = c.voxel_downsampled(opts.voxel, seed=opts.seed)
    debug["points_after_voxel"] = len(c)

    # 3. gravity
    aligned, grav = align_to_gravity(c, hint=np.asarray(opts.up_hint) if opts.up_hint is not None else None)
    ceiling_measured = grav.ceiling_height is not None
    ceiling_h = float(grav.ceiling_height) if ceiling_measured else opts.default_ceiling
    T_total = grav.T.copy()

    # 4. Manhattan rotation
    z = aligned.xyz[:, 2]
    nz = aligned.normals[:, 2]
    z_top = ceiling_h - opts.wall_top_margin if ceiling_measured else 3.5
    wall_m = (np.abs(nz) < opts.wall_max_nz) & (z > opts.wall_z_min) & (z < z_top)
    if wall_m.sum() < opts.min_peak_points:
        raise ValueError("too few wall points; is the cloud metric and roughly upright?")
    nxy0 = unit(aligned.normals[wall_m, :2])
    if opts.manhattan:
        phi = manhattan_angle(nxy0)
        phi = float(np.mod(phi + np.pi / 4, np.pi / 2) - np.pi / 4)  # smallest rotation that aligns
        Tz = make_pose(rot_z(-phi), np.zeros(3))
        aligned = aligned.transformed(Tz)
        T_total = Tz @ T_total
        alphas = [0.0, np.pi / 2]
        debug["manhattan_angle_deg"] = float(np.rad2deg(phi))
    else:
        alphas = direction_families(nxy0)
        debug["direction_families_deg"] = [float(np.rad2deg(a)) for a in alphas]

    xyz = aligned.xyz
    nrm = aligned.normals
    z = xyz[:, 2]
    wall_xy = xyz[wall_m, :2]
    wall_n = unit(nrm[wall_m, :2])
    wall_z = z[wall_m]

    # 5. rasters
    cgrid = Grid.from_points(xyz[:, :2], opts.coverage_cell)
    cov = coverage_raster(cgrid, wall_xy, wall_z, opts.z_band, z_top)
    # A sensor with a narrow field of view, or a sparse feed-forward reconstruction, may
    # never reach the top of the walls.  Height coverage is then judged against the height
    # the capture actually reached (95th percentile of wall points), not the ceiling.
    z_seen_top = float(min(z_top, np.percentile(wall_z, 95)))
    n_bands_total = (z_seen_top - opts.wall_z_min) / opts.z_band
    debug["z_seen_top"] = z_seen_top
    min_bands = max(2.0, opts.min_coverage_frac * n_bands_total)
    keep = cgrid.sample(cov, wall_xy) >= max(2.0, opts.cell_coverage_frac * n_bands_total)
    raw_xy, raw_n, raw_z = wall_xy, wall_n, wall_z  # unfiltered, for edge refinement
    wall_xy, wall_n, wall_z = wall_xy[keep], wall_n[keep], wall_z[keep]
    debug["wall_points"] = len(wall_xy)

    grid = Grid.from_points(xyz[:, :2], opts.cell)
    floor_m = (nrm[:, 2] > 0.9) & (np.abs(z) < 0.08)
    floor_r = count_raster(grid, xyz[floor_m, :2]) > 0
    cams = aligned.point_camera_centers()
    if cams is not None:
        free_r = free_space_raster(grid, xyz[:, :2], cams[:, :2], max_rays=opts.max_rays, seed=opts.seed)
    else:
        free_r = np.zeros(grid.shape, dtype=bool)
    inside = floor_r | free_r
    # Seen floor, plus line of sight within half a metre of it: what the fallback room
    # outline may follow.  Sight lines far from any seen floor (through a doorway into an
    # unscanned corridor) are excluded.
    inside_strict = floor_r | (free_r & dilate(floor_r, round(0.5 / opts.cell)))
    debug["has_cameras"] = cams is not None

    # 6. faces and wall lines
    faces: list[Face] = []
    for alpha in alphas:
        faces += extract_faces(
            wall_xy,
            wall_n,
            wall_z,
            alpha,
            angle_tol_deg=opts.angle_tol_deg,
            s_bin=opts.s_bin,
            s_tol=opts.s_tol,
            gap_tol=opts.gap_tol,
            min_len=opts.min_wall_len,
            min_peak_points=opts.min_peak_points,
            z_band=opts.z_band,
            min_bands=min_bands,
            z_top=z_seen_top if ceiling_measured else None,
            total_bands=n_bands_total,
            t_bin=opts.station_bin,
        )
    lines: list[WallLine] = []
    for alpha in alphas:
        lines += build_wall_lines(
            faces,
            alpha,
            min_thickness=opts.min_thickness,
            max_thickness=opts.max_thickness,
            default_thickness=opts.default_interior_thickness,
            first_id=len(lines),
        )
    for ln in lines:
        if ln.sides_seen == 1:
            ln.exterior = classify_exterior(ln, inside, grid)
            th = opts.default_exterior_thickness if ln.exterior else opts.default_interior_thickness
            f = ln.faces[0]
            ln.thickness = th
            ln.s = f.s - f.sign * th / 2.0
        else:
            ln.exterior = False
    attach_samples(lines, raw_xy, raw_n, raw_z, s_tol=opts.s_tol, angle_tol_deg=opts.angle_tol_deg)
    debug["faces"] = len(faces)
    debug["wall_lines"] = len(lines)

    # 7. openings
    openings: list[LineOpening] = resolve_gaps(
        lines,
        free_r,
        grid,
        door_min=opts.door_min,
        door_max=opts.door_max,
        free_min=opts.free_min,
        unseen_merge_max=opts.unseen_merge_max,
        default_door_height=opts.default_door_height,
        ceiling_height=ceiling_h,
    )
    openings += snap_corners(
        lines,
        free_r,
        grid,
        snap_dist=opts.snap_dist,
        door_min=opts.door_min,
        free_min=opts.free_min,
        default_door_height=opts.default_door_height,
        ceiling_height=ceiling_h,
    )
    if opts.detect_windows:
        openings += detect_windows(lines, ceiling_height=ceiling_h)

    # 8. rooms
    room_polys = build_rooms(
        lines,
        openings,
        inside,
        grid,
        min_area=opts.min_room_area,
        min_inside_frac=opts.min_room_inside_frac,
        inside_strict=inside_strict,
        fallback=opts.room_fallback,
        camera_xy=None if aligned.cameras is None else aligned.camera_centers[:, :2],
        manhattan=opts.manhattan,
        room_min_jog=opts.room_min_jog,
        room_snap_dist=opts.room_snap_dist,
    )

    plan = _assemble(lines, openings, room_polys, ceiling_h, ceiling_measured, T_total, opts, grav, debug, source=str(cloud.meta.get("source", "")))
    if opts.tidy:
        plan = tidy_walls(plan, attach_dist=opts.wall_attach_dist, trim_margin=opts.wall_trim_margin, min_len=opts.min_wall_len)
        plan = drop_stubs(plan, max_len=opts.stub_max_len)
        plan = close_outline_gaps(
            plan,
            free_r,
            grid,
            door_range=(opts.door_min, opts.door_max),
            free_min=opts.free_min,
            default_thickness=opts.default_interior_thickness,
            default_door_height=opts.default_door_height,
        )
    plan.label_openings()
    return PlanResult(
        plan=plan,
        cloud=aligned,
        gravity=grav,
        grid=grid,
        rasters={"coverage": cov, "floor": floor_r, "free": free_r, "inside": inside, "inside_strict": inside_strict},
        lines=lines,
        faces=faces,
        debug=debug,
    )


def _assemble(
    lines: list[WallLine],
    openings: list[LineOpening],
    room_polys: list[tuple[Polygon, bool]],
    ceiling_h: float,
    ceiling_measured: bool,
    T_total: np.ndarray,
    opts: PlanOptions,
    grav: GravityResult,
    debug: dict[str, Any],
    source: str = "",
) -> FloorPlan:
    walls: list[Wall] = []
    plan_openings: list[Opening] = []
    for ln in lines:
        # A door bridges two intervals: the wall is one piece with an opening cut into it.
        bridged = merge_intervals(
            ln.intervals + [(o.t0, o.t1) for o in openings if o.line_id == ln.id and o.kind in ("door", "passage")], 1e-6
        )
        for t0, t1 in bridged:
            wid = len(walls)
            a, b = ln.point(t0), ln.point(t1)
            walls.append(
                Wall(
                    id=wid,
                    a=(float(a[0]), float(a[1])),
                    b=(float(b[0]), float(b[1])),
                    thickness=float(ln.thickness),
                    height=float(ceiling_h),
                    sides_seen=ln.sides_seen,
                    line_id=ln.id,
                    exterior=bool(ln.exterior),
                )
            )
            for o in openings:
                if o.line_id == ln.id and o.t0 >= t0 - 1e-6 and o.t1 <= t1 + 1e-6:
                    plan_openings.append(
                        Opening(
                            id=len(plan_openings),
                            wall_id=wid,
                            kind=o.kind,
                            t0=float(o.t0 - t0),
                            t1=float(o.t1 - t0),
                            z0=float(o.z0),
                            z1=float(o.z1),
                            height_measured=bool(o.measured),
                        )
                    )

    rooms: list[Room] = []
    for i, (poly, closed) in enumerate(room_polys):
        p = orient(poly, sign=1.0)
        rooms.append(
            Room(
                id=i,
                name=f"Room {i + 1}",
                polygon=[(float(x), float(y)) for x, y in list(p.exterior.coords)[:-1]],
                holes=[[(float(x), float(y)) for x, y in list(h.coords)[:-1]] for h in p.interiors],
                closed=closed,
            )
        )
    # which rooms does each opening connect?
    wall_by_id = {w.id: w for w in walls}
    for o in plan_openings:
        w = wall_by_id[o.wall_id]
        seg = LineString([w.point_at(o.t0), w.point_at(o.t1)]).buffer(w.thickness / 2 + 0.05, cap_style="flat")
        o.rooms = tuple(r.id for r in rooms if r.shapely.intersects(seg))

    meta = {
        "options": asdict(opts),
        "gravity": {
            "up_in_input_frame": [float(v) for v in grav.up],
            "floor_support": grav.floor_support,
            "ceiling_support": grav.ceiling_support,
        },
        "debug": debug,
        "source": source,
    }
    return FloorPlan(
        walls=walls,
        rooms=rooms,
        openings=plan_openings,
        ceiling_height=float(ceiling_h),
        ceiling_measured=ceiling_measured,
        transform=T_total.tolist(),
        meta=meta,
    )
