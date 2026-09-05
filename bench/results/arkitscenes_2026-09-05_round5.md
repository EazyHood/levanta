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

The other lever — views composed by parallax rather than time (2 fps, 16 views per
chunk: more overlap, fewer views) — is measured below.

## 3. An apartment: Replica

ARKitScenes has no apartment (one video is one room). Replica's meshes are real scans of
flats with per-vertex colour (`bench/replica.py`: floor and rooms from the mesh, a walk
generated on the floor raster, rendered off-screen with Open3D at 720p, `levanta video`
on the result). Two things learned before any number: Replica's `mesh.ply` are *quad*
meshes, which Open3D's reader refuses (a numpy reader splits them); and `apartment_1`,
the first scene fetched, is an open-plan 57 m² flat with no doorway under 1.2 m — one
room by any erosion. The multi-room flats are `apartment_0` and `apartment_2`.
