"""Reader for AiM Race Studio CSV exports.

Only parsing lives here: no interpretation of laps, corners or driving.
Channel names become snake_case with the unit as suffix, so a value's unit
is never ambiguous downstream.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

# AiM channel -> (our name, multiplier to the unit in our name)
CHANNELS: dict[str, tuple[str, float]] = {
    "Time": ("time_s", 1.0),
    "Distance": ("distance_m", 1000.0),  # exported in km
    "Distance Lap": ("lap_distance_m", 1.0),
    "GPS Speed": ("speed_kmh", 1.0),
    "GPS Nsat": ("gps_sats", 1.0),
    "GPS PosAccuracy": ("gps_accuracy_mm", 1.0),
    "GPS Latitude": ("lat_deg", 1.0),
    "GPS Longitude": ("lon_deg", 1.0),
    "GPS Heading": ("heading_deg", 1.0),
    "GPS Altitude": ("altitude_m", 1.0),
    "InlineAcc": ("accel_long_g", 1.0),
    "LateralAcc": ("accel_lat_g", 1.0),
    "YawRate": ("yaw_rate_dps", 1.0),
    "GPS Lateral G": ("gps_accel_lat_g", 1.0),
    "GPS Longitudinal G": ("gps_accel_long_g", 1.0),
}

# Known channels we deliberately drop. "(sim)" channels are estimated by
# Race Studio, not measured: the kart has no steering or pedal sensors.
IGNORED: frozenset[str] = frozenset({
    "GPS SpdAccuracy", "Master Clk", "Predictive Time", "Best Run Diff",
    "Best Today Diff", "Prev Lap Diff", "Ref Lap Diff", "VerticalAcc",
    "RollRate", "PitchRate", "Internal Battery", "External Voltage",
    "Distance Lap Int", "StrtRec",
    "Steering Angle (sim)", "Throttle (sim)", "Brake (sim)",
})


@dataclass(frozen=True)
class Session:
    path: Path
    venue: str
    user: str
    comment: str
    started_at: datetime
    sample_rate_hz: int
    duration_s: float
    beacon_markers_s: tuple[float, ...]
    data: pl.DataFrame


def read_session(path: Path) -> Session:
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    if not rows or rows[0][:2] != ["Format", "AIM CSV File"]:
        raise ValueError(f"{path}: not an AiM CSV export")

    # The metadata block also has a "Time" row (session start clock time);
    # the column header is the first "Time" row with more than one value.
    columns_at = next(i for i, r in enumerate(rows) if len(r) > 2 and r[0] == "Time")
    meta = {r[0]: r[1:] for r in rows[:columns_at] if r}
    columns = rows[columns_at]

    unknown = [c for c in columns if c not in CHANNELS and c not in IGNORED]
    if unknown:
        raise ValueError(f"{path}: unknown channels {unknown}; map or ignore them in aim.py")

    # Below the column names: a repeated header, units, channel indexes and a
    # blank line. Data starts after that blank line.
    data_at = next(i for i in range(columns_at + 1, len(rows)) if not rows[i]) + 1
    raw = pl.DataFrame(
        [r for r in rows[data_at:] if r], schema=columns, orient="row"
    )
    data = raw.select(
        (pl.col(src).cast(pl.Float64) * scale).alias(dst)
        for src, (dst, scale) in CHANNELS.items()
        if src in columns
    )

    return Session(
        path=path,
        venue=meta["Venue"][0],
        user=meta["User"][0],
        comment=meta["Comment"][0],
        started_at=datetime.strptime(f"{meta['Date'][0]} {meta['Time'][0]}", "%m/%d/%y %H:%M:%S"),
        sample_rate_hz=int(meta["Sample Rate"][0]),
        duration_s=float(meta["Duration"][0]),
        beacon_markers_s=_parse_markers(meta.get("Beacon Markers", [""])),
        data=data,
    )


def _parse_markers(values: list[str]) -> tuple[float, ...]:
    # Exported as one quoted, comma-separated string.
    joined = ",".join(values)
    return tuple(float(v) for v in joined.split(",") if v.strip())
