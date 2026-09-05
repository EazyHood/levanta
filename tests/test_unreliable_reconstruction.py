"""A reconstruction that fell apart says so instead of drawing a room.

The 4.2 m² bathroom of ARKitScenes 47430051 (mirror, tiles) came back with 56 k points
for 57 views, one wall, chunk scales 0.25-0.58 of the median and scale 0.26 against the
truth; the sheet drew a 7 m² room over it.  The signals are in the reconstruction:
chunks whose scale against the previous one falls outside [0.5, 2.0], or a median mask
coverage per view below 10 % (the collapsed bathroom kept 5 %, a sound one 13 %).

Thresholds written before the fix ran: with such meta the plan carries a check with key
"unreliable", the stamp reads "NO RECONSTRUIBLE" (es) / "NOT RECONSTRUCTIBLE" (en) and
names mirror or glass; a healthy reconstruction (scales within 10 %, coverage 40 %) has
neither.
"""

from __future__ import annotations

from levanta.io.draw import render_svg
from levanta.io.plan2d import floor_plan_drawing
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.synthetic import sample_apartment, three_rooms


def _plan(**meta):
    cloud = sample_apartment(three_rooms(), seed=7)
    cloud.meta.update({"source": "mapanything", **meta})
    return extract_floor_plan(cloud, PlanOptions()).plan.label_openings()


def test_collapsed_chunks_are_flagged_and_stamped():
    plan = _plan(chunk_scales=[1.02, 0.31, 0.28], mask_fraction=0.12)
    assert plan.unreliable
    keys = {q["key"] for q in plan.quality("es")}
    assert "unreliable" in keys
    text = next(q["text"] for q in plan.quality("es") if q["key"] == "unreliable")
    assert "espejo" in text and "2 de 4" in text  # three scales = four chunks
    svg = render_svg(floor_plan_drawing(plan, lang="es"))
    assert "NO RECONSTRUIBLE" in svg and "espejo" in svg
    assert "NOT RECONSTRUCTIBLE" in render_svg(floor_plan_drawing(plan, lang="en"))


def test_low_coverage_alone_is_enough():
    plan = _plan(chunk_scales=[1.0, 1.05], mask_fraction=0.08)
    assert plan.unreliable and any(q["key"] == "unreliable" for q in plan.quality("en"))


def test_a_wide_spread_of_chunk_scales_is_flagged_even_inside_the_band():
    """ARKitScenes 42897599, 301 s, 15 chunks: scales 0.53-1.73, no room at all."""
    plan = _plan(chunk_scales=[1.07, 0.72, 1.59, 1.06, 0.75, 1.09, 1.10, 0.64, 0.53, 1.46, 0.99, 1.73, 0.56, 1.0], mask_fraction=0.6)
    assert plan.unreliable is not None and plan.unreliable[0] >= 4
    plan = _plan(chunk_scales=[0.99, 1.04, 1.02, 0.99, 1.04, 1.38], mask_fraction=0.76)  # 47331964, a sound one
    assert plan.unreliable is None


def test_healthy_reconstruction_is_not_flagged():
    plan = _plan(chunk_scales=[1.0, 1.06, 0.95], mask_fraction=0.4)
    assert not plan.unreliable and not any(q["key"] == "unreliable" for q in plan.quality("en"))
    assert "NO RECONSTRUIBLE" not in render_svg(floor_plan_drawing(plan, lang="es"))
