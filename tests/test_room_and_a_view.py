"""A scene with something outside it, because a closed box cannot show the failure.

Every other synthetic apartment is sealed, and that is why the automated suite passed with
two planner changes the seven-scene bench measured at up to twice the area error: with
nothing beyond a wall, a sight line has nothing to reach, so the interior cannot leak out of
the building.

`a_room_and_a_view` gives one room to walk and a larger space behind a 1.6 m doorway that
nobody enters.  Its surfaces are attributed to the cameras in the walked room, which is the
geometry a real flat has and a box does not.

What it shows today: the walked room comes out exactly right, and levanta claims a second
room of 39 m² out of floor **nobody ever stood on**.  Both stages that build rooms are
involved and only one of them checks: the seen-floor fallback requires a room to contain a
camera, and the closed-pocket stage, which is what fires here, does not.
"""

from __future__ import annotations

import pytest

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.synthetic import sample_apartment, scenes

WALKED_M2 = 16.0


@pytest.fixture(scope="module")
def result():
    apt = scenes()["a_room_and_a_view"]()
    return extract_floor_plan(sample_apartment(apt, seed=7, camera_rooms=(0,)), PlanOptions())


def test_the_room_that_was_walked_comes_out_right(result):
    walked = min(result.plan.rooms, key=lambda r: abs(r.area - WALKED_M2))
    assert abs(walked.area - WALKED_M2) <= 1.6, [round(r.area, 1) for r in result.plan.rooms]


def test_the_scene_has_something_beyond_the_wall(result):
    """The point of the scene: without a second space the rest of this file is vacuous."""
    assert len(result.plan.rooms) >= 2, [round(r.area, 1) for r in result.plan.rooms]
    assert max(r.area for r in result.plan.rooms) > WALKED_M2 * 1.5


@pytest.mark.xfail(strict=True, reason="the closed-pocket stage claims a 39 m2 room out of floor nobody walked on; the fallback stage checks for a camera and it does not")
def test_no_room_is_claimed_from_floor_nobody_walked_on(result):
    cams = result.cloud.camera_centers[:, :2]
    from shapely import contains_xy

    for r in result.plan.rooms:
        assert contains_xy(r.shapely.buffer(0.3), cams[:, 0], cams[:, 1]).any(), f"{r.name} at {r.area:.1f} m2 holds no camera"
