"""A capture can be too thin for the flat, and nothing used to say so.

The one flat nobody chose got 55 frames for a 56.8 m2 floor and its plan came out at 13.3.
The bench scenes run at 2.4 to 6.5 frames per square metre of the cloud's own footprint and
that one sat at 0.78, three times below the thinnest real one, so the input was an order of
magnitude short of anything levanta had been measured on and the user was never told.

The denominator matters and is the trap: using the plan's own area would make a sparse
capture look dense, because the plan that under-measures reports a flattering density.
"""

from __future__ import annotations

from levanta.plan.types import MIN_FRAMES_PER_M2, FloorPlan, Room


def _plan(views=None, footprint=None) -> FloorPlan:
    p = FloorPlan(walls=[], openings=[], ceiling_height=2.5,
                  rooms=[Room(id=0, name="Room 1", polygon=[(0, 0), (4, 0), (4, 4), (0, 4)])])
    if views is not None:
        p.meta["views"] = views
    if footprint is not None:
        p.meta["cloud_footprint_m2"] = footprint
    return p


def keys(p: FloorPlan) -> set[str]:
    return {c["key"] for c in p.quality("en")}


def test_a_thin_capture_is_reported():
    assert "too_few_frames" in keys(_plan(views=55, footprint=70.3))  # the flat nobody chose


def test_a_normal_capture_stays_quiet():
    assert "too_few_frames" not in keys(_plan(views=128, footprint=53.8))  # 47331964, the thinnest real one
    assert "too_few_frames" not in keys(_plan(views=184, footprint=28.2))  # 41069021


def test_the_line_sits_below_every_real_scene():
    assert MIN_FRAMES_PER_M2 < 128 / 53.8, "would misfire on the thinnest bench scene"
    assert MIN_FRAMES_PER_M2 > 55 / 70.3, "would not catch the flat that motivated it"


def test_nothing_is_claimed_without_both_numbers():
    assert "too_few_frames" not in keys(_plan())
    assert "too_few_frames" not in keys(_plan(views=55))
    assert "too_few_frames" not in keys(_plan(footprint=70.3))


def test_a_sparse_sample_of_a_dense_video_is_our_fault_not_theirs():
    """A 30 fps clip sampled at 1 fps has 96 % of its frames unused.  Telling that person to
    walk more slowly blames them for a default of ours, and a warning that blames the person
    filming is very hard to withdraw later."""
    p = _plan(views=55, footprint=70.3)
    p.meta.update({"video_fps": 29.97, "video_frames": 6604, "sample_fps": 1.0})
    k = keys(p)
    assert "sampled_too_sparsely" in k
    assert "too_few_frames" not in k
    text = next(c["text"] for c in p.quality("en") if c["key"] == "sampled_too_sparsely")
    assert "6604" in text and "--fps" in text


def test_when_the_file_had_no_more_to_give_the_advice_is_about_filming():
    """The rendered walk really is 1 fps with 80 frames in it: there is nothing to recover,
    so the advice is how long to walk, in minutes, which is the only unit anyone can act on."""
    p = _plan(views=55, footprint=70.3)
    p.meta.update({"video_fps": 1.0, "video_frames": 80, "sample_fps": 1.0})
    k = keys(p)
    assert "too_few_frames" in k
    assert "sampled_too_sparsely" not in k
    text = next(c["text"] for c in p.quality("en") if c["key"] == "too_few_frames")
    assert "minutes of walking" in text


def test_a_dense_enough_capture_says_nothing_either_way():
    p = _plan(views=128, footprint=53.8)
    p.meta.update({"video_fps": 30.0, "video_frames": 3000, "sample_fps": 1.0})
    assert not ({"too_few_frames", "sampled_too_sparsely"} & keys(p))
