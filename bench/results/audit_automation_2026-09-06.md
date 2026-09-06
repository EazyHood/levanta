# What is being done by hand that is supposed to be automatic

Four candidates, checked by **effect** rather than exit code, and for each the question:
if this had been broken for a month, what would anyone have seen?

## 1. CI — healthy, and provably a gate

| | |
|---|---|
| runs | 34 on `push` to `main`, plus pull requests |
| **red** | **5 of 34** |
| coverage | 48 commits, 34 pushes; 4 jobs each (Ubuntu and Windows × 3.10 and 3.12) |

A gate that has never been red is a checkbox. This one has failed five times and each
failure stopped something real: a missing `.ply` fixture and a `ruff` warning I had read
only the tail of. **Broken for a month I would have seen it**, because I also run the suite
locally every round and the two would have disagreed.

## 2. The bench — nothing automated, and the automated substitute is blind

| | |
|---|---|
| scheduled tasks mentioning levanta | **0** |
| CI steps that run a bench | **0** (`ruff check src tests bench` lints it, never runs it) |
| bench runs launched by anything other than me | **0** |

So the seven-scene bench is entirely manual. That is defensible — its data cannot be
redistributed — and the answer was supposed to be `tests/test_pipeline_synthetic.py`, which
does run on every push and does assert real quantities: room count, per-room IoU, door
positions and widths, wall thickness, ceiling height, gravity and Manhattan residual.

**So I tested the watcher on the mechanism, and it does not watch.** With
`rooms_clipped_by_low_walls` forced on, a change the bench measured at 17 % → 39 % mean area
error, the synthetic suite passes. With `free_blocked_by_walls` forced on, 17 % → 21 % and
six points of wall recall, it passes too.

The reason is structural, and it is not that the code path lies idle: the synthetic
apartment produces 3 low runs, so the path fires. The scene is a closed box. **There is
nothing outside it to shoot a ray at**, so the interior cannot leak past a missing wall,
which is the entire failure mode of rounds 14 to 18. Cutting one wall's points above 1.0 m
moves the area by −17 % and −2 %, never up.

**Broken for a month, nobody would have seen anything.** A synthetic scene that can carry
this regression needs geometry the camera never enters, so that a ray past a wall edge lands
on something. That is the missing test, and it is now named.

## 3. Publishing to PyPI — never succeeded, for the documented reason

Three runs of `publish.yml`, **three failures**, all at the upload step, none at build. The
cause is the one the workflow header predicts: Trusted Publishing has no pending publisher,
so PyPI rejects the OIDC claim. The claims the failed run presented are exactly what the
setup needs, which is worth having verified rather than assumed:

```
owner:       EazyHood
repository:  levanta
workflow:    publish.yml
environment: pypi
```

**This is the honest state: the automatic path exists, has run, and has never once put a
package anywhere.** It cannot be proven to work until the publisher exists. The tag `v0.3.0`
is already pushed, so the run can simply be re-run afterwards.

## 4. Long-job output — a real exposure, already half mitigated

Storage Sense deleted a background task's output file today **while it was being written**.
The tool reported the missing file, so I saw it. A polling loop would not have: it greps the
file for a marker, finds nothing, and waits until it gives up. **An empty result and a
destroyed result look identical to it.**

Half of this is already handled by habit rather than design: bench runs write their tables
to `out/*.txt` inside the project, which Storage Sense does not touch. The task output in
`%TEMP%` is what remains exposed.

## 5. What the audit fixed on the spot

The apartment gate's fixture was derived from `plan_cloud.ply`, **the planner's own output**,
which is the same defect round 11 found in the bench. Regenerated from `fused_cloud.ply`, the
cloud that actually goes in, one of its assertions failed immediately:

> a room of **55.8 m² on a flat of 51.8 m²** — the plan claims a single room larger than the
> whole building.

That assertion had been passing for ten rounds because a second pass separates the rooms. It
is now its own test, marked `xfail(strict=True)`, so it stays visible while it is broken and
fails the day the fusion is fixed, forcing the mark off.

---

# Follow-up: what else does the output claim that is impossible?

## 6. Six invariants, measured on five plans

Checked without ground truth, on the Replica flat, both synthetic apartments and the three
published examples:

| the claim | holds today |
|---|---|
| no room larger than the building | **cannot be checked from the output alone** |
| the rooms' areas sum to no more than the area they cover | **fails on the U2 apartment**: 30.99 against 30.55 |
| no zero or negative area, length or thickness | holds everywhere |
| every opening sits on a wall that exists | holds everywhere |
| every *enclosed* room has a door or passage on one of its walls | holds everywhere; the first version of this check raised a false alarm |
| perimeter and area do not contradict each other | holds everywhere |

The first one is worth being exact about. Without truth, "the building" is the union of the
plan's own rooms and walls, and a room is part of that by construction, so the check is
vacuous. It only became a defect against the flat's real 51.8 m², which is why the gate
found it and this family cannot.

The other five are now in `FloorPlan.quality()` and print on the sheet like any other check,
with seven tests including the tightest legal case, a circle, which must not fire.

