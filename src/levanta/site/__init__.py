"""Public building data (OpenStreetMap, Overture Maps) -> LOD1 3D model and site plan.

What a satellite can and cannot give you
----------------------------------------
Every public footprint dataset is derived from overhead imagery (Google Open Buildings,
Microsoft Building Footprints, and the human-traced OpenStreetMap).  That imagery shows
the *roof*: outline, roof shape, and, from stereo pairs or shadows, an approximate
height.  It does not show walls, and it can never show the interior; there is no sensor
that sees through a roof.  This module therefore produces exactly what the data
supports: footprint + height = a *Level of Detail 1* block model and a site plan with
dimensions.  Interior plans come from :mod:`levanta.plan`.
"""

from __future__ import annotations

from levanta.site.lod1 import export_site, lod1_mesh
from levanta.site.projection import LocalProjection
from levanta.site.sources import Building, fetch_buildings

__all__ = ["Building", "LocalProjection", "export_site", "fetch_buildings", "lod1_mesh"]
