# Round 5: what the numbers asked for next, measured

Same five ARKitScenes scenes; the "after" of round 4 (`639158d`) is the baseline here.
Every threshold below was written before its experiment ran.

## 1. The ceiling as a scale anchor — it loses

`bench/ceiling_scale.py`. Scale = 2.50 m / ceiling height the network measured, against the
network alone (1.0) and the door (0.80 m / width found). Threshold: beats the network alone
on 4 of 5 to become automatic calibration.

| scene | real ceiling (LiDAR) | ceiling the network measured | scale error, network alone | ceiling at 2.50 m | ceiling at the real height | door at 0.80 m |
|---|---|---|---|---|---|---|
| 41069021 | 2.35 m | 2.79 m | 3 % | 13 % | 18 % | — |
| 42897526 | 2.43 m | 2.55 m | 0 % | 2 % | 4 % | — |
| 45260905 | 3.25 m | 3.20 m | 24 % | 41 % | 23 % | — |
| 47331964 | 2.72 m | 2.45 m | 12 % | 14 % | 24 % | — |
| 47430051 (flagged) | 2.34 m | 2.09 m | 296 % | 373 % | 343 % | — |

Wins: **0 of 5** (1 of 5 with the ARKit focal). Two reasons, both measured: real
ceilings in these five homes run 2.34–3.25 m (one is 3.25), and the network's own ceiling
measurement is off by up to 20 % (2.79 m where there are 2.35). Even typing the true
height loses on 4 of 5. Where a door was found (with K, two scenes) its width was off by
29–38 %: a door seen sideways or half-open is not a ruler either. Nothing changes in the
product; the stamp stays until the user measures something well.

## 2. Straightening a chunk — the surface has nothing to say

`bench/refine_chunks.py`: every chunk fused into a TSDF (Open3D, 3 cm) from the network's
own depths, every view registered to the fused surface with point-to-plane ICP, three
rounds. Thresholds: per-chunk RMS against ARKit from 0.12–0.56 to ≤ 0.25 m on 4 of 5
(median over chunks), spread of per-chunk scales below 1.3×.

| scene | chunks | per-chunk RMS, median before → after | scale spread before → after | whole walk RMS before → after |
|---|---|---|---|---|
| 41069021 | 9 | 0.28 → 0.31 m | 2.04× → 1.88× | 0.47 → 0.50 m |
| 42897526 | 3 | 0.35 → 0.36 m | 1.10× → 1.11× | 0.51 → 0.53 m |
| 45260905 | 4 | 0.34 → 0.36 m | 2.31× → 2.37× | 0.59 → 0.64 m |
| 47331964 | 7 | 0.31 → 0.31 m | 4.23× → 4.16× | 0.84 → 0.85 m |
| 47430051 | 3 | 0.50 → 0.50 m | 2.39× → 2.39× | 0.89 → 0.89 m |

**0 of 5 on both thresholds, and the numbers do not move.** The network's depth maps and
its poses are consistent with each other inside a chunk: the fused surface is exactly
where the poses say it is, so ICP has nothing to correct. The bend is in the geometry the
network predicts, not in how its views are placed. Refining poses against the network's
own depth cannot see it; only an outside reference (a measured door, a second sensor) or
a different network can.

The other lever named in round 4 — views composed by overlap rather than by time — was
measured on the apartment below, where the drift matters most (`bench/overlap_sweep.py`,
with the exact focal length, threshold written before: camera RMS from 1.04 m to
<= 0.50 m and at least 2 of 3 rooms):

| views : shared | scale | camera RMS | rooms found | walls | total area error |
|---|---|---|---|---|---|
| 24 : 4 (baseline) | 1.06 | 1.04 m | 2 of 3 | 8 | −38 % |
| 16 : 8 | 0.85 | 1.05 m | 2 of 3 | 5 | −47 % |
| 12 : 6 | 1.16 | 1.01 m | 1 of 3 | 3 | −23 % |

**Not met, and the RMS does not move**: 1.01–1.05 m whatever the composition. Halving the
views per chunk costs walls (8 → 5 → 3) and swings the scale (0.85 to 1.16) without buying
accuracy. Both levers named in round 4 are now measured and both are dead ends; what is
left is the geometry the network predicts for a set of views, which no amount of
re-arranging those views repairs.

## 3. An apartment: Replica

ARKitScenes has no apartment (one video is one room). Replica's meshes are real scans of
flats with per-vertex colour (`bench/replica.py`: floor and rooms from the mesh, a walk
generated on the floor raster, rendered off-screen with Open3D at 720p, `levanta video`
on the result). Two things learned before any number: Replica's `mesh.ply` are *quad*
meshes, which Open3D's reader refuses (a numpy reader splits them); and `apartment_1`,
the first scene fetched, is an open-plan 57 m² flat with no doorway under 1.2 m — one
room by any erosion. The multi-room flat used here is **`apartment_0`: 51.8 m² of floor,
three rooms (territories 18.1, 17.1, 16.6 m²) joined by two doorways**. The walk is 116
steps of 0.30 m, camera at 1.5 m, a full turn in every room, rendered at 1280x720 and
written at 1 fps: 1.9 minutes of "video".

The first run exposed a bug of my own before it measured anything about the planner: the
round-3 speed-up (score one frame in three) assumes a window of about 30 frames, and this
render is *already* at 1 fps, so two frames of every three were never candidates — the
network saw 31 views of the flat instead of 94. The skip is now capped at the window size
(`tests/test_frame_sampling_window.py`). Both runs are in the table.

| | scale | camera RMS | rooms found | walls | total area error |
|---|---|---|---|---|---|
| no K, 31 views (the bug) | 1.14 | 0.96 m | 1 of 3 | 2 | −78 % |
| **no K, 94 views** | **1.07** | **1.08 m** | **1 of 3** | **5** | **−49 %** |
| with K, 31 views (the bug) | 1.15 | 0.90 m | 1 of 3 | 6 | −43 % |
| **with K, 94 views** | **1.06** | **1.04 m** | **2 of 3** | **8** | **−38 %** |

**The verdict the round asked for: levanta does not yet deliver its promise on an
apartment.** Three rooms come out as one or two, no doorway is found where the truth has
two, and the one room that matches a real one is 94 % too big — two rooms fused. Scale is
the good news: 1.06–1.07 without any calibration, the best of any real input so far. The
camera track ends **1.0 m** from the truth over a 35 m walk in five chunks, and the debug
cloud shows why the rooms fuse: the walls arrive doubled and bent, each chunk's copy
offset from the next.

This is the same limit as round 4, now measured where it matters: the drift inside a
chunk, chained five times across a flat, is what stops a three-room plan from existing.
