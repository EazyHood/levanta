"""`levanta video` hands the right checkpoint name to the backend, phone or no phone.

Regression: the phone lookup reused the name ``model`` inside the video command and
shadowed the ``--model`` option; with a video that carried no phone model the backend was
built with ``model_name=None`` and every reconstruction died at loading ("MapAnything
(None)").  Five of ten benchmark runs went that way.

The network is replaced by a stub that records what it was built with and returns the
synthetic apartment, so the whole command runs in seconds without a GPU.
"""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest
from typer.testing import CliRunner

torch = pytest.importorskip("torch")

from levanta.cli import app  # noqa: E402
from levanta.synthetic import sample_apartment, three_rooms  # noqa: E402


class StubBackend:
    built: list[dict] = []

    def __init__(self, model_name=None, **kw):
        StubBackend.built.append({"model_name": model_name, **kw})

    def reconstruct(self, frames):
        cloud = sample_apartment(three_rooms(), seed=7)
        cloud.meta.update({"source": "mapanything", "views": len(frames), "chunks": 1})
        return cloud


def _clip(path, seconds=6, fps=10.0):
    cv2 = pytest.importorskip("cv2")
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 180))
    rng = np.random.default_rng(0)
    for _ in range(int(fps * seconds)):
        w.write(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
    w.release()
    return path


def test_video_without_a_known_phone_still_uses_the_default_checkpoint(tmp_path, monkeypatch):
    import levanta.recon.mapanything as backend

    monkeypatch.setattr(backend, "MapAnythingBackend", StubBackend)
    monkeypatch.setitem(sys.modules, "mapanything", types.ModuleType("mapanything"))
    StubBackend.built.clear()
    clip = _clip(tmp_path / "walk.mp4")
    r = CliRunner().invoke(app, ["video", str(clip), "-o", str(tmp_path / "out"), "--max-views", "8"])
    assert r.exit_code == 0, r.output
    assert StubBackend.built and StubBackend.built[0]["model_name"] == "facebook/map-anything-apache"
    assert StubBackend.built[0]["max_views"] == 8 and StubBackend.built[0]["overlap"] == 4
    assert "no known phone" in r.output
    plan = json.loads((tmp_path / "out" / "plan.json").read_text(encoding="utf-8"))
    assert plan["rooms"] and plan["meta"]["source"] == "mapanything"
    assert "PRELIMINAR" in (tmp_path / "out" / "plan.svg").read_text(encoding="utf-8")
