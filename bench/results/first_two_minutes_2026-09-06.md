# What a stranger gets, on a flat levanta has never seen

`pip install` was proven to work and `levanta demo` produces thirteen files, but the demo is
an input the program already knows. This is the other path: a flat that is **not one of the
six bench scenes**, run end to end with nothing touched half way.

## 0. The previous attempt had died and nobody noticed

`out/replica_apt1/` held a walk video, a `frames/` directory and a log that stops on the
line after the weights load. No plan, no error, no follow-up. It is exactly the shape of
the tramo nobody walks: it failed on 2026-09-05 and was never looked at again. Re-run today
it completes in 57 s of card, **which proves it does not reproduce today and not that it was
transient**: a run that dies leaves no notice, and the absence of a notice reads exactly like
the absence of an attempt.

## 1. The pre-flight tells the user something untrue

```
walk.mp4: 1280x720, 80 s at 1 fps, 80 frames
sharpness: median 62, 10th percentile 10  (below 20 is blurry)
would keep 39 frames at 1 fps (11 windows had nothing sharp, 30 were title cards or blank)
! 30 s of title cards or blank frames: skipped (they are not the house)
```

**There are no title cards in this video.** It is a rendered walk through a flat. Those 30
frames are the camera looking at a blank wall, and the flatness detector, which exists to
throw away the title screens of produced tours, calls them "title cards or blank" and drops
them. A stranger reads that their footage contained half a minute of something that is not
their house, which is false, and **a third of their video is discarded** on the strength of
it. Cause named, not proven: there is no flag to disable the filter, so it was not tested.

## 2. What comes out

| | |
|---|---|
| truth (Replica `apartment_1`) | **56.8 m²** of floor, one room by the bench's watershed definition |
| levanta | **10.3 m²** in 2 rooms, ceiling 2.79 m measured |
| area error | **−82 %** |
| room count | 2 where there is 1 |

**The plan covers 18 % of the flat.** That is the number a stranger gets on a house levanta
has never seen, and it is four times worse than the bench's 19 %. **The two figures belong
together from now on: the bench is not an estimate of what a user receives, it is the best
case**, measured on scenes that were chosen, and this one was not.

## 3. What the sheet says about itself, which is the good half

```
! one side was not scanned; the outline follows the seen floor there
! less than half of the outline rests on floor that was seen (40 % on average)
· 4 of 4 walls were seen from one side only; their thickness is a default
! Scale comes from the network alone: pass --focal-px or calibrate with --door-width
· No window detected
```

Every one of those is true and each names what to do about it. The plan is wrong by a factor
of five and **it does not claim otherwise**: it stamps itself PRELIMINARY, marks both rooms
incomplete, and reports that 40 % of the outline rests on seen floor. The honesty
instrumentation of the last rounds does its job on the first real stranger's input.

## 4. What this does not cover

A rendered walk is steady, evenly lit, horizontal and 720p. The failures a real phone brings
— vertical video, low light, a 15-second clip, a hallway — are untested, and the search for a
freely licensed house-tour video to test them with came up empty. That remains open, and it
is the half of the first two minutes that decides whether someone tries again.


## 5. Was the filter the cause? No, and now it is measured

The pre-flight discards a third of the footage, and the plan comes out at a fifth of the
flat. Two facts that ask to be the same one. There was no way to test it, so
`extract_frames(flat_max=...)` and `levanta video --keep-flat` were added, and the same
pipeline ran twice on the same video:

| | frames | rooms | area | error | ceiling |
|---|---|---|---|---|---|
| filter on (today's default) | 39 | 2 | 10.27 m² | **−82 %** | 2.79 m |
| `--keep-flat` | **55** | 2 | 13.31 m² | **−77 %** | 3.42 m |

**The filter costs about 3 m², and it is not the reason the plan is a fifth of the flat.**
Sixteen frames come back and the area moves five points; four fifths of the floor are still
missing for another reason. The biggest suspected cause is eliminated, which is worth the
flag it took to test it.

The flag stays, off by default, with four tests: a plain wall does score above the threshold
like a title card, the filter does drop it, raising the bar keeps it, and a textured frame
survives either way. The filter's own docstring said a plain wall would trip it before any of
this was measured.

## 6. The division that changes whose problem it is

Frames per square metre, scene by scene, against the truth floor:

| scene | frames | floor | frames per m² |
|---|---|---|---|
| 41069021 | 184 | 19.1 m² | 9.64 |
| 47430051 ⚠ | 57 | 5.4 m² | 10.55 |
| 42897526 | 46 | 5.6 m² | 8.15 |
| 47331964 | 128 | 27.8 m² | 4.60 |
| 45260905 | 79 | 25.6 m² | 3.08 |
| **apt_1, the stranger's flat** | **55** | **56.8 m²** | **0.97** |

**Every scene the bench was measured on had three to eleven times the input density of the
one flat nobody chose.** The video is 80 s at 1 fps, so even keeping every frame it could
only reach 1.4 per m², still below the thinnest bench scene. **This walk could not have
produced a good plan at any setting**, and levanta never said so.

That does not make the planner innocent: with perfect depth on a different flat it still
misses rooms. It does mean the −82 % is not a fair measure of the planner, and that the
first thing a user needs is not a better model but a sentence before they start.

### So the sheet now says it

`FloorPlan.quality()` gains a check: frames per square metre of the cloud's own footprint,
below **1.5**, warns that the capture is thinner than any scene levanta has been measured
on and that the plan will be short of floor. The numbers behind the line: 6.53, 2.48 and
2.38 on real scenes, **0.78** on the thin one.

The denominator is the point. Using the plan's own area would make a sparse capture look
dense, because a plan that under-measures reports a flattering density: the same flat scores
4.1 frames per m² against its own 13.3 m² plan and 0.78 against the ground it actually
covers. The footprint over-estimates on some scenes and under-estimates on others, so it is
a gauge, not a measurement, and it separates by a factor of three.

### And a second canary was tried and dropped

A ceiling outside a dwelling's usual range looked like a free signal: the stranger's flat
measures 3.42 m. But the real scenes measure 2.09, 2.45, 2.55, 2.79, 2.85, 2.91 and
**3.204**. A threshold in a 0.22 m gap is fitted to two points, and old flats do have high
ceilings, so there is no defensible line and none was shipped. The ceiling does not separate
a bad reconstruction from an unusual room in the data available.
