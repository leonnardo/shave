"""Lap splitting and lap validity.

Laps are cut where the GPS track crosses the layout's finish line (from the
track file), not at the logger's beacons. The logger's line depends on how it
was set up that day and has been wrong (Aldeia 2026-08-29); a fixed line per
layout keeps laps comparable across sessions. The crossing instant is
interpolated between the two samples on either side of the line.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from shave.aim import Session
from shave.tracks import FinishLine, Track

# A sample with accuracy at or below this (mm) and at least this many
# satellites is trusted. Defaults; callers may override.
MAX_GPS_ACCURACY_MM = 1500.0
MIN_GPS_SATS = 8

# A step longer than this between consecutive samples is a GPS jump, not
# driving (a kart covers ~1.5 m per sample at 20 Hz and 100 km/h); a jump
# across the line is not a crossing.
MAX_STEP_M = 5.0

# A crossing closer than this fraction of the layout length to the previous
# one is ignored (e.g. a spin right after the line).
MIN_LAP_FRACTION = 0.5

EARTH_RADIUS_M = 6_371_008.8


class LapStatus(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"  # before the first or after the last line crossing
    BAD_LENGTH = "bad_length"
    BAD_GPS = "bad_gps"


@dataclass(frozen=True)
class Lap:
    number: int  # 1-based, counting the out-lap
    start_s: float
    end_s: float
    length_m: float
    complete: bool  # starts and ends on a line crossing
    # Session rows inside the lap; lap_distance_m is recomputed from our own
    # line, so it starts at ~0 m on a complete lap whatever the logger did.
    data: pl.DataFrame

    @property
    def time_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class LapCheck:
    status: LapStatus
    reason: str


@dataclass(frozen=True)
class Crossing:
    row: int  # first sample past the line
    time_s: float
    distance_m: float


def find_crossings(data: pl.DataFrame, line: FinishLine, min_spacing_m: float) -> list[Crossing]:
    time = data["time_s"].to_list()
    distance = data["distance_m"].to_list()
    along, across = _line_coordinates(data["lat_deg"].to_list(), data["lon_deg"].to_list(), line)

    crossings: list[Crossing] = []
    for i in range(1, len(time)):
        a0, a1 = along[i - 1], along[i]
        if not (a0 < 0 <= a1) or a1 - a0 > MAX_STEP_M:
            continue
        f = -a0 / (a1 - a0)
        if abs(_lerp(across[i - 1], across[i], f)) > line.half_width_m:
            continue
        crossing = Crossing(
            row=i,
            time_s=_lerp(time[i - 1], time[i], f),
            distance_m=_lerp(distance[i - 1], distance[i], f),
        )
        if crossings and crossing.distance_m - crossings[-1].distance_m < min_spacing_m:
            continue
        crossings.append(crossing)
    return crossings


def split_laps(session: Session, track: Track) -> list[Lap]:
    data = session.data
    time = data["time_s"].to_list()
    distance = data["distance_m"].to_list()
    crossings = find_crossings(
        data, track.finish_line, min_spacing_m=MIN_LAP_FRACTION * track.expected_length_m
    )

    start = Crossing(row=0, time_s=time[0], distance_m=distance[0])
    end = Crossing(row=len(time), time_s=time[-1], distance_m=distance[-1])
    bounds = [start, *crossings, end]

    laps = []
    for n, (a, b) in enumerate(zip(bounds, bounds[1:]), start=1):
        lap_data = data.slice(a.row, b.row - a.row).with_columns(
            (pl.col("distance_m") - a.distance_m).alias("lap_distance_m")
        )
        laps.append(Lap(
            number=n,
            start_s=a.time_s,
            end_s=b.time_s,
            length_m=b.distance_m - a.distance_m,
            complete=a is not start and b is not end,
            data=lap_data,
        ))
    return laps


def check_lap(
    lap: Lap,
    track: Track,
    max_gps_accuracy_mm: float = MAX_GPS_ACCURACY_MM,
    min_gps_sats: int = MIN_GPS_SATS,
) -> LapCheck:
    """First failing rule wins: partial, then length, then GPS.

    Slow laps (traffic, yellow flag, mistakes) are valid here; choosing which
    laps represent the driver is the analysis' job, not validity's.
    """
    if not lap.complete:
        return LapCheck(LapStatus.PARTIAL, "does not start and end on a line crossing")

    deviation = lap.length_m - track.expected_length_m
    if abs(deviation) > track.length_tolerance_m:
        return LapCheck(
            LapStatus.BAD_LENGTH,
            f"{lap.length_m:.0f} m is {deviation:+.0f} m from expected "
            f"{track.expected_length_m:.0f} ± {track.length_tolerance_m:.0f} m",
        )

    worst_accuracy = lap.data["gps_accuracy_mm"].max()
    fewest_sats = lap.data["gps_sats"].min()
    if worst_accuracy > max_gps_accuracy_mm or fewest_sats < min_gps_sats:
        return LapCheck(
            LapStatus.BAD_GPS,
            f"worst accuracy {worst_accuracy:.0f} mm (max {max_gps_accuracy_mm:.0f}), "
            f"fewest satellites {fewest_sats:.0f} (min {min_gps_sats})",
        )

    return LapCheck(LapStatus.VALID, "")


def _line_coordinates(
    lat_deg: list[float], lon_deg: list[float], line: FinishLine
) -> tuple[list[float], list[float]]:
    """Meters along the direction of travel and across it, from the line point.

    Equirectangular projection: exact enough over a kart track.
    """
    k = math.pi / 180 * EARTH_RADIUS_M
    cos_lat = math.cos(math.radians(line.lat_deg))
    ux, uy = math.sin(math.radians(line.heading_deg)), math.cos(math.radians(line.heading_deg))
    along, across = [], []
    for lat, lon in zip(lat_deg, lon_deg):
        x = (lon - line.lon_deg) * cos_lat * k
        y = (lat - line.lat_deg) * k
        along.append(x * ux + y * uy)
        across.append(y * ux - x * uy)
    return along, across


def _lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f
