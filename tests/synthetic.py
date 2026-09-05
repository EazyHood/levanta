"""Synthetic apartments with exact ground truth, used as the planner's control experiments.

The generator samples the surfaces a hand-held scanner would see from inside each room
(wall faces, floor, ceiling, low furniture), with Gaussian noise and per-point camera
assignment.  Cameras also see *through doorways* into the neighbouring room (and
through exterior doors onto a patch of ground outside), exactly as a phone does, so
that the planner's line-of-sight test is exercised.  Everything is parametric so the
expected numbers are known *before* the pipeline runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon

from levanta.geometry import make_pose, rot_z, rotation_from_a_to_b, unit
from levanta.scene import PointCloud


@dataclass
class SRoom:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def polygon(self) -> Polygon:
        return Polygon([(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)])


@dataclass
class SOpening:
    """Opening in a wall plane.  ``axis='x'`` means the wall is the plane x = ``at``."""

    axis: str
    at: float
    t0: float
    t1: float
    z0: float = 0.0
    z1: float = 2.05
    kind: str = "door"


@dataclass
class Apartment:
    rooms: list[SRoom]
    openings: list[SOpening] = field(default_factory=list)
    height: float = 2.5
    wall_int: float = 0.12
    wall_ext: float = 0.25


def two_rooms() -> Apartment:
    """Two rooms side by side, one door between them, one exterior door, two windows."""
    a = SRoom("A", 0.0, 0.0, 4.0, 3.0)
    b = SRoom("B", 4.12, 0.0, 7.0, 3.0)
    return Apartment(
        rooms=[a, b],
        openings=[
            SOpening("x", 4.0, 1.0, 1.9),  # door A<->B in the shared wall (both faces)
            SOpening("y", 0.0, 0.6, 1.5),  # exterior door of A
            SOpening("y", 3.0, 1.2, 2.6, 0.9, 2.1, "window"),  # window in A
            SOpening("y", 3.0, 5.0, 6.2, 0.9, 2.1, "window"),  # window in B
        ],
    )


def three_rooms() -> Apartment:
    """Two rooms opening onto a corridor across the top; three doors."""
    a = SRoom("A", 0.0, 0.0, 4.0, 3.0)
    b = SRoom("B", 4.12, 0.0, 7.5, 3.0)
    c = SRoom("C", 0.0, 3.12, 7.5, 5.0)
    return Apartment(
        rooms=[a, b, c],
        openings=[
            SOpening("y", 3.0, 0.8, 1.7),  # A -> C
            SOpening("y", 3.0, 5.5, 6.4),  # B -> C
            SOpening("x", 4.0, 0.9, 1.8),  # A <-> B
            SOpening("x", 7.5, 3.6, 4.6, 0.9, 2.0, "window"),  # window C east
            SOpening("y", 0.0, 2.0, 3.2, 0.9, 2.0, "window"),  # window A south
        ],
    )


# ----------------------------------------------------------------------------------------


def _wall_faces(room: SRoom):
    """(axis, at, normal_into_room, t_range) for the four faces of a room."""
    return [
        ("x", room.x0, np.array([1.0, 0.0, 0.0]), (room.y0, room.y1)),
        ("x", room.x1, np.array([-1.0, 0.0, 0.0]), (room.y0, room.y1)),
        ("y", room.y0, np.array([0.0, 1.0, 0.0]), (room.x0, room.x1)),
        ("y", room.y1, np.array([0.0, -1.0, 0.0]), (room.x0, room.x1)),
    ]


def _holes_for(axis: str, at: float, apt: Apartment) -> list[SOpening]:
    """Openings that cut this face: same axis and within one wall thickness of the plane."""
    return [o for o in apt.openings if o.axis == axis and abs(o.at - at) <= apt.wall_ext + 1e-6]


def _rooms_at(o: SOpening, apt: Apartment) -> list[SRoom]:
    """Rooms whose boundary carries opening ``o`` (one for an exterior door, two for interior)."""
    out = []
    for r in apt.rooms:
        if o.axis == "x":
            on = abs(r.x0 - o.at) <= apt.wall_ext + 1e-6 or abs(r.x1 - o.at) <= apt.wall_ext + 1e-6
            span = r.y0 - 1e-6 <= o.t0 and o.t1 <= r.y1 + 1e-6
        else:
            on = abs(r.y0 - o.at) <= apt.wall_ext + 1e-6 or abs(r.y1 - o.at) <= apt.wall_ext + 1e-6
            span = r.x0 - 1e-6 <= o.t0 and o.t1 <= r.x1 + 1e-6
        if on and span:
            out.append(r)
    return out


def visible_through(cam: np.ndarray, pts: np.ndarray, o: SOpening) -> np.ndarray:
    """Which of ``pts`` the camera at ``cam`` sees through the rectangle of opening ``o``."""
    ax = 0 if o.axis == "x" else 1
    tx = 1 - ax
    denom = pts[:, ax] - cam[ax]
    ok = np.abs(denom) > 1e-9
    lam = np.where(ok, (o.at - cam[ax]) / np.where(ok, denom, 1.0), -1.0)
    inter_t = cam[tx] + lam * (pts[:, tx] - cam[tx])
    inter_z = cam[2] + lam * (pts[:, 2] - cam[2])
    return ok & (lam > 0) & (lam < 1) & (inter_t >= o.t0) & (inter_t <= o.t1) & (inter_z >= o.z0) & (inter_z <= o.z1)


def sample_apartment(
    apt: Apartment,
    density: float = 900.0,
    noise: float = 0.008,
    cameras_per_room: int = 3,
    furniture: int = 2,
    seed: int = 0,
    rigid: np.ndarray | None = None,
    through_doors: float = 0.5,
) -> PointCloud:
    """Point cloud with oriented normals, per-point camera and cameras (OpenCV c2w).

    ``density`` is points per square metre of surface; ``rigid`` an optional 4x4
    transform applied to everything (to test gravity/Manhattan recovery);
    ``through_doors`` the share of the points visible through a doorway that get
    attributed to a camera on the other side.
    """
    rng = np.random.default_rng(seed)
    xyz, nrm, view, room_of = [], [], [], []
    cams: list[np.ndarray] = []
    cams_of_room: dict[int, np.ndarray] = {}
    H = apt.height

    for ri, room in enumerate(apt.rooms):
        cam_ids = []
        for _ in range(cameras_per_room):
            cx = rng.uniform(room.x0 + 0.5, room.x1 - 0.5)
            cy = rng.uniform(room.y0 + 0.5, room.y1 - 0.5)
            yaw = rng.uniform(0, 2 * np.pi)
            f = np.array([np.cos(yaw), np.sin(yaw), 0.0])
            down = np.array([0.0, 0.0, -1.0])
            right = np.cross(down, f)
            R = np.stack([right, down, f], axis=1)
            cams.append(make_pose(R, [cx, cy, 1.4]))
            cam_ids.append(len(cams) - 1)
        cam_ids = np.array(cam_ids)
        cams_of_room[ri] = cam_ids

        def add(points: np.ndarray, normal: np.ndarray, ri: int = ri, cam_ids: np.ndarray = cam_ids) -> None:
            if len(points) == 0:
                return
            xyz.append(points + rng.normal(0, noise, points.shape))
            nrm.append(np.tile(normal, (len(points), 1)))
            view.append(rng.choice(cam_ids, size=len(points)))
            room_of.append(np.full(len(points), ri))

        # walls
        for axis, at, normal, (t0, t1) in _wall_faces(room):
            n = int(density * (t1 - t0) * H)
            t = rng.uniform(t0, t1, n)
            z = rng.uniform(0, H, n)
            keep = np.ones(n, bool)
            for o in _holes_for(axis, at, apt):
                keep &= ~((t >= o.t0) & (t <= o.t1) & (z >= o.z0) & (z <= o.z1))
            t, z = t[keep], z[keep]
            pts = np.stack([np.full_like(t, at), t, z], 1) if axis == "x" else np.stack([t, np.full_like(t, at), z], 1)
            add(pts, normal)
            # door/window reveals (short faces across the wall thickness)
            for o in _holes_for(axis, at, apt):
                th = apt.wall_int if len(_rooms_at(o, apt)) == 2 else apt.wall_ext
                depth_dir = -normal
                for tt, sgn in ((o.t0, 1.0), (o.t1, -1.0)):
                    m = int(density * th * (o.z1 - o.z0) * 0.5)
                    d = rng.uniform(0, th, m)
                    z = rng.uniform(o.z0, o.z1, m)
                    base = np.array([at, tt, 0.0]) if axis == "x" else np.array([tt, at, 0.0])
                    tang = np.array([0.0, 1.0, 0.0]) if axis == "x" else np.array([1.0, 0.0, 0.0])
                    pts = base + depth_dir * d[:, None] + np.array([0, 0, 1.0]) * z[:, None]
                    add(pts, tang * sgn)
        # floor and ceiling
        area = (room.x1 - room.x0) * (room.y1 - room.y0)
        n = int(density * area)
        fx = rng.uniform(room.x0, room.x1, n)
        fy = rng.uniform(room.y0, room.y1, n)
        add(np.stack([fx, fy, np.zeros(n)], 1), np.array([0.0, 0.0, 1.0]))
        n = int(density * area * 0.6)
        cx_ = rng.uniform(room.x0, room.x1, n)
        cy_ = rng.uniform(room.y0, room.y1, n)
        add(np.stack([cx_, cy_, np.full(n, H)], 1), np.array([0.0, 0.0, -1.0]))
        # low furniture: boxes on the floor, only faces that a room camera can see
        for _ in range(furniture):
            w, d, h = rng.uniform(0.5, 1.4), rng.uniform(0.4, 0.9), rng.uniform(0.4, 1.0)
            bx = rng.uniform(room.x0 + 0.3, max(room.x0 + 0.31, room.x1 - w - 0.3))
            by = rng.uniform(room.y0 + 0.3, max(room.y0 + 0.31, room.y1 - d - 0.3))
            faces = [
                (np.array([bx, by, h]), np.array([w, 0, 0]), np.array([0, d, 0]), np.array([0, 0, 1.0])),
                (np.array([bx, by, 0]), np.array([0, d, 0]), np.array([0, 0, h]), np.array([-1.0, 0, 0])),
                (np.array([bx + w, by, 0]), np.array([0, d, 0]), np.array([0, 0, h]), np.array([1.0, 0, 0])),
                (np.array([bx, by, 0]), np.array([w, 0, 0]), np.array([0, 0, h]), np.array([0, -1.0, 0])),
                (np.array([bx, by + d, 0]), np.array([w, 0, 0]), np.array([0, 0, h]), np.array([0, 1.0, 0])),
            ]
            for origin, u, v, normal in faces:
                m = int(density * np.linalg.norm(u) * np.linalg.norm(v))
                a = rng.uniform(0, 1, m)[:, None]
                b = rng.uniform(0, 1, m)[:, None]
                pts = origin + a * u + b * v
                cam = cams[cam_ids[0]][:3, 3]
                vis = (cam - pts) @ normal > 0
                add(pts[vis], normal)

    P = np.concatenate(xyz)
    N = unit(np.concatenate(nrm))
    V = np.concatenate(view)
    RO = np.concatenate(room_of)

    # Sight lines through doorways: a camera in room A also observes part of room B.
    extra_xyz, extra_nrm, extra_view = [], [], []
    for o in apt.openings:
        if o.kind != "door":
            continue
        rooms_here = _rooms_at(o, apt)
        if len(rooms_here) == 2:
            for src, dst in ((rooms_here[0], rooms_here[1]), (rooms_here[1], rooms_here[0])):
                si, di = apt.rooms.index(src), apt.rooms.index(dst)
                idx_dst = np.flatnonzero(RO == di)
                for cid in cams_of_room[si]:
                    vis = visible_through(cams[cid][:3, 3], P[idx_dst], o)
                    cand = idx_dst[vis]
                    take = cand[rng.uniform(0, 1, len(cand)) < through_doors]
                    V[take] = cid
        elif len(rooms_here) == 1:
            # exterior door: a 3 x 3 m patch of ground outside, seen only through the door
            room = rooms_here[0]
            ri = apt.rooms.index(room)
            if o.axis == "x":
                out_dir = -1.0 if abs(room.x0 - o.at) < abs(room.x1 - o.at) else 1.0
                gx = o.at + out_dir * rng.uniform(0.3, 3.3, 3000)
                gy = rng.uniform((o.t0 + o.t1) / 2 - 1.5, (o.t0 + o.t1) / 2 + 1.5, 3000)
            else:
                out_dir = -1.0 if abs(room.y0 - o.at) < abs(room.y1 - o.at) else 1.0
                gy = o.at + out_dir * rng.uniform(0.3, 3.3, 3000)
                gx = rng.uniform((o.t0 + o.t1) / 2 - 1.5, (o.t0 + o.t1) / 2 + 1.5, 3000)
            ground = np.stack([gx, gy, np.zeros(3000)], 1)
            for cid in cams_of_room[ri]:
                vis = visible_through(cams[cid][:3, 3], ground, o)
                g = ground[vis]
                extra_xyz.append(g + rng.normal(0, noise, g.shape))
                extra_nrm.append(np.tile([0.0, 0.0, 1.0], (len(g), 1)))
                extra_view.append(np.full(len(g), cid))
    if extra_xyz:
        P = np.concatenate([P, *extra_xyz])
        N = np.concatenate([N, *extra_nrm])
        V = np.concatenate([V, *extra_view])

    cloud = PointCloud(xyz=P, normals=N, view=V, cameras=np.stack(cams), meta={"source": "synthetic"})
    if rigid is not None:
        cloud = cloud.transformed(rigid)
    return cloud


def rigid_perturbation(tilt_deg: float, yaw_deg: float, offset=(3.0, -2.0, 0.7)) -> np.ndarray:
    """A tilt of the up axis, a yaw about it and a translation."""
    tilt_axis_up = unit(np.array([np.sin(np.deg2rad(tilt_deg)), 0.0, np.cos(np.deg2rad(tilt_deg))]))
    R = rotation_from_a_to_b(np.array([0.0, 0.0, 1.0]), tilt_axis_up) @ rot_z(np.deg2rad(yaw_deg))
    return make_pose(R, np.asarray(offset, dtype=float))


# ----------------------------------------------------------------------------------------
# ground-truth comparison
# ----------------------------------------------------------------------------------------


def match_rooms(gt: list[Polygon], pred: list[Polygon]) -> list[tuple[int, int, float]]:
    """Greedy IoU matching; returns (gt_index, pred_index, iou)."""
    pairs = []
    for i, g in enumerate(gt):
        for j, p in enumerate(pred):
            inter = g.intersection(p).area
            union = g.union(p).area
            pairs.append((inter / union if union > 0 else 0.0, i, j))
    pairs.sort(reverse=True)
    used_g, used_p, out = set(), set(), []
    for iou, i, j in pairs:
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        out.append((i, j, iou))
    return out


def opening_center(o: SOpening) -> np.ndarray:
    t = (o.t0 + o.t1) / 2
    return np.array([o.at, t]) if o.axis == "x" else np.array([t, o.at])
