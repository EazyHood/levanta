"""An area error from a reconstruction is printed with its scale, or not at all.

Four times in this project a respectable area figure was two errors of opposite sign.  The
last one, in the fps sweep of 2026-09-24: at 4 fps the larger room read −15 %, which was a
reconstruction 2.2 times too large (scale 0.45) holding a shape 83 % short.  A −15 % gets
quoted on its own; a −15 % that says "shape −83 %, scale 0.45" does not.

So every bench that reports an area error against truth formats it here, and
`tests/test_area_error_never_alone.py` fails if one of them prints it any other way, the
same way the planner bench no longer prints an aggregate of the room count.

Scale follows the benches' own convention: the factor that carries levanta's cameras onto
the true ones (below 1 means levanta drew the place too big), so the shape is the area
once multiplied by scale squared.
"""

from __future__ import annotations

EXEMPT_REASON = "exact depth and exact poses: there is no reconstruction scale to hide"


def shape_pct(error_pct: float, scale: float) -> float:
    """The area error left once the scale is divided out."""
    return ((1.0 + error_pct / 100.0) * scale * scale - 1.0) * 100.0


def area_with_scale(error_pct: float | None, scale: float | None) -> str:
    """A raw area error in levanta's own metres, with the two things it is made of."""
    if error_pct is None:
        return "—"
    if scale is None or not scale > 0:
        raise ValueError("an area error from a reconstruction is printed with its scale or not at all")
    return f"{error_pct:+.0f} % (shape {shape_pct(error_pct, scale):+.0f} %, scale {scale:.2f})"


def area_vs_reference(error_pct: float | None) -> str:
    """A change against levanta's own published example, planned from the same cloud: the
    reconstruction is not in the comparison, so there is no scale to report."""
    if error_pct is None:
        return "—"
    return f"{error_pct:+.0f} % vs the published example, same cloud"


def area_shape(shape_error_pct: float | None, scale: float | None) -> str:
    """An area error that was already computed with the scale divided out, labelled so."""
    if shape_error_pct is None:
        return "—"
    if scale is None or not scale > 0:
        raise ValueError("a scale-corrected area error names the scale it divided out")
    return f"shape {shape_error_pct:+.0f} % (scale {scale:.2f} divided out)"
