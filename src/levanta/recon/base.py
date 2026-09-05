"""Backend protocol and registry.

A backend turns a list of :class:`~levanta.scene.Frame` objects into a
:class:`~levanta.scene.PointCloud` in metres.  Two kinds exist:

* **RGB-D** (:mod:`levanta.recon.rgbd`): the frames already carry depth and poses
  (datasets, ARCore/ARKit/Record3D exports).  Pure numpy, no GPU.
* **MapAnything** (:mod:`levanta.recon.mapanything`): plain RGB frames from a phone
  video; a feed-forward network predicts metric depth, intrinsics and poses.  Needs
  ``torch`` and the ``mapanything`` package (see ``requirements-recon.txt``).
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from levanta.scene import Frame, PointCloud


@runtime_checkable
class ReconBackend(Protocol):
    """Anything with a ``name`` and a ``reconstruct(frames) -> PointCloud`` method."""

    name: str

    def reconstruct(self, frames: Sequence[Frame]) -> PointCloud: ...


_REGISTRY: dict[str, str] = {
    "rgbd": "levanta.recon.rgbd:RGBDBackend",
    "mapanything": "levanta.recon.mapanything:MapAnythingBackend",
}


def available_backends() -> list[str]:
    return sorted(_REGISTRY)


def get_backend(name: str, **kwargs) -> ReconBackend:
    """Instantiate a backend by name; raises a helpful error when its extras are missing."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown backend {name!r}; choose one of {available_backends()}")
    module_name, cls_name = _REGISTRY[name].split(":")
    module = importlib.import_module(module_name)
    return getattr(module, cls_name)(**kwargs)
