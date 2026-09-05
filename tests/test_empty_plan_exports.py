"""A plan with nothing in it still produces every output, stamped, instead of crashing.

ARKitScenes 42897599 (301 s, 15 chunks) reconstructed to 2 walls and 0 rooms and the run
died in `export_all` with trimesh's "Can't export empty scenes!" — after 862 s of GPU.
The sheet that should have come out is the one that says NOT RECONSTRUCTIBLE.

Thresholds written before the fix ran: `export_all` on a plan with no walls, rooms or
openings returns every format, the GLB and OBJ files exist and are non-empty, and the SVG
carries the stamp.
"""

from __future__ import annotations

from levanta.io.export import export_all
from levanta.plan.types import FloorPlan


def test_empty_plan_exports_everything(tmp_path):
    plan = FloorPlan(walls=[], rooms=[], openings=[], ceiling_height=2.5, ceiling_measured=False)
    plan.meta.update({"source": "mapanything", "chunk_scales": [0.53, 1.73, 1.0], "mask_fraction": 0.6})
    out = export_all(plan, tmp_path, lang="es")
    for key in ("glb", "obj", "svg", "png", "pdf", "html", "json", "dxf"):
        assert key in out and out[key].exists() and out[key].stat().st_size > 0, key
    assert "NO RECONSTRUIBLE" in out["svg"].read_text(encoding="utf-8")