**And then one of the two was the checker, not the plan.** Announcing a defect on a published
example deserves the same suspicion as any instrument that accuses something published, so
both were re-measured.

**The room with no door: false alarm, and the checker is fixed.** Room 5 of the U2 apartment
has **4 % of its outline on a wall and 21 % of it touching the room next door**. It is the
open end of a corridor: you walk in, and there is no door because there is no door in
reality. The check now fires only on a room walled all the way round (≥90 % of its outline
backed by wall) with no opening in any of those walls, and both directions are tested,
because a check that cannot be quiet is not a check.

**The overlap: real, and the threshold is not in a hole.** The distribution over the five
plans settles it:

| plan | excess of the sum over the area covered |
|---|---|
| Replica apt_0 | 0.0000 m² |
| synthetic three_rooms | 0.0000 m² |
| synthetic two_rooms | 0.0000 m² |
| TUM office | 0.0000 m² |
| **U2 apartment** | **0.4443 m² (1.46 %)** |

Not a gradient of floating-point noise with a threshold sitting in the middle of it: four
plans are exactly zero and one is half a square metre, four orders of magnitude apart. The
0.05 m² threshold could be anywhere in that gap. The overlapping pair is Room 2 and Room 5,
the same corridor and its open end, so the two alarms had one cause and only one of them was
a defect.

## 7. The xfail drawer, capped, and the cap tested

`tests/conftest.py` prints the known defects at the end of every run and fails the suite
above `MAX_XFAIL = 1`. Both directions were measured rather than assumed, and the first
version was wrong: it printed the warning and the suite still exited 0, because
`pytest_terminal_summary` runs too late to change the exit code. With `pytest_sessionfinish`
it exits 1 with two xfails and 0 with one.

There was a measurement error of my own in the middle: reading `$?` after a pipe gives the
exit status of `tail`, not of pytest. The first "it does not bite" reading was that.

## 8. Where every test input comes from

| source | tests | is it upstream of what is tested? |
|---|---|---|
| `sample_apartment(...)`, the synthetic generator | 19 | yes: truth by construction |
| `tests/data/replica_apt0_cloud.ply` | 4 | **was not**, fixed today: derived from `plan_cloud.ply`, the planner's own output |
| `tests/data/video_real_plan.json` | 2 | yes, though it is a levanta plan: the unit under test is the *sheet renderer*, and a plan is its input |
| written and read back within the test | 2 | yes |

So the pattern appears twice and only one is a defect, which gives the rule that separates
them: **a test's input must come from upstream of the thing being tested.** For the
apartment gate the unit is the planner, so the input has to be the cloud that goes in, never
the plan that comes out. For the label and note tests the unit is the renderer, so a plan is
upstream and using a real one is right.

---

# Follow-up 2: the threshold, and a scene with something outside it

## 9. The overlap threshold was reserving margin for noise that does not exist

Asked for the distribution at full precision instead of four decimals, over ten plans:

| | excess of the sum over the area covered |
|---|---|
| eight plans (both synthetic apartments at five seeds, the TUM office, two examples) | **exactly 0.0** |
| Replica apt_0 | 1.4e-14 m² — one float epsilon on a 62 m² sum |
| U2 apartment | **0.4443 m²** |

There is no noise floor to clear. I had written that the 0.05 m² threshold "was placed by
luck but is well placed"; **it is not**, and the measurement says so: it would let a real
overlap of four hand-sized centimetres through with nothing measured to justify it. It is
now **1e-6 m²**, thirteen orders of magnitude above the noise, with a test that 4 cm² fires
and a test that two rooms sharing an edge stay quiet. A margin is justified by a case, and
the day a case lands in between it raises this with the case in front of it.

## 10. `a_room_and_a_view`: the scene the suite was missing

Every synthetic apartment was a sealed box, so a sight line had nothing to reach past a wall
and the interior could not leak out of the building — which is why the suite passed with two
changes the bench measures at up to twice the area error.

The new scene gives one room to walk and a larger space behind a 1.6 m doorway that nobody
enters; its surfaces are attributed to the cameras in the walked room, which is the geometry
a real flat has. `sample_apartment` gained `camera_rooms` for it.

What it shows:

| | rooms | areas | total |
|---|---|---|---|
| default | 2 | **39.0**, 16.0 | 55.0 m² |
| `rooms_clipped_by_low_walls` | 2 | 37.5, 15.1 | 52.6 m² |
| `free_blocked_by_walls` | 2 | 39.0, 16.0 | 55.0 m² |

The walked room comes out at 16.0 m² against a truth of 16.0. **And levanta claims a second
room of 39 m² out of floor nobody ever stood on.** The scene also moves under a planner
change where the closed scenes moved not at all, which is the sensitivity it was built for,
though only by 5 %.

And it named a concrete cause: both rooms come from the **closed-pocket** stage
(`closed: 2`), and that stage has no check that a room was entered. The seen-floor fallback
does: it requires a room to contain a camera. One of the two stages checks and the other
does not.

That is now `tests/test_room_and_a_view.py`, with the defect as an `xfail(strict=True)` and
`MAX_XFAIL` raised to 2 with both cases written next to it.
