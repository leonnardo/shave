"""Segment times, and a first proposal of segments for a new layout.

A segment is timed from the instant the lap reaches its start station to the
instant it reaches the next segment's start, interpolated between samples.
The first segment starts at the lap's own start and the last ends at the
lap's end, so on a lap cut from an aligned session the segment times add up
to the lap time exactly.
"""

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


def segment_times(lap: Lap, projection: Projection, segments: Sequence[Segment]) -> list[float]:
    """Seconds spent in each segment on one complete lap.

    `projection` is the lap's samples projected onto the reference line, in
    order (see reference.project_lap).
    """
    time = lap.data["time_s"].to_numpy()
    station = np.maximum.accumulate(projection.station_m)
    keep = np.concatenate([[True], np.diff(station) > 0])
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

    Corners are C1..Cn in order from the line. A corner's segment ends EXIT_M
    past its curvature; the next one starts there, so a corner includes its
    braking zone. When the gap to the next corner is longer than
    STRAIGHT_MIN_M, it becomes a straight R1..Rk and the next corner starts
    APPROACH_M before its curvature. The stretch after the line is R0 and the
    one before it RP.
    """
    if not corners:
        raise ValueError("no corners found")
    segments = [Segment("R0", 0.0)]
    exit_m = None
    for n, corner in enumerate(corners, start=1):
        approach = max(corner.start_m - APPROACH_M, 1.0)
        if exit_m is None or approach - exit_m > STRAIGHT_MIN_M:
            if exit_m is not None:
                segments.append(Segment(f"R{sum(s.id.startswith('R') for s in segments)}", exit_m))
            start = approach
        else:
            start = exit_m
        segments.append(Segment(f"C{n}", max(start, segments[-1].start_m + 1)))
        exit_m = corner.end_m + EXIT_M
    if exit_m < line.length_m - 1:
        segments.append(Segment("RP", exit_m))
    return segments


def _circular_mean(values: np.ndarray, window: int) -> np.ndarray:
    pad = window // 2
    wrapped = np.concatenate([values[-pad:], values, values[:pad]])
    return np.convolve(wrapped, np.ones(window) / window, mode="valid")
