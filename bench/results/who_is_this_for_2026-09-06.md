# Who asks for what levanta gives?

The question was put as a product question and answered by looking up what people who do
this actually specify, not by reasoning about it. Three tiers exist and they are documented.

## 1. What is asked for, by use

| use | tolerance asked for | source |
|---|---|---|
| measured building survey / as-built for construction | **±2 mm** across the structure; ±6 mm on large commercial, ±12 mm on small renovations | industry practice for measured surveys |
| legal documents (lease plans, rent reviews) | under **1 %** of net internal area, because 1 % on an office is money | Photoplan, RICS practice |
| **marketing floor plan for a listing** | **±2 % of gross internal area** as the professional target, **±5 %** as the consumer-protection floor; individual walls **±20-50 mm** | RICS guidance, IPMS, ANSI Z765 |
| phone LiDAR apps, already on the market | **±20-50 mm per wall**, described as fit for furniture planning and *not* for legal or commercial use | Photoplan |

## 2. What levanta gives, measured today

| | |
|---|---|
| mean absolute area error, six scenes it stands behind | **19 %** |
| the same flat with **perfect** depth and poses, per room | **−65 %, −27 %, +162 %** |
| camera drift over a 35 m walk | **~1 m** |
| walls found, against the real wall | 12-48 % |

## 3. The answer

**Nobody documented asks for this.** Not as a margin: by 3× against the loosest consumer
floor and by two to three orders of magnitude against a survey.

The tier that looked like a fit — "a rough idea, or a draft somebody corrects by hand" — is
**already occupied, and its occupants are 20 to 50 times more accurate**. A phone with LiDAR
gives ±20-50 mm per wall today, and even that is published as unfit for legal or commercial
use. levanta at ±1 m and 19 % sits below the floor of the loosest tier that anyone has
written down.

**What levanta does that those do not** is the honest half of the answer, and it is one
thing: it needs **no depth sensor**. Those figures are for LiDAR phones. It is also MIT,
offline, and emits DXF with AIA layers and a PDF at scale, which is a real difference in
kind but not in accuracy.

## 4. What follows for the roadmap

**Precision is the binding constraint, and the target is not the one we have been chasing.**
Reducing 1 m of drift to 0.5 m crosses no line, because no line is drawn there. The line
that exists is **±5 % of area**, the consumer floor, and levanta is at 19 %. Nothing else
moves the project across it: not more export formats, not a better sheet, not usability.

And the per-room numbers say where the work is. With *perfect* depth the rooms are −65 %,
−27 % and +162 %, so the reconstruction is not what stands between levanta and 5 %. **The
planner is.** That agrees with every measurement of the last twelve rounds and it is the
first time the target has a number that comes from outside the project.

Sources: [Photoplan on floor plan accuracy](https://www.photoplan.co.uk/guides/how-accurate-are-floor-plans),
[RICS measuring standards](https://www.photoplan.co.uk/guides/rics-measuring-standards-explained),
[IPMS residential](https://ipmsc.org/wp-content/uploads/2016/09/ipms-residential-buildings-sept-2016.pdf),
[measured building survey practice](https://xpsurveys.co.uk/measured-survey/).


---

## 5. And the other half: who needs a plan and has no depth sensor?

Every figure above comes from people who already have LiDAR, so the open question was whether
the segment without it accepts less. It does not, and the segment is not empty either.

**It exists and it has a name.** `magicplan` works on any phone without LiDAR and its stated
focus is **insurance claims, inspections and loss adjustment**; `RoomScan Pro` and `CamToPlan`
serve the same gap on Android. So the "no depth sensor" niche is real, occupied, and already
addressed by tools that do not need one.

**Its tolerance is tighter than what levanta delivers, not looser.** In insurance estimating,
a **15-25 % discrepancy in square footage** is described as the significant variance that
inflates or deflates the total, which is to say it is the error being eliminated, not the
tolerance accepted. **levanta's 19 % lands inside it.**

**And the loosest documented tier does not save it.** Marketing plans published as
*"illustrative purposes only, not to scale"* are a real category with standard disclaimers,
but the ±5 % consumer-protection floor still applies to any stated area; the disclaimer covers
approximation, not being wrong by a fifth.

### What that changes

If a plan states no areas at all, then area error stops mattering to the reader and what is
left is the **layout**: how many rooms there are and how they connect. That is the one escape
route the tolerances leave open, and **levanta does not currently qualify for it either**: on
the only three-room flat measured it finds one or two rooms, and on one scene it draws 0 % of
the partition.

So there is a second target beside the ±5 %, and it is not a tolerance:

> **Get the number of rooms right.** A plan with three rooms and approximate areas serves the
> illustrative tier. A plan with one room where there are three serves nobody, at any
> tolerance, because no disclaimer covers a missing room.

That is a gate rather than a gradient, which makes it the cheaper of the two to aim at, and
it is the same fusion the last several rounds have been circling.

Sources for this section: [room scan apps compared](https://www.arcsite.com/blog/room-scan-apps),
[floor plan apps for real estate](https://roomio.io/articles/best-floor-plan-apps-real-estate/),
[Xactimate sketching accuracy](https://prideestimating.com/mastering-xactimate-sketching/),
[estate agent vs architectural plans](https://www.spacesurvey.co.uk/post/illustrative-vs-accurate-the-difference-between-estate-agent-plans-and-architectural-plans).
