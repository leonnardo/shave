"""Local metric coordinates around a point.

Equirectangular projection: over a kart track (~500 m across) its error is
far below GPS noise.
"""

import math

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
_M_PER_DEG = math.pi / 180 * EARTH_RADIUS_M


def to_local(lat_deg, lon_deg, lat0_deg: float, lon0_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """(east, north) in metres from (lat0, lon0)."""
    lat = np.asarray(lat_deg, dtype=float)
    lon = np.asarray(lon_deg, dtype=float)
    east = (lon - lon0_deg) * math.cos(math.radians(lat0_deg)) * _M_PER_DEG
    north = (lat - lat0_deg) * _M_PER_DEG
    return east, north


def to_latlon(east_m, north_m, lat0_deg: float, lon0_deg: float) -> tuple[np.ndarray, np.ndarray]:
    lat = lat0_deg + np.asarray(north_m, dtype=float) / _M_PER_DEG
    lon = lon0_deg + np.asarray(east_m, dtype=float) / (math.cos(math.radians(lat0_deg)) * _M_PER_DEG)
    return lat, lon
