"""Segment times, and a first proposal of segments for a new layout.

A segment is timed from the instant the lap reaches its start station to the
instant it reaches the next segment's start, interpolated between samples.
The first segment starts at the lap's own start and the last ends at the
lap's end, so on a lap cut from an aligned session the segment times add up
to the lap time exactly.
"""

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from shave.laps import Lap
from shave.reference import Projection, ReferenceLine
from shave.tracks import Segment

# Proposal: a corner is a run of curvature in one direction tighter than
# this radius, turning at least this much in total. Mild kinks (a few degrees)
# are left out on purpose; add them by hand if the driver counts them.
CORNER_MAX_RADIUS_M = 80.0
CORNER_MIN_TURN_DEG = 20.0
CURVATURE_SMOOTH_M = 15
# Same-direction runs closer than this are one corner.
CORNER_MERGE_GAP_M = 10
# A corner's segment runs this far past the end of its curvature (the exit),
# and when a straight precedes it, starts this far before (the braking zone).
EXIT_M = 25.0
APPROACH_M = 25.0
# A gap between corners longer than this becomes a straight of its own.
STRAIGHT_MIN_M = 60.0
# GPS longitudinal acceleration: below BRAKING_G the kart is braking (or
# lifting hard); braking starts where it last was above BRAKE_ONSET_G.
BRAKING_G = -0.15
BRAKE_ONSET_G = -0.05
BRAKE_SEARCH_M = 40.0


def segment_times(lap: Lap, projection: Projection, segments: Sequence[Segment]) -> list[float]:
    """Seconds spent in each segment on one complete lap.

    `projection` is the lap's samples projected onto the reference line, in
    order (see reference.project_lap).
    """
    time = lap.data["time_s"].to_numpy()
    station = np.maximum.accumulate(projection.station_m)
    keep = np.concatenate([[True], np.diff(station) > 0])
    for s in segments[1:]:
        # np.interp would clamp a start outside the lap's samples to the first
        # or last sample's time, giving a plausible but wrong segment time.
        if not station[0] < s.start_m < station[-1]:
            raise ValueError(
                f"segment {s.id} starts at {s.start_m:.0f} m, outside lap {lap.number}'s "
                f"stations {station[0]:.1f}-{station[-1]:.1f} m"
            )
    inner = [np.interp(s.start_m, station[keep], time[keep]) for s in segments[1:]]
    bounds = [lap.start_s, *inner, lap.end_s]
    return [float(b - a) for a, b in zip(bounds, bounds[1:])]


@dataclass(frozen=True)
class ProposedCorner:
    start_m: float
    end_m: float
    apex_m: float
    direction: str  # "dir" or "esq"
    turn_deg: float


def detect_corners(line: ReferenceLine) -> list[ProposedCorner]:
    east, north = line.east_m, line.north_m
    dx, dy = np.roll(east, -1) - east, np.roll(north, -1) - north
    heading = np.arctan2(dx, dy)
    turn = np.diff(np.unwrap(np.concatenate([heading, heading[:1]])))  # rad per vertex, + = right
    curvature = _circular_mean(turn, CURVATURE_SMOOTH_M)
    sign = np.where(curvature > 1 / CORNER_MAX_RADIUS_M, 1,
                    np.where(curvature < -1 / CORNER_MAX_RADIUS_M, -1, 0))

    runs: list[list[int]] = []
    for i, s in enumerate(sign):
        if s == 0:
            continue
        if runs and runs[-1][2] == s and i - runs[-1][1] <= CORNER_MERGE_GAP_M:
            runs[-1][1] = i
        else:
            runs.append([i, i, int(s)])

    corners = []
    for a, b, s in runs:
        total = float(np.degrees(turn[a:b + 1].sum()))
        if abs(total) < CORNER_MIN_TURN_DEG:
            continue
        apex = a + int(np.argmax(np.abs(curvature[a:b + 1])))
        corners.append(ProposedCorner(float(a), float(b), float(apex), "dir" if s > 0 else "esq", total))
    return corners


def propose_segments(line: ReferenceLine, corners: Sequence[ProposedCorner]) -> list[Segment]:
    """A first draft of a layout's segments, to check against how the driver
    counts corners.

    Corners are C1..Cn in order from the line. Corner n's segment starts
    APPROACH_M before its curvature, but never inside the previous corner's
    curvature (at the earliest, halfway between the two corners' curvature),
    so every corner segment holds exactly its own apex. When the
    stretch from one corner's exit (EXIT_M past its curvature) to the next
    corner's start is longer than STRAIGHT_MIN_M, it becomes a straight R1..Rk.
    The stretch after the line is R0 and the one before it RP. Run
    `move_out_of_braking` on the result: APPROACH_M is a guess at where
    braking starts.
    """
    if not corners:
        raise ValueError("no corners found")
    length = line.length_m
    if corners[0].start_m < 1 or corners[-1].end_m > length - 2:
        raise ValueError("a corner crosses the finish line; draw this layout's segments by hand")

    segments = [Segment("R0", 0.0)]
    straights = 0
    for n, corner in enumerate(corners, start=1):
        previous = corners[n - 2] if n > 1 else None
        earliest = (previous.end_m + corner.start_m) / 2 if previous else 1.0
        start = min(max(corner.start_m - APPROACH_M, earliest), corner.apex_m - 1)
        if previous and start - (previous.end_m + EXIT_M) > STRAIGHT_MIN_M:
            straights += 1
            segments.append(Segment(f"R{straights}", previous.end_m + EXIT_M))
        segments.append(Segment(f"C{n}", start))
    last_exit = corners[-1].end_m + EXIT_M
    if length - last_exit > STRAIGHT_MIN_M:
        segments.append(Segment("RP", last_exit))
    return segments


def station_profile(values_by_lap: Sequence[tuple[np.ndarray, np.ndarray]], length_m: float,
                    step_m: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Median of a channel across laps, station by station.

    `values_by_lap` holds (station_m, value) per lap, stations increasing.
    """
    grid = np.arange(0.0, length_m, step_m)
    per_lap = []
    for station, value in values_by_lap:
        station = np.maximum.accumulate(station)
        keep = np.concatenate([[True], np.diff(station) > 0])
        per_lap.append(np.interp(grid, station[keep], value[keep], left=np.nan, right=np.nan))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # stations no lap reached stay NaN
        return grid, np.nanmedian(per_lap, axis=0)


def move_out_of_braking(segments: Sequence[Segment], grid_m: np.ndarray,
                        accel_long_g: np.ndarray) -> list[Segment]:
    """Moves each boundary that sits in a braking zone back to where braking starts.

    A boundary is in a braking zone when the median longitudinal acceleration
    there is below BRAKING_G; it moves back to the last station where it was
    above BRAKE_ONSET_G, at most BRAKE_SEARCH_M back and never onto the
    previous boundary. A corner's segment then holds its whole braking zone.
    """
    moved = [segments[0]]
    for segment in segments[1:]:
        start = segment.start_m
        if np.interp(start, grid_m, accel_long_g) < BRAKING_G:
            back = (grid_m <= start) & (grid_m >= start - BRAKE_SEARCH_M) & (accel_long_g >= BRAKE_ONSET_G)
            if back.any():
                start = float(grid_m[back].max())
        moved.append(Segment(segment.id, max(start, moved[-1].start_m + 1)))
    return moved


def _circular_mean(values: np.ndarray, window: int) -> np.ndarray:
    pad = window // 2
    wrapped = np.concatenate([values[-pad:], values, values[:pad]])
    return np.convolve(wrapped, np.ones(window) / window, mode="valid")
