# What would fix a long take: the options, their cost, and the measurement for each

Written on 2026-09-24, before any of them is coded, with every threshold fixed here. The laps
on the rendered flat (`replica_laps_2026-09-24.md`) kept the scale over 14 chunks and still
drew the rooms twice: camera error 1.08 m over one lap, 2.11 m over three. This page lists the
ways to reduce that, what each would move and what it would not, and how each would be judged.
One is chosen and measured; the rest wait.

## First, what the evidence already says

Two measurements from earlier rounds change the order of this page.

- *(Corrected at the end of this page, the same afternoon: what follows was the network's
  focal length, not its depth scale, and it is why option A found nothing to fix.)*
  **On this flat the plan fails even with exact poses.** Handing the network the true pose of
  every frame still gives one room of three and −43 % of area; a perfect cloud gives three
  rooms (README, round 6). What goes wrong first is the **scale of each view's depth**: half
  the truth and swinging by a factor of two between views (0.37 to 0.70). The laps showed the
  same bias per chunk (depth at 0.55 of the truth while the cameras sit at about 1). A fix to
  the pose chain alone cannot give this flat back its rooms.
- **More shared frames has been tried here.** Composing chunks with 8 of 16 or 6 of 12 views
  shared left the camera error at 1.05 and 1.01 m against about 1.0 (`overlap_sweep.json`,
  round 5). TSDF + ICP per chunk moved it by ±0.03 m, and the ceiling as an anchor lost on five
  scenes of five.

## The options

| | what changes | cost | should move | will not move | evidence so far |
|---|---|---|---|---|---|
| **A. Per-view depth made consistent** | each view's depth rescaled to agree with its neighbours where they overlap, before fusing | 1-2 days, CPU, on dumped views | shape, rooms, the depth/camera disagreement | a drift of the cameras themselves | the measured cause on this flat |
| **B. Links from the shared points** | chunk k placed on k−1 by registering the 3D points of their shared views, not by camera centres and a depth ratio | half a day, CPU, recomposes the chunks already dumped | rotation and translation per link, hence camera error | per-view depth scale | none; cheapest real test of the pose chain |
| **C. Yaw from the walls** | each chunk turned so its dominant wall directions match the walk's (the planner already assumes right angles) | half a day, CPU, on the dumps | yaw drift, rooms laid down rotated | translation drift, depth scale | none |
| **D. One alignment for the whole walk, with loop closure** | all chunks solved together; edges between chunks that see the same place again (a corridor walked twice) | 2-4 days: loop detection plus a 7-DoF pose graph | camera error and duplicated rooms at revisits | a walk that never revisits; depth scale | none; the laps make detection too easy (identical frames) |
| **E. An anchor that does not drift** | each chunk's floor plane and the camera's height above it held constant | 1 day, CPU | tilt, height, and a scale consistency from eye height | yaw and horizontal drift, which is what moved the rooms | the ceiling version lost 5 of 5; gravity from the phone's IMU is not in the videos we have |
| **F. More views per chunk at a lower resolution** | 48 views instead of 24 if the network accepts a smaller picture | an hour to try, GPU | fewer links | drift inside a chunk; depth quality may drop | unknown whether the loader takes a lower resolution |
| **G. More shared frames** | 8 or 12 of 24 shared | none, a flag | little | | already measured: 1.01-1.05 m against 1.0 |

## How each would be judged, fixed now

Every pose option (B to G) runs on the same two walks and must meet all of:

- **three laps**: camera error at most **1.3 m** (today 2.11 m) and **no more than three
  rooms** (today four of three);
- **one lap**: camera error no worse than **1.18 m** (today 1.08 m + 0.10);
- **ARKitScenes 41069021 at 1 fps**: floor IoU at least **0.60** (today 0.65 − 0.05), so the
  fix does not break the real walk that works.

The depth option (A) is judged where its cause was measured:

