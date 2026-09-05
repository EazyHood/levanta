"""FloorPlan -> 3D building model (a :class:`trimesh.Scene`).

Walls are boxes.  Openings are not cut with booleans (fragile); instead the wall is
split along its length into solid pieces, and a sill box and/or lintel box is added
below / above every opening.  The result is watertight per piece and exports cleanly
to GLB, OBJ and STL.
"""

from __future__ import annotations

import numpy as np
import trimesh

from levanta.plan.types import FloorPlan, Opening, Wall

WALL_COLOR = (225, 222, 214, 255)
FLOOR_COLOR = (196, 176, 150, 255)
CEILING_COLOR = (240, 240, 240, 255)
DOOR_COLOR = (150, 110, 70, 255)
GLASS_COLOR = (160, 200, 230, 120)


def wall_pieces(wall: Wall, openings: list[Opening]) -> list[tuple[float, float, float, float]]:
    """Solid boxes (t0, t1, z0, z1) covering the wall minus its openings."""
    h = wall.height
    L = wall.length
    pieces: list[tuple[float, float, float, float]] = []
    cursor = 0.0
    for o in sorted(openings, key=lambda o: o.t0):
        t0, t1 = max(0.0, o.t0), min(L, o.t1)
        if t1 <= cursor:
            continue
        if t0 > cursor + 1e-6:
            pieces.append((cursor, t0, 0.0, h))
        if o.z0 > 0.01:
            pieces.append((t0, t1, 0.0, min(o.z0, h)))
        if o.z1 < h - 0.01:
            pieces.append((t0, t1, max(o.z1, 0.0), h))
        cursor = t1
    if L > cursor + 1e-6:
        pieces.append((cursor, L, 0.0, h))
    return pieces


def _box(wall: Wall, t0: float, t1: float, z0: float, z1: float, thickness: float | None = None) -> trimesh.Trimesh:
    th = wall.thickness if thickness is None else thickness
    d = wall.direction
    n = wall.normal
    R = np.array([[d[0], n[0], 0.0], [d[1], n[1], 0.0], [0.0, 0.0, 1.0]])
    center_local = np.array([(t0 + t1) / 2.0, 0.0, (z0 + z1) / 2.0])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.array([wall.a[0], wall.a[1], 0.0]) + R @ center_local
    return trimesh.creation.box(extents=[t1 - t0, th, z1 - z0], transform=T)


def floor_plan_to_scene(
    plan: FloorPlan,
    include_ceiling: bool = False,
    include_openings: bool = True,
    floor_thickness: float = 0.05,
) -> trimesh.Scene:
    """Build the 3D model.  Doors get a thin leaf, windows a translucent pane, when
    ``include_openings`` is on."""
    scene = trimesh.Scene()
    wall_meshes: list[trimesh.Trimesh] = []
    door_meshes: list[trimesh.Trimesh] = []
    glass_meshes: list[trimesh.Trimesh] = []
    for w in plan.walls:
        ops = plan.openings_of(w.id)
        for t0, t1, z0, z1 in wall_pieces(w, ops):
            if t1 - t0 > 1e-4 and z1 - z0 > 1e-4:
                wall_meshes.append(_box(w, t0, t1, z0, z1))
        if include_openings:
            for o in ops:
                if o.kind == "door":
                    door_meshes.append(_box(w, o.t0, o.t1, 0.0, o.z1, thickness=0.04))
                elif o.kind == "window":
                    glass_meshes.append(_box(w, o.t0, o.t1, o.z0, o.z1, thickness=0.02))
    if wall_meshes:
        walls = trimesh.util.concatenate(wall_meshes)
        walls.visual.face_colors = WALL_COLOR
        scene.add_geometry(walls, geom_name="walls", node_name="walls")
    if door_meshes:
        doors = trimesh.util.concatenate(door_meshes)
        doors.visual.face_colors = DOOR_COLOR
        scene.add_geometry(doors, geom_name="doors", node_name="doors")
    if glass_meshes:
        glass = trimesh.util.concatenate(glass_meshes)
        glass.visual.face_colors = GLASS_COLOR
        scene.add_geometry(glass, geom_name="windows", node_name="windows")
    for r in plan.rooms:
        poly = r.shapely
        if poly.is_empty or not poly.is_valid:
            continue
        slab = trimesh.creation.extrude_polygon(poly, height=floor_thickness)
        slab.apply_translation([0.0, 0.0, -floor_thickness])
        slab.visual.face_colors = FLOOR_COLOR
        scene.add_geometry(slab, geom_name=f"floor_{r.id}", node_name=f"floor_{r.name.replace(' ', '_')}")
        if include_ceiling:
            ceil = trimesh.creation.extrude_polygon(poly, height=0.05)
            ceil.apply_translation([0.0, 0.0, plan.ceiling_height])
            ceil.visual.face_colors = CEILING_COLOR
            scene.add_geometry(ceil, geom_name=f"ceiling_{r.id}", node_name=f"ceiling_{r.name.replace(' ', '_')}")
    if len(scene.geometry) == 0:
        # nothing was reconstructed: trimesh refuses to export an empty scene, and the
        # sheet that says NOT RECONSTRUCTIBLE must still come out with its GLB/OBJ
        marker = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
        marker.metadata["name"] = "empty"
        scene.add_geometry(marker, node_name="empty", geom_name="empty")
    return scene


def scene_stats(scene: trimesh.Scene) -> dict[str, float]:
    verts = sum(len(g.vertices) for g in scene.geometry.values())
    faces = sum(len(g.faces) for g in scene.geometry.values())
    return {"geometries": len(scene.geometry), "vertices": verts, "faces": faces}
