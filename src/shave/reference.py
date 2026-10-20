"""Reference line: the ruler laps of one layout are measured against.

A closed polyline with a vertex every metre, starting on the finish line.
Projecting a sample onto it gives `station_m` (distance along the line from
the finish line) and `offset_m` (signed lateral distance, positive to the
right of the direction of travel). It is not a racing line: any stable line
works, and once corners are drawn on it, it must not change.
"""

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shave.geo import to_latlon, to_local
from shave.laps import Lap
from shave.tracks import TRACKS_DIR, FinishLine, Track

STEP_M = 1.0
BUILD_ITERATIONS = 3
SMOOTH_WINDOW_VERTICES = 5

# Projection follows the previous sample: it looks this many metres back and
# ahead on the line, so stretches that pass close to each other can't swap.
SEARCH_BACK_M = 5
SEARCH_AHEAD_M = 40
# Further than this from the windowed match means the search lost track (a
# GPS jump); it then searches the whole line.
MAX_SNAP_M = 15.0

# Samples further than this from the line don't count when estimating a
# session's GPS shift (offs, pit lane).
ALIGN_CLIP_M = 5.0
ALIGN_ITERATIONS = 3


@dataclass(frozen=True)
class ReferenceLine:
    origin_lat_deg: float  # local frame origin: the finish line point
    origin_lon_deg: float
    east_m: np.ndarray  # vertex 0 is on the finish line; the last segment closes back to it
    north_m: np.ndarray

    @property
    def length_m(self) -> float:
        dx = np.roll(self.east_m, -1) - self.east_m
        dy = np.roll(self.north_m, -1) - self.north_m
        return float(np.hypot(dx, dy).sum())


@dataclass(frozen=True)
class Projection:
    station_m: np.ndarray
    offset_m: np.ndarray
    segment: np.ndarray  # index of the line segment each sample projected onto


def project(line: ReferenceLine, east_m: np.ndarray, north_m: np.ndarray) -> Projection:
    """Projects consecutive samples (one lap or a whole session) onto the line."""
    ax, ay = line.east_m, line.north_m
    dx, dy = np.roll(ax, -1) - ax, np.roll(ay, -1) - ay
    seg_len = np.hypot(dx, dy)
    seg_station = np.concatenate([[0.0], np.cumsum(seg_len)[:-1]])
    n = len(ax)
    window = np.arange(-int(SEARCH_BACK_M / STEP_M), int(SEARCH_AHEAD_M / STEP_M) + 1)
    every = np.arange(n)

    station = np.empty(len(east_m))
    offset = np.empty(len(east_m))
    segment = np.empty(len(east_m), dtype=int)
    previous = None
    for k, (px, py) in enumerate(zip(east_m, north_m)):
        candidates = every if previous is None else (previous + window) % n
        i, t, dist = _nearest(candidates, px, py, ax, ay, dx, dy, seg_len)
        if previous is not None and dist > MAX_SNAP_M:
            i, t, dist = _nearest(every, px, py, ax, ay, dx, dy, seg_len)
        station[k] = seg_station[i] + t * seg_len[i]
        offset[k] = (dy[i] * (px - ax[i]) - dx[i] * (py - ay[i])) / seg_len[i]
        segment[k] = i
        previous = i
    return Projection(station, offset, segment)


def project_lap(line: ReferenceLine, east_m: np.ndarray, north_m: np.ndarray) -> Projection:
    """Like `project`, with station unwrapped to run continuously from ~0 m.

    A lap starts just past the finish line, but its first sample may land a
    few centimetres before vertex 0 (station ≈ length); unwrapping keeps the
    lap's station continuous instead of jumping by a whole lap.
    """
    p = project(line, east_m, north_m)
    length = line.length_m
    steps = np.diff(p.station_m)
    steps = np.where(steps < -length / 2, steps + length, steps)
    steps = np.where(steps > length / 2, steps - length, steps)
    station = np.concatenate([[p.station_m[0]], p.station_m[0] + np.cumsum(steps)])
    if station[0] > length / 2:
        station -= length
    return Projection(station, p.offset_m, p.segment)


