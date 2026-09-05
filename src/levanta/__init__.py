"""levanta — from a phone video (or public satellite-derived data) to a 3D model and 2D/3D floor plans.

The package is organised as a pipeline of independent, importable stages:

``levanta.io``      read videos, RGB-D datasets, point clouds; write SVG / DXF / GLB / OBJ / JSON.
``levanta.recon``   turn frames into a metric point cloud (RGB-D back-projection, MapAnything).
``levanta.plan``    turn a point cloud into a :class:`~levanta.plan.types.FloorPlan` and a 3D mesh.
``levanta.site``    turn public building footprints (OpenStreetMap, Overture) into LOD1 models.

Every stage can be used on its own; :mod:`levanta.cli` wires them together.
"""

from __future__ import annotations

from levanta.plan.pipeline import PlanOptions, extract_floor_plan
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from levanta.scene import PointCloud

__version__ = "0.1.0"

__all__ = [
    "FloorPlan",
    "Opening",
    "PlanOptions",
    "PointCloud",
    "Room",
    "Wall",
    "__version__",
    "extract_floor_plan",
]
