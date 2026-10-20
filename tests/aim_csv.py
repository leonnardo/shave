"""Builds small synthetic AiM Race Studio CSV exports for tests."""

import math
from collections.abc import Callable
from pathlib import Path

from shave.aim import CHANNELS

SIM = "Brake (sim)"

EARTH_RADIUS_M = 6_371_008.8


def write_aim_csv(
    path: Path,
    lap_distance_m: list[float],
    beacons_s: list[float],
    *,
    lat_deg: list[float] | None = None,
    lon_deg: list[float] | None = None,
    distance_m: list[float] | None = None,
    extra_channels: tuple[str, ...] = (SIM,),
    gps_accuracy_mm: float = 500.0,
    gps_sats: float = 14.0,
    sample_rate_hz: int = 20,
) -> Path:
    dt = 1 / sample_rate_hz
    columns = list(CHANNELS) + list(extra_channels)
    n = len(lap_distance_m)

    def row(i: int) -> list[str]:
        values = {
            "Time": i * dt,
            "Distance": (distance_m[i] if distance_m else i) / 1000,  # km
            "Distance Lap": lap_distance_m[i],
            "GPS Latitude": lat_deg[i] if lat_deg else 0.0,
            "GPS Longitude": lon_deg[i] if lon_deg else 0.0,
            "GPS PosAccuracy": gps_accuracy_mm,
            "GPS Nsat": gps_sats,
        }
        return [f"{values.get(c, 0.0):.9f}" for c in columns]

    def line(cells: list[str]) -> str:
        return ",".join(f'"{c}"' for c in cells)

    header = [
        ["Format", "AIM CSV File"],
        ["Venue", "Test"],
        ["Vehicle", ""],
        ["User", "Driver"],
        ["Data Source", "AIM Data Logger"],
        ["Comment", ""],
        ["Date", "10/11/26"],
        ["Time", "09:28:29"],
        ["Sample Rate", str(sample_rate_hz)],
        ["Duration", f"{(n - 1) * dt:.3f}"],
        ["Segment", "Session"],
        ["Beacon Markers", ", ".join(f"{b:.3f}" for b in beacons_s)],
        ["Segment Times", "0:00.000"],
    ]
    lines = [line(r) for r in header] + [
        "",
        line(columns),
        line(columns),
        line(["unit"] * len(columns)),
        line([""] + [str(i) for i in range(1, len(columns))]),
        "",
    ] + [line(row(i)) for i in range(n)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_circle_csv(
    path: Path,
    *,
    center: tuple[float, float],
    circumference_m: float,
    speed_ms: float,
    start_angle_rad: float,
    duration_s: float,
    clockwise: bool = False,
    radial_offset_m: Callable[[float], float] = lambda t: 0.0,
    shift_m: tuple[float, float] = (0.0, 0.0),
    sample_rate_hz: int = 20,
    **kwargs,
) -> Path:
    """A kart driving a circle at constant speed.

    Angle 0 is the southernmost point; counterclockwise travel heads east
    there, clockwise heads west. `radial_offset_m(t)` moves the kart outwards
    of the circle at time t; `shift_m` (east, north) shifts every position, as
    a GPS offset would.
    """
    r = circumference_m / (2 * math.pi)
    k = math.pi / 180 * EARTH_RADIUS_M
    cos_lat = math.cos(math.radians(center[0]))
    sign = -1 if clockwise else 1
    n = int(duration_s * sample_rate_hz) + 1
    lat, lon, dist = [], [], []
    for i in range(n):
        t = i / sample_rate_hz
        theta = start_angle_rad + sign * speed_ms * t / r
        radius = r + radial_offset_m(t)
        lat.append(center[0] + (-radius * math.cos(theta) + shift_m[1]) / k)
        lon.append(center[1] + (radius * math.sin(theta) + shift_m[0]) / (k * cos_lat))
        dist.append(speed_ms * t)
    return write_aim_csv(
        path, [0.0] * n, beacons_s=[], lat_deg=lat, lon_deg=lon, distance_m=dist,
        sample_rate_hz=sample_rate_hz, **kwargs,
    )
