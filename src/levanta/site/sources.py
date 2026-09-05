"""Building footprints and heights from public sources.

* :class:`OverpassSource` — OpenStreetMap through the public Overpass API.  No extras,
  no key.  Coverage and ``height`` / ``building:levels`` tags vary by city.
  License: ODbL 1.0, attribution "© OpenStreetMap contributors".
* :class:`OvertureSource` — Overture Maps buildings (OSM + Microsoft + Google Open
  Buildings, with ``height`` where a source measured it).  Needs ``pip install
  levanta[overture]`` (pyarrow).  License: ODbL 1.0 / CDLA-Permissive-2.0 per source.

Both return :class:`Building` objects in WGS84; heights are metres above ground.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely.geometry import Point, Polygon

from levanta.site.projection import LocalProjection

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "levanta/0.1 (+https://github.com/EazyHood/levanta)"


@dataclass
class Building:
    id: str
    source: str
    footprint: list[tuple[float, float]]  # (lon, lat) exterior ring
    holes: list[list[tuple[float, float]]] = field(default_factory=list)
    height_m: float | None = None
    levels: int | None = None
    roof_shape: str | None = None
    name: str | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    license: str = ""
    attribution: str = ""

    def polygon_wgs84(self) -> Polygon:
        return Polygon(self.footprint, self.holes)

    def polygon_local(self, proj: LocalProjection) -> Polygon:
        ext = proj.to_local(*np.asarray(self.footprint).T)
        holes = [proj.to_local(*np.asarray(h).T) for h in self.holes]
        return Polygon(ext, holes)

    def height(self, level_height: float = 3.0, default: float = 3.0) -> tuple[float, str]:
        """(height in metres, how it was obtained: 'measured' | 'levels' | 'default')."""
        if self.height_m is not None and self.height_m > 0:
            return float(self.height_m), "measured"
        if self.levels is not None and self.levels > 0:
            return float(self.levels) * level_height, "levels"
        return float(default), "default"

    def describe(self, proj: LocalProjection | None = None) -> dict[str, Any]:
        h, how = self.height()
        d: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "name": self.name,
            "height_m": round(h, 2),
            "height_source": how,
            "levels": self.levels,
            "roof_shape": self.roof_shape,
            "license": self.license,
            "attribution": self.attribution,
            "vertices": len(self.footprint),
        }
        if proj is not None:
            p = self.polygon_local(proj)
            d["footprint_area_m2"] = round(p.area, 2)
            d["perimeter_m"] = round(p.length, 2)
        return d


# ----------------------------------------------------------------------------------------


class OverpassSource:
    name = "osm"

    def __init__(self, url: str = OVERPASS_URL, timeout: float = 40.0) -> None:
        self.url = url
        self.timeout = timeout

    def query(self, lat: float, lon: float, radius_m: float) -> list[Building]:
        import requests

        q = (
            f"[out:json][timeout:{int(self.timeout)}];"
            f"(way[building](around:{radius_m:.0f},{lat:.7f},{lon:.7f});"
            f"relation[building](around:{radius_m:.0f},{lat:.7f},{lon:.7f}););"
            "out body geom;"
        )
        r = requests.post(self.url, data={"data": q}, headers={"User-Agent": USER_AGENT}, timeout=self.timeout + 10)
        r.raise_for_status()
        return parse_overpass(r.json())


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        s = str(v).strip().lower().replace(",", ".")
        for suffix in (" m", "m", " meters", " metres"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
        return float(s)
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    f = _num(v)
    return round(f) if f is not None else None


def parse_overpass(data: dict[str, Any]) -> list[Building]:
    """Buildings from an Overpass JSON answer with ``out geom`` geometry."""
    out: list[Building] = []
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        if "building" not in tags:
            continue
        rings: list[list[tuple[float, float]]] = []
        inner: list[list[tuple[float, float]]] = []
        if el["type"] == "way" and el.get("geometry"):
            rings.append([(g["lon"], g["lat"]) for g in el["geometry"]])
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("type") != "way" or not m.get("geometry"):
                    continue
                ring = [(g["lon"], g["lat"]) for g in m["geometry"]]
                (inner if m.get("role") == "inner" else rings).append(ring)
        rings = [r for r in rings if len(r) >= 4 and r[0] == r[-1]]
        if not rings:
            continue
        # keep the largest outer ring as the footprint
        outer = max(rings, key=lambda r: abs(Polygon(r).area))
        holes = [h for h in inner if len(h) >= 4 and Polygon(outer).contains(Polygon(h))]
        h = _num(tags.get("height")) or _num(tags.get("building:height"))
        out.append(
            Building(
                id=f"{el['type']}/{el['id']}",
                source="osm",
                footprint=outer[:-1],
                holes=[hh[:-1] for hh in holes],
                height_m=h,
                levels=_int(tags.get("building:levels")),
                roof_shape=tags.get("roof:shape"),
                name=tags.get("name"),
                tags=tags,
                license="ODbL 1.0",
                attribution="© OpenStreetMap contributors",
            )
        )
    return out


class OvertureSource:
    name = "overture"

    def query(self, lat: float, lon: float, radius_m: float) -> list[Building]:
        try:
            from overturemaps import core
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install 'levanta[overture]' for the Overture source") from e
        import shapely

        dlat = radius_m / 111_320.0
        dlon = radius_m / (111_320.0 * max(0.05, np.cos(np.deg2rad(lat))))
        bbox = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
        table = core.record_batch_reader("building", bbox).read_all()
        rows = table.to_pylist()
        out: list[Building] = []
        for row in rows:
            geom = shapely.from_wkb(row["geometry"])
            if geom.geom_type == "MultiPolygon":
                geom = max(geom.geoms, key=lambda g: g.area)
            if geom.geom_type != "Polygon":
                continue
            names = row.get("names") or {}
            sources = row.get("sources") or []
            ds = ", ".join(sorted({(s.get("dataset") or "?") for s in sources if isinstance(s, dict)}))
            out.append(
                Building(
                    id=str(row.get("id")),
                    source="overture",
                    footprint=[(float(x), float(y)) for x, y in geom.exterior.coords[:-1]],
                    holes=[[(float(x), float(y)) for x, y in r.coords[:-1]] for r in geom.interiors],
                    height_m=_num(row.get("height")),
                    levels=_int(row.get("num_floors")),
                    roof_shape=row.get("roof_shape"),
                    name=(names.get("primary") if isinstance(names, dict) else None),
                    tags={"datasets": ds, "class": row.get("class"), "subtype": row.get("subtype")},
                    license="ODbL 1.0 / CDLA-Permissive-2.0 (per source dataset)",
                    attribution=f"Overture Maps Foundation ({ds})",
                )
            )
        return out


SOURCES = {"osm": OverpassSource, "overture": OvertureSource}


def fetch_buildings(lat: float, lon: float, radius_m: float = 60.0, source: str = "osm") -> list[Building]:
    """Buildings around a point, the one containing the point first, then by distance."""
    if source not in SOURCES:
        raise KeyError(f"unknown source {source!r}; choose from {sorted(SOURCES)}")
    buildings = SOURCES[source]().query(lat, lon, radius_m)
    return sort_by_relevance(buildings, lat, lon)


def sort_by_relevance(buildings: list[Building], lat: float, lon: float) -> list[Building]:
    proj = LocalProjection(lat, lon)
    p = Point(0.0, 0.0)

    def key(b: Building) -> tuple[int, float]:
        poly = b.polygon_local(proj)
        return (0 if poly.contains(p) else 1, poly.distance(p))

    return sorted(buildings, key=key)


def load_overpass_json(path: str) -> list[Building]:
    with open(path, encoding="utf-8") as f:
        return parse_overpass(json.load(f))
