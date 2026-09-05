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


# ----------------------------------------------------------------------------------------
# UTM (WGS84), the frame civil drafters expect on a site plan
# ----------------------------------------------------------------------------------------

_K0 = 0.9996
_E = WGS84_E2
_E2 = _E * _E
_E3 = _E2 * _E
_E_P2 = _E / (1.0 - _E)
_M1 = 1 - _E / 4 - 3 * _E2 / 64 - 5 * _E3 / 256
_M2 = 3 * _E / 8 + 3 * _E2 / 32 + 45 * _E3 / 1024
_M3 = 15 * _E2 / 256 + 45 * _E3 / 1024
_M4 = 35 * _E3 / 3072
_BANDS = "CDEFGHJKLMNPQRSTUVWXX"


def utm_zone(lat: float, lon: float) -> tuple[int, str]:
    """UTM zone number and latitude band letter (with the Norway/Svalbard exceptions)."""
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    elif 72 <= lat <= 84 and lon >= 0:
        zone = 31 if lon < 9 else 33 if lon < 21 else 35 if lon < 33 else 37 if lon < 42 else int((lon + 180) / 6) + 1
    else:
        zone = int((lon + 180) / 6) + 1
    band = _BANDS[int((lat + 80) / 8)] if -80 <= lat <= 84 else "Z"
    return zone, band


def utm_from_latlon(lat: float, lon: float) -> dict:
    """WGS84 lat/lon -> UTM easting/northing (metres), zone, band, hemisphere and EPSG code.
    Standard transverse-Mercator series; agrees with GIS tools to well under a metre."""
    zone, band = utm_zone(lat, lon)
    lat_r = np.deg2rad(lat)
    s, c, tn = np.sin(lat_r), np.cos(lat_r), np.tan(lat_r)
    tn2, tn4 = tn * tn, tn**4
    lon0 = (zone - 1) * 6 - 180 + 3
    n = WGS84_A / np.sqrt(1 - _E * s * s)
    cc = _E_P2 * c * c
    a = c * np.deg2rad(lon - lon0)
    a2, a3, a4, a5, a6 = a * a, a**3, a**4, a**5, a**6
    m = WGS84_A * (_M1 * lat_r - _M2 * np.sin(2 * lat_r) + _M3 * np.sin(4 * lat_r) - _M4 * np.sin(6 * lat_r))
    easting = _K0 * n * (a + a3 / 6 * (1 - tn2 + cc) + a5 / 120 * (5 - 18 * tn2 + tn4 + 72 * cc - 58 * _E_P2)) + 500000.0
    northing = _K0 * (m + n * tn * (a2 / 2 + a4 / 24 * (5 - tn2 + 9 * cc + 4 * cc * cc) + a6 / 720 * (61 - 58 * tn2 + tn4 + 600 * cc - 330 * _E_P2)))
    south = lat < 0
    if south:
        northing += 10_000_000.0
    return {"easting": float(easting), "northing": float(northing), "zone": zone, "band": band, "hemisphere": "S" if south else "N", "epsg": (32700 if south else 32600) + zone}


def azimuth_deg(dx: float, dy: float) -> float:
    """Bearing of the vector (east, north): degrees clockwise from north, 0..360."""
    return float(np.mod(np.degrees(np.arctan2(dx, dy)), 360.0))


def dms(deg: float) -> str:
    """Degrees to D°MM'SS\"."""
    d = int(deg)
    m_f = (deg - d) * 60
    m = int(m_f)
    s = round((m_f - m) * 60)
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f"{d}°{m:02d}'{s:02d}\""
