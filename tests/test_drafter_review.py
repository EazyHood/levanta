"""The drafter's red pen on the 0.3.0 sheet.  Thresholds written before the fixes ran.

1. every interior partition is positioned by a dimension (axis chains) and every opening
   is positioned along its wall by a chain, interior walls included;
2. every PDF page carries a title block with its own sheet number and scale;
3. every wall is tagged on the plan so schedule, elevations and drawing can be joined;
4. "assumed" is printed on the sheet when a wall thickness is a default;
5. the plan fills at least 60 % of the usable page, or the sheet says why not;
6. ``python -m levanta`` runs.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib

import numpy as np

from levanta.io.draw import render_svg
from levanta.io.export import export_pdf, fit_print_scale
from levanta.io.plan2d import (
    axis_chains,
    dimension_chains,
    floor_plan_drawing,
    interior_chains,
    reference_axes,
)
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.synthetic import sample_apartment, three_rooms

FILL_MIN = 0.60


def _demo_plan():
    res = extract_floor_plan(sample_apartment(three_rooms(), seed=7), PlanOptions())
    plan = res.plan
    plan.project.update({"name": "Casa demo", "author": "Jhona", "sheet": "A-01", "revision": "B", "level": "+0.00"})
    plan.north_deg = 20.0
    return plan.label_openings()


def _pdf_page_texts(path) -> list[str]:
    data = path.read_bytes()
    texts = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            texts.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except zlib.error:
            continue
    return texts


def test_every_partition_and_opening_is_positioned():
    plan = _demo_plan()
    letters, numbers = reference_axes(plan)
    ax = axis_chains(plan)
    hx = next(c for c in ax if c["orientation"] == "h")
    vy = next(c for c in ax if c["orientation"] == "v")
    assert np.allclose(hx["positions"], [x for _, x in letters])
    assert np.allclose(sorted(vy["positions"]), sorted(y for _, y in numbers))
    # every interior partition lies on an axis
    for w in plan.walls:
        d = w.direction
        if abs(d[0]) < 0.05:
            assert min(abs((w.a[0] + w.b[0]) / 2 - x) for x in hx["positions"]) < 0.05
        elif abs(d[1]) < 0.05:
            assert min(abs((w.a[1] + w.b[1]) / 2 - y) for y in vy["positions"]) < 0.05
    # every opening has a chain on its wall with both jambs as stations
    chains = dimension_chains(plan) + interior_chains(plan)
    for o in plan.openings:
        ok = any(c["wall"].id == o.wall_id and any(abs(s - o.t0) < 1e-6 for s in c["stations"]) and any(abs(s - o.t1) < 1e-6 for s in c["stations"]) for c in chains)
        assert ok, f"opening {o.tag} on wall {o.wall_id} has no dimension chain"
    inner = [w for w in plan.walls if not w.exterior and plan.openings_of(w.id)]
    assert inner and all(any(c["wall"].id == w.id for c in interior_chains(plan)) for w in inner)


def test_every_pdf_page_has_a_title_block_with_its_sheet_number(tmp_path):
    plan = _demo_plan()
    p = export_pdf(plan, tmp_path / "s.pdf", paper="A3", lang="es")
    pages = _pdf_page_texts(p)
    assert len(pages) == 2
    assert "A-01" in pages[0] and "1:" in pages[0] and "Casa demo" in pages[0]
    assert "A-02" in pages[1] and "1:" in pages[1] and "Casa demo" in pages[1]


def test_every_wall_is_tagged_on_the_plan_and_in_the_elevations():
    plan = _demo_plan()
    svg = render_svg(floor_plan_drawing(plan, lang="es"))
    root = ET.fromstring(svg)
    tags = {el.text for el in root.iter() if (el.get("class") or "") == "wall-tag"}
    assert tags >= {f"M{w.id + 1}" for w in plan.walls}
    from levanta.io.elevations import elevations_drawing

    esvg = render_svg(elevations_drawing(plan, lang="es"))
    for w in plan.walls:
        assert f"Muro {w.id + 1}" in esvg
    assert re.search(r"Muro \d+ · [^·]+ · (N|S|E|O|NE|NO|SE|SO)\b", esvg)  # orientation from the north arrow


def test_assumed_thickness_is_visible_on_the_sheet():
    plan = _demo_plan()
    assert any(w.sides_seen == 1 for w in plan.walls)
    svg = render_svg(floor_plan_drawing(plan, lang="es"))
    assert "supuesto" in svg and 'class="wall-assumed"' in svg and "Notas" in svg
    svg_en = render_svg(floor_plan_drawing(plan, lang="en"))
    assert "assumed" in svg_en and "Notes" in svg_en


def test_sheet_is_filled_or_the_reason_is_printed():
    plan = _demo_plan()
    d, _pw, _ph, _ox, _oy, _s, info = fit_print_scale(plan, "A3", "landscape", lang="es")
    assert info["fill"] >= FILL_MIN or info["next_scale_fits"] is False
    if info["fill"] < FILL_MIN:
        assert f"1:{info['next_scale']}" in render_svg(d)  # the justification is on the sheet


def test_python_dash_m_levanta_runs():
    out = subprocess.run([sys.executable, "-m", "levanta", "version"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip().count(".") == 2
