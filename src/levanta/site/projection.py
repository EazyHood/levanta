"""WGS84 <-> local east/north metres around an origin (no pyproj needed).

Uses the ellipsoid's radii of curvature at the origin latitude, which keeps the error
below a centimetre for the few hundred metres a site plan spans.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


@dataclass
class LocalProjection:
    lat0: float
    lon0: float

    def __post_init__(self) -> None:
        phi = np.deg2rad(self.lat0)
        s2 = np.sin(phi) ** 2
        self.N = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s2)  # prime vertical
        self.M = WGS84_A * (1.0 - WGS84_E2) / (1.0 - WGS84_E2 * s2) ** 1.5  # meridional
        self.cos0 = np.cos(phi)

    def to_local(self, lon, lat) -> np.ndarray:
        """(..., 2) array of (east, north) metres."""
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        x = np.deg2rad(lon - self.lon0) * self.N * self.cos0
        y = np.deg2rad(lat - self.lat0) * self.M
        return np.stack([x, y], axis=-1)

    def to_wgs84(self, x, y) -> np.ndarray:
        """(..., 2) array of (lon, lat) degrees."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        lon = self.lon0 + np.rad2deg(x / (self.N * self.cos0))
        lat = self.lat0 + np.rad2deg(y / self.M)
        return np.stack([lon, lat], axis=-1)
