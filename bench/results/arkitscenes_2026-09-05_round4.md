# Round 4: what the benchmark ordered, measured before and after

Same five ARKitScenes scenes, same script (`bench/arkitscenes.py`), same metrics; "before" is
commit `445bffa` ([the first table](arkitscenes_2026-09-05.md)), "after" is `639158d` plus
the flag threshold of this round. Thresholds set by the review before the work: camera
RMS ≤ 0.30 m on 4 of 5; area error within ±15 % on 3 of 5; the collapsed bathroom flagged
instead of drawn.

## What changed

1. **Chunk scale from depth, not from four camera centres.** Every chunk after the first is
   placed on the previous one; the scale used to come from a similarity fitted on the four
   shared camera centres (half a metre apart), and per-chunk scales against the truth came
   out 0.66–1.21 inside one room. Now the scale is the median ratio of the depths both
   chunks predicted for the shared views' pixels (`align_chunk`). Consecutive chunk
   scales are now within 0.86–1.06 on the sound scenes.
2. **The outline reaches the walls.** An open room's edge snaps to the nearest parallel
   wall up to 2.5 m out (was 1.0 m, and the farthest wall with the most overlap won).
3. **A broken reconstruction says so.** Median mask coverage under 10 %, a chunk scaled by
   less than 0.5 or more than 2, or chunk scales spread over more than 2.5× flag the plan:
   check `unreliable`, sheet stamped *NOT RECONSTRUCTIBLE · mirror or glass*.

## Scale from the network alone (no K)

| scene | truth floor / rooms | scale before → after | area error before → after | floor IoU before → after | camera RMS before → after | rooms | flagged |
|---|---|---|---|---|---|---|---|
| 41069021 | 17.5 m² / 1 | 1.00 → **1.03** | −22 % → **−25 %** | 0.61 → **0.65** | 0.42 → **0.47** m | 1 (1) | no |
| 42897526 | 4.9 m² / 1 | 0.95 → **1.00** | +31 % → **+8 %** | 0.52 → **0.48** | 0.49 → **0.49** m | 1 (1) | no |
| 45260905 | 25.3 m² / 1 | 1.30 → **1.31** | −24 % → **−28 %** | 0.69 → **0.69** | 0.61 → **0.59** m | 1 (1) | no |
| 47331964 | 24.0 m² / 2 | 0.97 → **0.90** | −44 % → **−9 %** | 0.40 → **0.46** | 0.88 → **0.82** m | 3 (2) | no |
| 47430051 | 4.2 m² / 1 | 0.26 → **0.25** | +78 % → **+12 %** | 0.07 → **0.06** | 0.75 → **0.75** m | 1 (1) | **yes** |

## With the focal length ARKit recorded (with K)

| scene | scale before → after | area error before → after | floor IoU before → after | camera RMS before → after | rooms | flagged |
|---|---|---|---|---|---|---|
| 41069021 | 1.07 → **1.00** | −30 % → **−19 %** | 0.60 → **0.71** | 0.36 → **0.37** m | 2 (1) | no |
| 42897526 | 0.97 → **1.01** | +46 % → **+22 %** | 0.56 → **0.55** | 0.42 → **0.42** m | 2 (1) | no |
| 45260905 | 1.32 → **1.30** | −26 % → **−28 %** | 0.68 → **0.71** | 0.44 → **0.45** m | 1 (1) | no |
| 47331964 | 1.00 → **0.89** | −75 % → **−59 %** | 0.19 → **0.22** | 0.89 → **0.82** m | 1 (2) | no |
| 47430051 | 0.25 → **0.24** | +52 % → **+47 %** | 0.06 → **0.06** | 0.75 → **0.76** m | 1 (1) | **yes** |

## Against the thresholds

- **Camera RMS ≤ 0.30 m on 4 of 5: not met** (0.47, 0.49, 0.59, 0.82, 0.75). The chaining
  is no longer the limit: consecutive chunk scales agree within 14 %, yet each chunk on
  its own fits ARKit's cameras with an RMS of 0.12–0.56 m and a per-chunk scale of
  0.65–1.32 *against the truth* — the network's geometry inside a set of 24 frames is
  bent, not just misplaced. A pose graph optimises how chunks sit against each other; it
  cannot straighten a chunk. That is where the next 0.2 m is: more or better-spread views
  per chunk, or refining the chunk's cameras on the point cloud itself.
- **Area within ±15 % on 3 of 5: not met, 2 of 5** (+8 %, −9 %; the flagged bathroom's +12 %
  does not count). The two big moves are real: 47331964 from −44 % to −9 % and 42897526
  from +31 % to +8 %; 41069021 dropped from two rooms to the one there is (IoU 0.61 → 0.65,
  and 0.71 with K). The two that stay short (−25 %, −28 %) are floor the camera never went
  near (a hallway at the far end, a 30 % scale error in the first chunk).
- **The bathroom is flagged**: coverage 5 % of a frame; the sheet now carries the stamp
  instead of a 4.7 m² room.

## The biggest scene the dataset has

42897599, the largest of 44 validation meshes screened: **35.1 m², one room, a 301 s walk,
302 frames in 15 chunks**. It did not survive: 2 walls, 0 rooms, chunk scales 0.53–1.73
(now flagged by the spread rule). The run without K then crashed exporting an empty
GLB, which is fixed. Fifteen chunks chained head to tail is exactly the regime the RMS
line above describes; it is the honest ceiling of the current chaining.
No scene of the dataset is an apartment (≥ 40 m², ≥ 3 rooms): one video is one room by
design; what would give one is in [the first notes](arkitscenes_2026-09-05.md#bigger-scenes-not-in-this-dataset).
