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
