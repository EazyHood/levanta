# One lap against three: a long chain of sound chunks keeps its scale, and still draws the rooms twice

The fps sweep could not say whether a long take at the default keeps its scale: raising the
fps lengthened the chain and shortened every chunk at once. This measures the chain alone.
The design and the rule were written and committed before any video was built
(`bench/replica_laps.py`, commit 98b690a), with the supervisor.

**Setup.** Replica `apartment_0` (51.8 m², three rooms), the walk of round 5, frames already
rendered with their exact depth. One lap is the 116 frames in order; three laps are the same
frames there, back and there again, 346 frames with no jump. Both through `levanta video` as a
user runs it: 1 fps, 24 views per chunk, 4 shared, no focal length. The frame filter kept 94
and 282 frames, so the chains are 5 and 14 chunks, every chunk about 20 seconds of walk.

## The verdict

| walk | frames | chunks | area error | floor IoU | rooms (truth 3) | camera error | chunks apart in size |
|---|---|---|---|---|---|---|---|
| one lap | 94 | 5 | −44 % (shape −35 %, scale 1.07) | 0.16 | 1 | 1.08 m | 1.55 |
| three laps | 282 | 14 | +77 % (shape +56 %, scale 0.94) | 0.39 | 4 | 2.11 m | 2.01 |

Rule, written before any run: at three laps, scale within ±15 % of the truth and floor IoU no
more than 0.05 below one lap's. **It holds**: scale 0.94, IoU 0.39 against a floor of 0.11.

## What the verdict does not say

- **The IoU half of the rule was loose, because the baseline was poor.** One lap finds one
  room of three at IoU 0.16, as round 5 found on this flat. A floor of 0.11 is easy to clear.
  The half that bites is the scale, and that one held: fourteen chunks of sound length,
  handed down link by link, end 6 % from the truth.
- **The scale held; the walk did not.** Between five chunks and fourteen the camera error
  doubles (1.08 m to 2.11 m), the shape goes from 35 % short to 56 % over, the rooms go from
  one to four and the walls from 4 to 14. The second and third laps lay the same rooms down
  again a little elsewhere. IoU rises because the rooms now cover more of the floor, not
  because the plan is better. A long take keeps its size and loses its shape.
- **So the defect of a long take is the pose chain, not the scale chain.** That matches the
  fps sweep's chain experiment, where keeping each chunk's own scale stopped nothing because
  the poses were still chained.

## Each chunk's own scale, beside the verdict

The same two walks with every chunk solved on its own and kept raw. The first four chunks of
both runs agree to three decimals, as they should: the setup is deterministic.

| walk | chunks | own scale by depth, median | range | own scale by cameras, median | range |
|---|---|---|---|---|---|
| one lap | 5 | 1.81 | 1.66 to 1.94 | 0.59 | 0.22 to 1.22 |
| three laps | 14 | 1.81 | 1.47 to 2.12 | 0.71 | 0.19 to 1.29 |

- **By depth**, which does not depend on how far the camera moved, each chunk's own scale is
  **steady along the chain**: the same median at 5 and at 14 chunks, no drift with position.
  On these renders the network puts every surface at about 0.55 of its true distance, the
  per-view 0.37 to 0.70 round 6 found with exact poses. That is a constant bias of the network
  on synthetic pictures, not something the chain does.
- **By cameras** the fits are too poor to read: residuals of 0.40 to 0.85 m on 2.5 to 8 m of
  travel per chunk. Kept for completeness, not as a measurement.
- That the depth sits at 0.55 while the whole walk's cameras come out at 0.94 to 1.07 means
  the network's depth and its camera motion disagree by nearly a factor of two inside a
  chunk. It is the same disagreement round 6 named, and it is why the shape is wrong even
  where the scale is right.

## What changes

- `levanta check` no longer says "not measured" between 10 and 14 chunks. It says that on a
  rendered flat 14 chunks kept the scale within 6 %, that the camera track drifted twice as
  far, and that the plan drew rooms twice. Past 14 it still says nothing is known.
- The capture guide says the same in both languages.
- The default does not change.

**Synthetic, and it repeats itself.** Replica has flat shading, no motion blur and perfect
exposure, and its second and third laps show the network exactly the same pictures again.
Holding the scale here is necessary for a phone video, not sufficient.
