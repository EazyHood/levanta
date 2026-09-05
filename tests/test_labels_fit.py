"""Room labels stay inside their room; wall tags stay off the labels.

On the first real walkthrough sheet (5 rooms, 23 walls; `tests/data/video_real_plan.json`)
"Room 3 (incompleta)" ran over both walls of a 1.40 m corridor and marker M12 sat on
top of "4.05 m²".

Thresholds written before the fix ran, on the A3 sheet at its print scale:
- every room-label text lies inside its room's polygon dilated by LABEL_SLACK metres;
- no wall-tag circle overlaps a room-label box;
- no label line is drawn smaller than MIN_SIZE px (it is shrunk, not squashed).
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import Point

from levanta.io.export import fit_print_scale
from levanta.io.pdf import text_width
from levanta.plan.types import FloorPlan

LABEL_SLACK = 0.05
MIN_SIZE = 6.0
DATA = Path(__file__).parent / "data" / "video_real_plan.json"


def _sheet():
    plan = FloorPlan.from_json(DATA)
    d, _pw, _ph, _ox, _oy, _s, _info = fit_print_scale(plan, "A3", "landscape", lang="es")
    m = d.meta  # X(x) = ox + (x - xmin) * scale, Y(y) = oy + (ymax - y) * scale
    return plan, d, m["ox"] - m["xmin"] * m["scale"], m["oy"] + m["ymax"] * m["scale"], m["scale"]


def _label_boxes(d, ox, oy, s):
    """Room-label text boxes in plan metres (``ox``/``oy``: pixel of plan x=0 / y=0)."""
    boxes = []
    for p in d.prims:
        if p.kind == "text" and p.cls == "label":
            w = text_width(p.text, p.size, p.weight == "bold")
            x0 = p.x - w / 2 if p.anchor == "middle" else p.x
            boxes.append(((x0 - ox) / s, (oy - p.y) / s, (x0 + w - ox) / s, (oy - (p.y - p.size)) / s, p))
    return boxes


def test_room_labels_are_inside_their_rooms():
    plan, d, ox, oy, s = _sheet()
    boxes = _label_boxes(d, ox, oy, s)
    assert len(boxes) >= 2 * len(plan.rooms)
    for x0, y0, x1, y1, p in boxes:
        room = next((r for r in plan.rooms if r.shapely.buffer(LABEL_SLACK).contains(Point((x0 + x1) / 2, (y0 + y1) / 2))), None)
        assert room is not None, p.text
        dil = room.shapely.buffer(LABEL_SLACK)
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            assert dil.contains(Point(cx, cy)), (room.name, p.text, p.size)
        assert p.size >= MIN_SIZE - 1e-9


def test_wall_tags_do_not_sit_on_room_labels():
    _plan, d, ox, oy, s = _sheet()
    boxes = _label_boxes(d, ox, oy, s)
    circles = [p for p in d.prims if p.kind == "circle" and p.cls == "wall-tag-circle"]
    assert circles
    for c in circles:
        cx, cy, r = (c.x - ox) / s, (oy - c.y) / s, c.r / s
        for x0, y0, x1, y1, p in boxes:
            assert not (x0 - r < cx < x1 + r and y0 - r < cy < y1 + r), (p.text, cx, cy)
