"""A plan whose scale comes from the network alone says so on the sheet, not only in a note.

The real walkthrough came out 1.2-1.4x off in scale and only note 4 said it.  Now a
diagonal "PRELIMINARY - scale not calibrated" stamp crosses the plan (and the elevations)
and the scale cell of the title block carries the same words, on every page, whenever
``plan.scale_uncalibrated`` is true; both vanish once the plan is calibrated.

Thresholds written before the fix ran: stamp present (class "stamp", text in the chosen
language) on the plan and the elevations and in every PDF page; absent after
``scaled()`` / ``calibrated_to_door_width()``; absent on RGB-D plans, whose scale is real.
"""

from __future__ import annotations

import re
import zlib

from levanta.io.draw import render_svg
from levanta.io.elevations import elevations_drawing
from levanta.io.export import export_pdf
from levanta.io.plan2d import floor_plan_drawing
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.synthetic import sample_apartment, three_rooms


def _plan(source="mapanything"):
    plan = extract_floor_plan(sample_apartment(three_rooms(), seed=7), PlanOptions()).plan
    plan.meta["source"] = source
    return plan.label_openings()


def _pdf_texts(path):
    data = path.read_bytes()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except zlib.error:
            pass
    return out


def test_uncalibrated_video_plan_is_stamped_everywhere(tmp_path):
    plan = _plan()
    assert plan.scale_uncalibrated
    svg = render_svg(floor_plan_drawing(plan, lang="es"))
    assert 'class="stamp"' in svg and "PRELIMINAR" in svg and "sin calibrar" in svg
    assert "PRELIMINARY" in render_svg(floor_plan_drawing(plan, lang="en"))
    esvg = render_svg(elevations_drawing(plan, lang="es"))
    assert 'class="stamp"' in esvg
    pages = _pdf_texts(export_pdf(plan, tmp_path / "s.pdf", paper="A3", lang="es"))
    assert len(pages) == 2 and all("PRELIMINAR" in p for p in pages)


def test_calibrated_or_measured_plans_are_not_stamped():
    plan = _plan()
    calibrated, _f = plan.calibrated_to_door_width(0.90)
    assert not calibrated.scale_uncalibrated
    assert 'class="stamp"' not in render_svg(floor_plan_drawing(calibrated, lang="es"))
    assert not plan.scaled(1.1).scale_uncalibrated
    rgbd = _plan(source="rgbd")
    assert not rgbd.scale_uncalibrated
    assert 'class="stamp"' not in render_svg(floor_plan_drawing(rgbd, lang="es"))