- **Replica with exact poses** (`bench/known_poses.py`): at least **two rooms of three** and area
  within **±25 %** (today one room, −43 %);
- **one lap, the normal pipeline**: floor IoU at least **0.26** (today 0.16 + 0.10);
- **ARKitScenes 41069021 at 1 fps**: floor IoU at least **0.60**.

## The recommendation

**A first**, because it is the only option aimed at what was measured to fail first on this
flat, and because every pose fix is capped by it: exact poses already give one room of three.
**B next**, because it costs half a day on chunks already on disk and tests the pose chain
directly, with no GPU. D is the right long-term structure for a whole home but the most
expensive, and it should wait until A and B say how much is left for it to fix. G is already
answered.

What none of these touch: everything here is measured on one rendered flat and one real
room. A fix that passes still has to pass on a phone video of a real home before anything
about long takes is said outside the bench.

## Option A, measured before it went into the pipeline: nothing to fix

The supervisor's two conditions were written into the estimator before it was coded
(`src/levanta/recon/depth_consistency.py`): consistency of the **3D points** through the
network's own relative poses, not depth against depth, and **no constant**, every scale
solved from the walk's own data. On a box room whose answer is known it recovers true depths
at 1, a uniform 0.55 at 1/0.55 and per-view factors from 0.4 to 0.7, each within 5 %, and
reports a camera that only turns as not estimable (`tests/test_depth_consistency.py`).

On the chunks already on disk (`bench/depth_consistency_check.py`, no GPU):

| scene | chunks estimable | views | depth scale that makes the points agree, median | range |
|---|---|---|---|---|
| Replica, one lap | 5 of 5 | 110 | 1.00 | 0.80 to 1.19 |
| Replica, three laps | 14 of 14 | 334 | 0.97 | 0.07 to 1.99 |
| ARKitScenes 41069021, 1 fps | 9 of 9 | 216 | 1.01 | 0.97 to 1.17 |
| ARKitScenes 41069021, 4 fps | 36 of 36 | 855 | 1.02 | 0.86 to 2.70 |

**The network's depth and its own poses agree with each other, on both scenes.** The camera
steps confirm it: on the rendered flat each reconstructed step is as long as the true one
(median 1.02 over one lap, 0.99 over three). So the "depth at 0.55 while the cameras sit at 1"
that motivated A was a wrong reading, mine, and A would move nothing: it is not wired into
the pipeline.

**What the 0.55 really is: the focal length.** On these renders the network estimates a focal
of about 195 px at 518 px wide, a 106° field of view, where the renderer used 70° (370 px).
A focal at 0.536 of the truth squashes every surface along the line of sight by the same
factor and leaves lateral positions and camera steps alone. View by view:

| walk | network focal / true focal | predicted depth / true depth | depth ratio / focal ratio |
|---|---|---|---|
| one lap, 110 views | 0.536 (0.51 to 0.71) | 0.533 | 0.985 |
| three laps, 334 views | 0.536 (0.51 to 0.74) | 0.541 | 0.993 |

On the real video the network's focal is much closer: 0.93 of ARKit's own (median; 0.51 to
1.28), which is why "a known focal does not help" on ARKitScenes (round 3). The synthetic
renders, flat-shaded with no lighting, are what fool the field of view.

**Consequences, written before anything else is run.**

- The round-6 finding in the README ("the scale of its depth is half the truth and swings
  between views", with exact poses giving one room of three) was measured **without the focal
  length passed to the network**. It was this, not a depth-scale defect.
- Every number from the rendered flat run without `--focal-px` measures the network's focal
  guess first. The laps' comparison of one lap with three still isolates the chain (both share
  the same guess), but their absolute shape figures are dominated by it. From here on the
  rendered flat is run with its true focal, or not at all.
- The next measurement is still **B**, and on the rendered flat it is judged with the true focal
  passed, one lap and three, against the thresholds above.
