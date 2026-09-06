"""Vector floor-plan model: walls, openings, rooms.

Everything lives in the *plan frame*: metres, z = 0 on the finished floor, +z up, and
(when Manhattan mode is on) walls parallel to the x or y axis.  ``FloorPlan.transform``
maps the original point-cloud frame into the plan frame so results can be related back
to the capture.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString, Polygon


@dataclass
class Wall:
    """Straight wall described by its centreline ``a -> b`` and its ``thickness``."""

    id: int
    a: tuple[float, float]
    b: tuple[float, float]
    thickness: float
    height: float
    sides_seen: int = 1  # 1: only one face was observed (thickness is a default); 2: both faces measured
    line_id: int = -1  # walls on the same infinite line share this id
    exterior: bool = False  # nothing was ever seen behind it

    @property
    def length(self) -> float:
        return float(np.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1]))

    @property
    def direction(self) -> np.ndarray:
        d = np.array(self.b, dtype=float) - np.array(self.a, dtype=float)
        n = np.linalg.norm(d)
        return d / n if n > 0 else np.array([1.0, 0.0])

    @property
    def normal(self) -> np.ndarray:
        d = self.direction
        return np.array([-d[1], d[0]])

    def point_at(self, t: float) -> np.ndarray:
        return np.array(self.a, dtype=float) + self.direction * t

    def polygon(self) -> Polygon:
        """Footprint rectangle of the wall body."""
        return LineString([self.a, self.b]).buffer(self.thickness / 2.0, cap_style="flat", join_style="mitre")


@dataclass
class Opening:
    """Door, window or open passage cut into ``wall_id``.

    ``t0``/``t1`` are distances along the wall centreline from ``Wall.a``; ``z0``/``z1``
    the bottom/top heights above the floor.
    """

    id: int
    wall_id: int
    kind: str  # "door" | "window" | "passage"
    t0: float
    t1: float
    z0: float
    z1: float
    rooms: tuple[int, ...] = ()  # ids of the rooms this opening connects
    tag: str = ""  # P1, V2, A1 ... assigned by FloorPlan.label_openings()
    height_measured: bool = False  # z1 measured on the lintel (True) or a default (False)

    @property
    def width(self) -> float:
        return self.t1 - self.t0


@dataclass
class Room:
    id: int
    name: str
    polygon: list[tuple[float, float]]  # exterior ring, counter-clockwise, metres
    holes: list[list[tuple[float, float]]] = field(default_factory=list)
    closed: bool = True  # False: not fully enclosed by detected walls; outline follows the seen floor
    floor_seen: float | None = None
    """Fraction of the room's area where floor was actually observed, not inferred.

    A camera at eye height sees furniture, not floor: on a rendered walk with exact depth
    and exact poses, floor points reached 36 % of a flat's real floor while the path passed
    within 2 m of 80-94 % of every room.  The rest of the outline is inference, so the
    number belongs on the sheet next to the room, where a reader can weigh it."""

    @property
    def shapely(self) -> Polygon:
        return Polygon(self.polygon, self.holes)

    @property
    def area(self) -> float:
        return float(self.shapely.area)

    @property
    def perimeter(self) -> float:
        return float(self.shapely.length)

    @property
    def centroid(self) -> tuple[float, float]:
        c = self.shapely.representative_point()
        return (float(c.x), float(c.y))


@dataclass
class FloorPlan:
    walls: list[Wall]
    rooms: list[Room]
    openings: list[Opening]
    ceiling_height: float
    ceiling_measured: bool = True
    transform: list[list[float]] = field(default_factory=lambda: np.eye(4).tolist())  # cloud -> plan
    units: str = "m"
    meta: dict[str, Any] = field(default_factory=dict)
    extra_walls: list[Wall] = field(default_factory=list)  # seen, but bounding no room (not drawn)
    north_deg: float | None = None  # where true north points: degrees clockwise from the plan's +y
    project: dict[str, str] = field(default_factory=dict)  # name, author, sheet, revision, level ...

    # -- derived -----------------------------------------------------------------------

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) over wall bodies and rooms."""
        xs: list[float] = []
        ys: list[float] = []
        for w in self.walls:
            b = w.polygon().bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for r in self.rooms:
            b = r.shapely.bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def total_area(self) -> float:
        """Floor area covered by the rooms, counting shared floor once.

        Summing the rooms is wrong when two of them overlap, and they can: on the U2
        apartment example, rooms 2 and 5 share 0.44 m2, so the title block said 30.99 m2
        while the area schedule right beside it said 30.55.  The schedule was the honest
        one, and this is now the same number.
        """
        if not self.rooms:
            return 0.0
        from shapely.ops import unary_union

        return float(unary_union([r.shapely for r in self.rooms]).area)

    def wall_by_id(self, wall_id: int) -> Wall:
        for w in self.walls:
            if w.id == wall_id:
                return w
        raise KeyError(wall_id)

    def openings_of(self, wall_id: int) -> list[Opening]:
        return sorted((o for o in self.openings if o.wall_id == wall_id), key=lambda o: o.t0)

    # -- annotation ----------------------------------------------------------------------

    def label_openings(self) -> FloorPlan:
        """Give every opening a tag: P1, P2 ... doors, V1 ... windows, A1 ... passages,
        numbered along the walls in wall order."""
        counters = {"door": 0, "window": 0, "passage": 0}
        prefix = {"door": "P", "window": "V", "passage": "A"}
        for w in self.walls:
            for o in self.openings_of(w.id):
                counters[o.kind] = counters.get(o.kind, 0) + 1
                o.tag = f"{prefix.get(o.kind, 'O')}{counters[o.kind]}"
        return self

    def area_summary(self) -> dict[str, float]:
        """Useful area (rooms), wall footprint area, and gross area (rooms + walls)."""
        from shapely.ops import unary_union

        rooms = unary_union([r.shapely for r in self.rooms]) if self.rooms else None
        walls = unary_union([w.polygon() for w in self.walls]) if self.walls else None
        useful = float(rooms.area) if rooms is not None else 0.0
        wall_area = float(walls.area) if walls is not None else 0.0
        parts = [g for g in (rooms, walls) if g is not None]
        gross = float(unary_union(parts).area) if parts else 0.0
        return {
            "useful_m2": useful,
            "walls_m2": wall_area,
            "gross_m2": gross,
            "wall_length_m": float(sum(w.length for w in self.walls)),
        }

    def quality(self, lang: str = "en") -> list[dict[str, str]]:
        """Checks a drafter would run before trusting the plan: ``[{level, text}]``.
        ``level`` is ``ok`` | ``info`` | ``warn``."""
        from levanta.i18n import t

        out: list[dict[str, str]] = []
        open_rooms = [r.name for r in self.rooms if not r.closed]
        if open_rooms:
            out.append({"key": "open_room", "level": "warn", "text": t(lang, "qa_open_room").format(rooms=", ".join(open_rooms))})
        if not self.rooms:
            out.append({"key": "no_rooms", "level": "warn", "text": t(lang, "qa_no_rooms")})
        overlap = float(sum(r.area for r in self.rooms)) - self.total_area
        if overlap > 0.05:
            out.append({"key": "rooms_overlap", "level": "warn", "text": t(lang, "qa_rooms_overlap").format(m2=f"{overlap:.2f}")})
        thin = [r for r in self.rooms if r.floor_seen is not None and r.floor_seen < 0.5]
        if thin:
            avg = round(100 * sum(r.floor_seen for r in thin) / len(thin))
            out.append({"key": "floor_seen", "level": "warn", "text": t(lang, "qa_floor_seen").format(rooms=", ".join(r.name for r in thin), pct=avg)})
        one_sided = sum(1 for w in self.walls if w.sides_seen == 1)
        if self.walls:
            out.append({"key": "thickness", "level": "info" if one_sided else "ok", "text": t(lang, "qa_thickness_assumed").format(n=one_sided, m=len(self.walls))})
        if not self.ceiling_measured:
            out.append({"key": "ceiling", "level": "warn", "text": t(lang, "qa_ceiling_default")})
        bad = self.unreliable
        if bad is not None:
            out.append({"key": "unreliable", "level": "warn", "text": t(lang, "qa_unreliable").format(bad=bad[0], n=bad[1], cover=round(100 * bad[2]))})
        if self.scale_uncalibrated:
            out.append({"key": "scale", "level": "warn", "text": t(lang, "qa_scale_uncalibrated")})
        unmeasured = [o.tag or o.kind for o in self.openings if o.kind == "door" and not o.height_measured]
        if unmeasured:
            out.append({"key": "door_height", "level": "info", "text": t(lang, "qa_height_assumed").format(tags=", ".join(unmeasured))})
        if self.rooms and not any(o.kind == "window" for o in self.openings):
            out.append({"key": "no_windows", "level": "info", "text": t(lang, "qa_no_windows")})
        if all(x["level"] == "ok" for x in out):
            out.append({"key": "ok", "level": "ok", "text": t(lang, "qa_ok")})
        return out

    # -- editing -----------------------------------------------------------------------

    def rename_rooms(self, names: list[str] | dict[int, str] | dict[str, str]) -> FloorPlan:
        """Rename rooms in place.  A list applies in room order (largest first, as
        numbered); a dict maps room id or current name to the new name."""
        if isinstance(names, dict):
            for r in self.rooms:
                if r.id in names:
                    r.name = str(names[r.id])  # type: ignore[index]
                elif r.name in names:
                    r.name = str(names[r.name])  # type: ignore[index]
        else:
            for r, n in zip(self.rooms, names, strict=False):
                if n:
                    r.name = str(n)
        return self

    @property
    def unreliable(self) -> tuple[int, int, float] | None:
        """(chunks whose scale broke, chunks, median mask coverage) when the reconstruction
        cannot be trusted: a chunk had to be scaled by less than 0.5 or more than 2 to meet
        the previous one, or the network kept less than 10 % of a typical frame.  Mirrors,
        glass and tiles do this (ARKitScenes 47430051: scales 0.25-0.58, one wall).  None
        for a healthy reconstruction or for plans that did not come from video."""
        scales = self.meta.get("chunk_scales")
        cover = self.meta.get("mask_fraction")
        if scales is None and cover is None:
            return None
        scales = [float(s) for s in (scales or [])]
        bad = sum(1 for s in scales if not (0.5 <= s <= 2.0))
        n = len(scales) + 1
        cov = float(cover) if cover is not None else 1.0
        # a walk whose chunks needed scales spread over more than 2.5x fell apart even if
        # no single one crossed the line (ARKitScenes 42897599: 0.53-1.73 over 15 chunks,
        # 0 rooms); sound walks stayed within 1.4x
        spread = (max(scales) / min(scales)) if scales and min(scales) > 0 else 1.0
        if bad == 0 and spread <= 2.5 and cov >= 0.10:  # measured: a collapsed bathroom kept 5 %, a sound one 13 %
            return None
        if bad == 0 and spread > 2.5:
            bad = sum(1 for s in scales if s < 0.7 or s > 1.4)
        return bad, n, cov

    @property
    def scale_uncalibrated(self) -> bool:
        """True when the metric scale comes from the network alone (a video with no known
        focal length and no door calibration): the sheet is stamped PRELIMINARY."""
        return str(self.meta.get("source", "")) == "mapanything" and "scale_factor" not in self.meta

    def scaled(self, factor: float) -> FloorPlan:
        """A copy with every length multiplied by ``factor`` (areas by ``factor**2``).

        Use it to fix the global scale of a video reconstruction once one real length is
        known; see :meth:`calibrated_to_door_width`.
        """
        d = self.to_dict()
        for w in d["walls"]:
            w["a"] = [v * factor for v in w["a"]]
            w["b"] = [v * factor for v in w["b"]]
            w["thickness"] *= factor
            w["height"] *= factor
        for r in d["rooms"]:
            r["polygon"] = [[v * factor for v in p] for p in r["polygon"]]
            r["holes"] = [[[v * factor for v in p] for p in h] for h in r["holes"]]
        for o in d["openings"]:
            for k in ("t0", "t1", "z0", "z1"):
                o[k] *= factor
        for w in d.get("extra_walls", []):
            w["a"] = [v * factor for v in w["a"]]
            w["b"] = [v * factor for v in w["b"]]
            w["thickness"] *= factor
            w["height"] *= factor
        d["ceiling_height"] *= factor
        T = np.array(d["transform"], dtype=float)
        T[:3, :] *= factor
        d["transform"] = T.tolist()
        d.setdefault("meta", {})["scale_factor"] = float(d.get("meta", {}).get("scale_factor", 1.0) * factor)
        return FloorPlan.from_dict(d)

    def calibrated_to_door_width(self, true_width: float = 0.90) -> tuple[FloorPlan, float]:
        """Rescale so that the median detected door width equals ``true_width``.

        Returns ``(plan, factor)``; the factor is 1.0 when no door was detected.
        """
        widths = [o.width for o in self.openings if o.kind == "door"]
        if not widths:
            return self, 1.0
        factor = float(true_width / float(np.median(widths)))
        return self.scaled(factor), factor

    def summary(self) -> str:
        lines = [
            f"walls: {len(self.walls)}  rooms: {len(self.rooms)}  openings: {len(self.openings)}",
            f"ceiling: {self.ceiling_height:.2f} m ({'measured' if self.ceiling_measured else 'default'})",
            f"floor area: {self.total_area:.2f} m2",
        ]
        for r in self.rooms:
            lines.append(f"  {r.name}: {r.area:.2f} m2, perimeter {r.perimeter:.2f} m")
        for o in self.openings:
            lines.append(f"  {o.kind} #{o.id} on wall {o.wall_id}: width {o.width:.2f} m, z {o.z0:.2f}-{o.z1:.2f}")
        return "\n".join(lines)

    # -- (de)serialisation -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["version"] = 1
        d["rooms"] = [
            {**asdict(r), "area_m2": round(r.area, 4), "perimeter_m": round(r.perimeter, 4)} for r in self.rooms
        ]
        d["walls"] = [{**asdict(w), "length_m": round(w.length, 4)} for w in self.walls]
        d["openings"] = [{**asdict(o), "width_m": round(o.width, 4)} for o in self.openings]
        d["extra_walls"] = [{**asdict(w), "length_m": round(w.length, 4)} for w in self.extra_walls]
        return d

    def to_json(self, path: str | Path | None = None, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, default=_json_default)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FloorPlan:
        walls = [Wall(**{k: v for k, v in w.items() if k in Wall.__dataclass_fields__}) for w in d["walls"]]
        rooms = [Room(**{k: v for k, v in r.items() if k in Room.__dataclass_fields__}) for r in d["rooms"]]
        openings = [
            Opening(**{k: (tuple(v) if k == "rooms" else v) for k, v in o.items() if k in Opening.__dataclass_fields__})
            for o in d["openings"]
        ]
        extra = [Wall(**{k: v for k, v in w.items() if k in Wall.__dataclass_fields__}) for w in d.get("extra_walls", [])]
        for w in walls + extra:
            w.a, w.b = tuple(w.a), tuple(w.b)
        for r in rooms:
            r.polygon = [tuple(p) for p in r.polygon]
            r.holes = [[tuple(p) for p in h] for h in r.holes]
        return cls(
            walls=walls,
            rooms=rooms,
            openings=openings,
            ceiling_height=float(d["ceiling_height"]),
            ceiling_measured=bool(d.get("ceiling_measured", True)),
            transform=d.get("transform", np.eye(4).tolist()),
            units=d.get("units", "m"),
            meta=d.get("meta", {}),
            extra_walls=extra,
            north_deg=d.get("north_deg"),
            project=dict(d.get("project", {}) or {}),
        )

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> FloorPlan:
        p = Path(path_or_text)
        text = p.read_text(encoding="utf-8") if p.exists() else str(path_or_text)
        return cls.from_dict(json.loads(text))


def _json_default(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o)}")
