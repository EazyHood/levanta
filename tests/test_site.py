from __future__ import annotations

import json
import os

import numpy as np
import pytest

from levanta.site.lod1 import export_site, lod1_mesh
from levanta.site.projection import LocalProjection
from levanta.site.sources import Building, fetch_buildings, parse_overpass, sort_by_relevance

OVERPASS_FIXTURE = {
    "elements": [
        {
            "type": "way",
            "id": 1,
            "tags": {"building": "house", "building:levels": "2", "name": "Casa"},
            "geometry": [
                {"lat": 4.6000, "lon": -74.0800},
                {"lat": 4.6000, "lon": -74.0799},
                {"lat": 4.6001, "lon": -74.0799},
                {"lat": 4.6001, "lon": -74.0800},
                {"lat": 4.6000, "lon": -74.0800},
            ],
        },
        {
            "type": "way",
            "id": 2,
            "tags": {"building": "yes", "height": "12.5 m"},
            "geometry": [
                {"lat": 4.6010, "lon": -74.0800},
                {"lat": 4.6010, "lon": -74.0799},
                {"lat": 4.6011, "lon": -74.0799},
                {"lat": 4.6010, "lon": -74.0800},
            ],
        },
        {"type": "node", "id": 3, "lat": 4.6, "lon": -74.08},
    ]
}


def test_projection_roundtrip_and_scale():
    proj = LocalProjection(4.6, -74.08)
    xy = proj.to_local(-74.0799, 4.6001)
    assert 10.5 < xy[0] < 11.5 and 10.8 < xy[1] < 11.3  # ~11 m per 1e-4 deg near the equator
    back = proj.to_wgs84(xy[0], xy[1])
    assert np.allclose(back, [-74.0799, 4.6001], atol=1e-9)


def test_parse_overpass_and_height_logic():
    bs = parse_overpass(OVERPASS_FIXTURE)
    assert [b.id for b in bs] == ["way/1", "way/2"]
    assert bs[0].levels == 2 and bs[0].height() == (6.0, "levels")
    assert bs[1].height_m == 12.5 and bs[1].height() == (12.5, "measured")
    assert Building("x", "osm", [(0, 0), (1, 0), (1, 1)]).height() == (3.0, "default")


def test_sort_by_relevance_puts_containing_building_first():
    bs = parse_overpass(OVERPASS_FIXTURE)
    ordered = sort_by_relevance(bs[::-1], 4.60005, -74.07995)
    assert ordered[0].id == "way/1"


def test_lod1_mesh_volume_and_export(tmp_path):
    bs = parse_overpass(OVERPASS_FIXTURE)
    proj = LocalProjection(4.60005, -74.07995)
    poly = bs[0].polygon_local(proj)
    mesh = lod1_mesh(poly, 6.0)
    assert mesh.is_watertight and abs(mesh.volume - poly.area * 6.0) < 1e-6
    paths = export_site(bs, 4.60005, -74.07995, tmp_path, stem="s", only_target=False)
    for p in paths.values():
        assert p.exists() and p.stat().st_size > 100
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["buildings"][0]["height_source"] == "levels" and len(data["buildings"]) == 2


@pytest.mark.skipif(not os.environ.get("LEVANTA_NETWORK_TESTS"), reason="set LEVANTA_NETWORK_TESTS=1 to hit Overpass")
def test_overpass_live():
    bs = fetch_buildings(4.5981, -74.0760, radius_m=80, source="osm")  # Bogota, Plaza de Bolivar area
    assert bs and bs[0].footprint
