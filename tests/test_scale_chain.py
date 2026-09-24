"""A walk whose scale was lost link by link says so, even when no single link looks wrong.

The fps sweep's 4 fps run on ARKitScenes 41069021 (17.5 m², 36 chunks) drew the plan 2.2
times too big with a shape 83 % short, and its total area read a harmless −15 %.  Nothing
flagged it: every chunk-to-chunk scale sat inside [0.5, 2] and their spread was 1.79, under
the 2.5 that `FloorPlan.unreliable` allows.  What does show it is the product of the links:
the chunks of that one walk ended up drawn 52 times apart in size.

The factors below are the real ones from bench/results/fps_sweep_2026-09-24.md, rounded to
three decimals, so this runs where the sweep's files are not.  Thresholds written before the
check was: the broken walk flagged and stamped in both languages; the two longest walks that
did not break (18 and 17 chunks, 4.6 and 3.7 times apart) left alone.
"""

from __future__ import annotations

from levanta.io.draw import render_svg
from levanta.io.plan2d import floor_plan_drawing
from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.plan.types import CHAIN_RANGE_MAX
from levanta.synthetic import sample_apartment, three_rooms

BROKE_AT_4_FPS = [1.03, 0.967, 0.948, 0.834, 0.889, 0.813, 0.925, 0.841, 0.749, 0.765, 0.793, 0.869, 1.147, 0.983, 0.693, 0.673, 0.933, 0.753,
                  1.191, 0.887, 0.936, 1.095, 1.163, 0.988, 1.03, 0.985, 0.969, 1.052, 1.104, 0.665, 0.817, 0.79, 0.787, 0.789, 0.812]
HELD_AT_2_FPS = [1.069, 1.037, 1.115, 0.969, 0.88, 0.989, 1.08, 0.835, 0.879, 0.815, 0.899, 0.892, 0.926, 0.98, 0.697, 0.917, 0.851]
HELD_AT_8_FPS_SMALL_ROOM = [1.066, 1.051, 0.981, 1.079, 0.95, 0.798, 0.941, 0.916, 0.852, 0.867, 0.813, 0.957, 0.95, 0.882, 0.909, 0.951]


def _plan(**meta):
    cloud = sample_apartment(three_rooms(), seed=7)
    cloud.meta.update({"source": "mapanything", "mask_fraction": 0.4, **meta})
    return extract_floor_plan(cloud, PlanOptions()).plan.label_openings()


def test_the_walk_nothing_flagged_is_flagged_now():
    plan = _plan(chunk_scales=BROKE_AT_4_FPS)
    assert plan.unreliable is None, "the per-link check still passes it; that is the point"
    spread, links = plan.scale_chain_broken
    assert 45 < spread < 60 and links == 35
    text = next(q["text"] for q in plan.quality("en") if q["key"] == "scale_chain")
    assert "35 times" in text and "52 times apart" in text


def test_it_is_stamped_with_its_own_cause_in_both_languages():
    plan = _plan(chunk_scales=BROKE_AT_4_FPS)
    es = render_svg(floor_plan_drawing(plan, lang="es"))
    en = render_svg(floor_plan_drawing(plan, lang="en"))
    assert "NO RECONSTRUIBLE" in es and "escala perdida" in es and "espejo" not in es
    assert "NOT RECONSTRUCTIBLE" in en and "scale lost along the walk" in en


def test_the_longest_walks_that_held_are_left_alone():
    for scales in (HELD_AT_2_FPS, HELD_AT_8_FPS_SMALL_ROOM):
        plan = _plan(chunk_scales=scales)
        assert plan.scale_chain_broken is None
        assert "scale_chain" not in {q["key"] for q in plan.quality("en")}


def test_the_line_sits_in_the_gap_it_claims():
    """Highest sound walk 4.64, lowest broken 52: the constant has to stay between them."""
    assert 4.64 < CHAIN_RANGE_MAX < 52


def test_a_chain_that_wanders_and_comes_back_is_still_caught():
    """The size gap is between any two parts of the walk, not first against last."""
    there_and_back = [0.6] * 5 + [1 / 0.6] * 5  # ends where it began, 13 times apart midway
    plan = _plan(chunk_scales=there_and_back)
    assert plan.scale_chain_broken is not None


def test_the_chunk_count_levanta_check_prints_is_the_one_the_network_gets():
    """Every frame count of the fps sweep against the chunks its reconstruction reported."""
    from levanta.plan.types import CHUNKS_MEASURED, chunk_count

    sweep = {184: 9, 46: 3, 361: 18, 92: 5, 715: 36, 183: 9, 1332: 67, 341: 17}
    assert {n: chunk_count(n) for n in sweep} == sweep
    assert chunk_count(24) == 1 and chunk_count(25) == 2 and chunk_count(0) == 0
    assert chunk_count(184) == CHUNKS_MEASURED  # the longest chain measured at the default


def test_no_chain_no_check():
    assert _plan().scale_chain_broken is None
    assert _plan(chunk_scales=[]).scale_chain_broken is None
