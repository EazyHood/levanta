"""End to end on a real flat, in CI: three rooms, and nobody silently loses them.

Two planner regressions in a row lived for days because the only real scenes were run by
hand: round 4's outline snapping shrank the TUM room by 2 m² and its walls by 2 m, and the
example in the repository stopped matching the code. This is the gate that would have said
so the same day.

The cloud is the Replica `apartment_0` walk with exact depth and exact poses, thinned to
40 046 points, which changes nothing in the plan: 16 walls and 61.5 m² at full density, 16
and 61.6 m² here.  Exact is not complete: floor points reach only 36 % of the flat's floor
because a camera at 1.5 m sees furniture, so this gate is the planner without network error,
not the planner with full information.  `apartment_0` also has a second storey 2.85 m up,
which the walk glimpses and the truth here does not include.

**It is not in the repository**: it derives from Replica's mesh, whose licence is for
research, and this repository is MIT. Whoever has the dataset generates it once with

    python bench/replica.py <replica>/apartment_0 out/replica_apt0 --res 1280x720 --save-depth
    python bench/ideal_input.py <replica>/apartment_0 out/replica_apt0
    python -c "from levanta.scene import PointCloud; PointCloud.load_ply('out/replica_apt0/ideal/plan_cloud.ply').voxel_downsampled(0.08).save_ply('tests/data/replica_apt0_cloud.ply')"

and these tests start running. Without it they skip, and the seven-scene bench
(`bench/planner_bench.py`) is what guards the planner.

Thresholds, deliberately wide enough that only a real change moves them, and every one of
them measured before being written down (truth: 51.8 m² of floor, three rooms, two doorways):

- three rooms, not one fused or four split;
- total area between 45 and 78 m² (today 61.6, the truth 51.8);
- at least twelve walls, and the longest at least 9 m (the party wall of the flat);
- the plan carries no room bigger than the whole floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.scene import PointCloud

CLOUD = Path(__file__).parent / "data" / "replica_apt0_cloud.ply"
TRUTH_FLOOR_M2 = 51.8

pytestmark = pytest.mark.skipif(not CLOUD.exists(), reason="Replica cloud not generated (research licence: not redistributed); see the module docstring")


@pytest.fixture(scope="module")
def plan():
    return extract_floor_plan(PointCloud.load_ply(CLOUD), PlanOptions()).plan


def test_the_flat_has_three_rooms(plan):
    assert len(plan.rooms) == 3, [round(r.shapely.area, 1) for r in plan.rooms]


def test_the_area_is_in_the_right_range(plan):
    total = sum(r.shapely.area for r in plan.rooms)
    assert 45.0 <= total <= 78.0, total
    assert all(r.shapely.area < TRUTH_FLOOR_M2 for r in plan.rooms), [round(r.shapely.area, 1) for r in plan.rooms]


def test_the_walls_are_there_and_the_long_one_survives(plan):
    assert len(plan.walls) >= 12, len(plan.walls)
    longest = max(w.length for w in plan.walls)
    assert longest >= 9.0, longest


def test_the_planner_reports_how_the_rooms_were_found(plan):
    """`debug.rooms` is what told us the closed-room stage finds two pockets in a
    three-room flat; a change that silences it hides the next diagnosis."""
    stats = plan.meta.get("debug", {}).get("rooms", {})
    assert {"pockets", "closed", "stage2", "fallback"} <= set(stats)
    assert stats["pockets"] >= 1
