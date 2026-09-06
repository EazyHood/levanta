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