def build_reference_line(laps: Sequence[Lap], finish_line: FinishLine) -> ReferenceLine:
    """Median of the given laps' positions, station by station."""
    if not laps:
        raise ValueError("need at least one lap to build a reference line")
    origin = (finish_line.lat_deg, finish_line.lon_deg)
    tracks = [to_local(lap.data["lat_deg"], lap.data["lon_deg"], *origin) for lap in laps]

    median_lap = sorted(range(len(laps)), key=lambda i: laps[i].time_s)[len(laps) // 2]
    east, north = _anchor_and_resample(*tracks[median_lap], finish_line)
    line = ReferenceLine(*origin, east, north)

    for _ in range(BUILD_ITERATIONS):
        grid = np.arange(0.0, line.length_m, STEP_M)
        per_lap_e, per_lap_n = [], []
        for e, nn in tracks:
            station = np.maximum.accumulate(project_lap(line, e, nn).station_m)
            keep = np.concatenate([[True], np.diff(station) > 0])
            per_lap_e.append(np.interp(grid, station[keep], e[keep], left=np.nan, right=np.nan))
            per_lap_n.append(np.interp(grid, station[keep], nn[keep], left=np.nan, right=np.nan))
        with warnings.catch_warnings():
            # The last metre before the line may have no samples; it gets filled.
            warnings.simplefilter("ignore", RuntimeWarning)
            east = _fill_and_smooth(np.nanmedian(per_lap_e, axis=0))
            north = _fill_and_smooth(np.nanmedian(per_lap_n, axis=0))
        line = ReferenceLine(*origin, *_anchor_and_resample(east, north, finish_line, closed=True))
    return line


def estimate_shift(line: ReferenceLine, laps: Sequence[Lap]) -> tuple[float, float]:
    """(east, north) metres to add to a session's positions to fit the line.

    Least squares on the lateral offsets: a lap is a closed loop, so offsets
    in every direction pin down a pure translation. Driving wider or tighter
    than the reference averages out over the lap only roughly, so expect
    ~0.2 m of error on top of the GPS shift being corrected.
    """
    origin = (line.origin_lat_deg, line.origin_lon_deg)
    tracks = [to_local(lap.data["lat_deg"], lap.data["lon_deg"], *origin) for lap in laps]
    dx = np.roll(line.east_m, -1) - line.east_m
    dy = np.roll(line.north_m, -1) - line.north_m
    seg_len = np.hypot(dx, dy)
    right = np.stack([dy / seg_len, -dx / seg_len], axis=1)

    shift = np.zeros(2)
    for _ in range(ALIGN_ITERATIONS):
        normals, offsets = [], []
        for e, n in tracks:
            p = project_lap(line, e + shift[0], n + shift[1])
            near = np.abs(p.offset_m) < ALIGN_CLIP_M
            normals.append(right[p.segment[near]])
            offsets.append(p.offset_m[near])
        normal = np.concatenate(normals)
        offset = np.concatenate(offsets)
        shift -= np.linalg.solve(normal.T @ normal, normal.T @ offset)
    return float(shift[0]), float(shift[1])


def save_reference_line(line: ReferenceLine, path: Path, provenance: str) -> None:
    lat, lon = to_latlon(line.east_m, line.north_m, line.origin_lat_deg, line.origin_lon_deg)
    station = np.arange(len(lat)) * STEP_M
    rows = [f"# {provenance}", "station_m,lat_deg,lon_deg"]
    rows += [f"{s:.0f},{a:.8f},{o:.8f}" for s, a, o in zip(station, lat, lon)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_reference_line(track: Track, tracks_dir: Path = TRACKS_DIR) -> ReferenceLine:
    path = tracks_dir / f"{track.id}.line.csv"
    if not path.exists():
        raise ValueError(f"no reference line for {track.id!r}; build it with `shave reference`")
    rows = [r for r in path.read_text(encoding="utf-8").splitlines() if r and not r.startswith("#")]
    lat, lon = np.array([[float(v) for v in r.split(",")[1:]] for r in rows[1:]]).T
    origin = (track.finish_line.lat_deg, track.finish_line.lon_deg)
    return ReferenceLine(*origin, *to_local(lat, lon, *origin))


def _nearest(candidates, px, py, ax, ay, dx, dy, seg_len):
    cx, cy, cdx, cdy, cl = ax[candidates], ay[candidates], dx[candidates], dy[candidates], seg_len[candidates]
    t = np.clip(((px - cx) * cdx + (py - cy) * cdy) / cl**2, 0.0, 1.0)
    dist = np.hypot(cx + t * cdx - px, cy + t * cdy - py)
    best = int(np.argmin(dist))
    return int(candidates[best]), float(t[best]), float(dist[best])


def _anchor_and_resample(
    east: np.ndarray, north: np.ndarray, finish_line: FinishLine, closed: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Resamples a track every STEP_M, starting where it crosses the finish line.

    `closed` treats the input as a loop; otherwise it is one lap from line to
    line and its last point is dropped if it sits on top of the first.
    """
    ux = math.sin(math.radians(finish_line.heading_deg))
    uy = math.cos(math.radians(finish_line.heading_deg))
    e, n = np.asarray(east, float), np.asarray(north, float)
    if not closed and math.hypot(e[-1] - e[0], n[-1] - n[0]) < STEP_M:
        e, n = e[:-1], n[:-1]

    along = e * ux + n * uy
    across = n * ux - e * uy
    nxt = np.roll(np.arange(len(e)), -1)
    crossing = np.flatnonzero(
        (along < 0) & (along[nxt] >= 0) & (np.abs(across) < finish_line.half_width_m)
    )
    if len(crossing) == 0:
        raise ValueError("track does not cross the finish line")
    i = int(crossing[0])
    f = -along[i] / (along[nxt[i]] - along[i])
    start = (e[i] + f * (e[nxt[i]] - e[i]), n[i] + f * (n[nxt[i]] - n[i]))

    order = np.concatenate([np.arange(i + 1, len(e)), np.arange(0, i + 1)])
    loop_e = np.concatenate([[start[0]], e[order], [start[0]]])
    loop_n = np.concatenate([[start[1]], n[order], [start[1]]])
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(loop_e), np.diff(loop_n)))])
    grid = np.arange(0.0, arc[-1] - STEP_M / 2, STEP_M)
    return np.interp(grid, arc, loop_e), np.interp(grid, arc, loop_n)


def _fill_and_smooth(values: np.ndarray) -> np.ndarray:
    """Fills gaps (stations no lap reached) and applies a circular moving average."""
    idx = np.arange(len(values))
    ok = ~np.isnan(values)
    filled = np.interp(idx, idx[ok], values[ok], period=len(values))
    pad = SMOOTH_WINDOW_VERTICES // 2
    wrapped = np.concatenate([filled[-pad:], filled, filled[:pad]])
    kernel = np.ones(SMOOTH_WINDOW_VERTICES) / SMOOTH_WINDOW_VERTICES
    return np.convolve(wrapped, kernel, mode="valid")
