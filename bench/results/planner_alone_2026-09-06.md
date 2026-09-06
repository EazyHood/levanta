# The planner alone, and a regression the benchmark caught

Everything here is measured without the network and without a GPU: the rendered walk of
Replica `apartment_0` carries the exact depth of every pixel and the exact pose of every
frame, so the planner can be fed a flawless cloud and judged on its own
(`bench/ideal_input.py`). The camera fit against the truth is exact to 1e-7 m and the
scale to 1.0000, which is the proof that the input really is flawless.

## 1. With a perfect cloud, the planner finds 29 % of the wall it can see

| | |
|---|---|
| real wall footprint (mesh, 0.3–1.8 m band) | 14.6 m² |
| of it, present in the cloud | 12.3 m² (84 %) |
| **of that, turned into walls** | **29 %** |
| precision of what it drew | 71 % |
| rooms | 2 of 3 (a third run gives 3, all open) |
| doorways | 1 of 2 |
| total area | +42 % (one room +283 %, another −47 %) |

**Half of what the apartment benchmark blamed on the network is the planner.** Even with
no drift at all, this input does not produce a three-room plan.

## 2. Where the wall is lost — four candidates, three ruled out

| candidate | measured | verdict |
|---|---|---|
| height coverage too strict | wall points have a median of 11 bands; 91 % pass the 5.2-band threshold | not it |
| Manhattan frame wrong | 73 % of wall normals within 6° of an axis, peaks at 0° and 89° | not it |
| outline snapping reach | identical plan at 1.0, 1.5, 2.0 and 2.5 m | not it |
| depth-edge filter eating the floor | 54 788 → 56 275 points from `edge_rel` 0.06 to 1.0 | not it |
| **`tidy_walls`** | **wall recall 48 % → 36 %, precision 75 % → 65 %** | **this one** |

`tidy_walls` keeps the stretches of wall that border a room and sets the rest aside. On a
flat whose rooms come out fused and misplaced, three real partitions (2.07, 1.29 and
2.43 m) border *no* room and are dropped — and dropping them makes the rooms worse. It is
a circle: rooms need walls, and the wall cleanup needs rooms.

Keeping long walls regardless was measured, not guessed: it brings the corridor seen
through the doorway back into the TUM plan (3 walls → 5). Length and distance do not
separate the two cases — the partition lost on the flat sits 0.98 m from a room, the
corridor debris in TUM sits 0.47 m — so no threshold here is honest. The fix is rooms
that do not depend on the walls already being clean, which is a redesign, not a constant.

What did land: a partition that starts at a room's outline and runs inwards is no longer
mistaken for furniture (`tests/test_tidy_keeps_partitions.py`).

## 3. A regression the published example was hiding

`examples/tum_fr1_room/` in the repository shows three walls of 5.80, 4.07 and 4.93 m and
a 24.5 m² room. Running `levanta tum` on the same sequence today gives **four walls of
3.68, 3.68, 0.45 and 4.83 m and a 22.2 m² room**: the room shrank, so `tidy_walls` trims
the walls harder, and a 0.45 m scrap appears.

It is not from today's change — `git stash` and the same run at commit `8407b7b` gives
the same four walls. It entered between round 3, when the example was generated, and
round 5, and nothing caught it because the TUM was never re-run after round 4. The
published example no longer matches what the code produces.
