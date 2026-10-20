"""Checks lap splitting against the real exports in data/raw (not versioned).

Skipped when the data isn't there.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from shave.aim import read_session
from shave.geo import to_local
from shave.laps import LapStatus, check_lap, split_laps
from shave.reference import estimate_shift, load_reference_line, project_lap
from shave.tracks import load_track

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

# session directory -> (layout, whether the logger's beacons sit on our line)
SESSIONS = {
    "aldeia/2026-08-29": ("aldeia-v1", False),  # logger line was wrong that day
    "aldeia/2026-10-11": ("aldeia-v3", True),
    "kgv/2026-10-01": ("kgv-7", True),
    "schincariol/2026-09-27": ("schincariol-3", True),  # beacons also mark sectors
}

# Best valid lap per file, as reported in the hand analyses of each day.
# Logger timing and our interpolation differ by a few milliseconds.
KNOWN_BEST_S = {
    "Leo Rabello_ADSv1_a_0180_027320.csv": 47.137,
    "Leo Rabello_ADSv1_a_0181_027320.csv": 46.731,
    "Leo Rabello_ADSv1_a_0182_027320.csv": 46.910,
    "Leo Rabello_ADSv1_a_0183_027320.csv": 46.680,
    "Leo Rabello_ADSv1_a_0185_027320.csv": 48.517,
    "ADSv3_a_0207_027320.csv": 51.762,
    "ADSv3_a_0208_027320.csv": 51.526,
    "ADSv3_a_0209_027320.csv": 50.571,
    "ADSv3_a_0210_027320.csv": 51.943,
    "Leo Rabello_Schincariol3_a_0202_027320.csv": 67.917,
}
TIMING_TOLERANCE_S = 0.006

FILES = [
    pytest.param(path, *spec, id=path.name)
    for directory, spec in SESSIONS.items()
    for path in sorted((RAW / directory).glob("*.csv"))
]

pytestmark = pytest.mark.skipif(not FILES, reason="no raw data in data/raw")


@pytest.mark.parametrize(("path", "track_id", "beacons_on_line"), FILES)
def test_crossings_agree_with_logger_beacons_when_its_line_was_right(
    path, track_id, beacons_on_line
):
    if not beacons_on_line:
        pytest.skip("logger line differs from ours")
    session = read_session(path)
    crossings = [lap.start_s for lap in split_laps(session, load_track(track_id))[1:]]

    # The logger misses a crossing right after recording starts; every other
    # crossing it marked, and we find it too.
    matched = [c for c in crossings
               if min(abs(c - b) for b in session.beacon_markers_s) <= TIMING_TOLERANCE_S]
    assert len(matched) >= len(crossings) - 1


@pytest.mark.parametrize(("path", "track_id", "beacons_on_line"), FILES)
def test_complete_laps_are_close_to_the_layout_length(path, track_id, beacons_on_line):
    track = load_track(track_id)
    lengths = [lap.length_m for lap in split_laps(read_session(path), track) if lap.complete]

    assert lengths
    assert all(abs(length / track.expected_length_m - 1) < 0.05 for length in lengths)


@pytest.mark.parametrize(("path", "track_id", "beacons_on_line"), FILES)
def test_best_lap_matches_the_hand_analysis(path, track_id, beacons_on_line):
    if path.name not in KNOWN_BEST_S:
        pytest.skip("no reference best lap")
    track = load_track(track_id)
    valid = [lap.time_s for lap in split_laps(read_session(path), track)
             if check_lap(lap, track).status == LapStatus.VALID]

    assert min(valid) == pytest.approx(KNOWN_BEST_S[path.name], abs=TIMING_TOLERANCE_S)


# Slow corners: apex distance from the line in the hand analyses. Minimum
# speed comes at or after the apex (up to ~15 m later in Schincariol's C10
# hairpin), so it locates the corner, not the apex.
SLOW_CORNERS_M = {
    "aldeia-v1": {"C4": 450, "C7": 674},
    "aldeia-v3": {"C5": 350, "C6": 481},
    "schincariol-3": {"C4": 535, "C10": 1090},
}
CORNER_TOLERANCE_M = 20


def _projected_laps(path, track_id):
    track = load_track(track_id)
    line = load_reference_line(track)
    laps = [lap for lap in split_laps(read_session(path), track)
            if check_lap(lap, track).status == LapStatus.VALID]
    shift = estimate_shift(line, laps)
    projected = []
    for lap in laps:
        east, north = to_local(lap.data["lat_deg"], lap.data["lon_deg"],
                               track.finish_line.lat_deg, track.finish_line.lon_deg)
        projected.append((lap, project_lap(line, east + shift[0], north + shift[1])))
    return shift, projected


@pytest.mark.parametrize(("path", "track_id", "beacons_on_line"), FILES)
def test_every_valid_lap_projects_cleanly_onto_the_reference_line(
    path, track_id, beacons_on_line
):
    shift, projected = _projected_laps(path, track_id)

    length = load_reference_line(load_track(track_id)).length_m
    assert math.hypot(*shift) < 2.5  # GPS shift between sessions, seen up to ~2 m
    for _, p in projected:
        # A sample snapped to a nearby stretch shows up as a jump: never
        # backwards, never more than a sample's travel (~1.5 m) forwards.
        steps = np.diff(p.station_m)
        assert steps.min() > -0.5
        assert steps.max() < 3.0
        # A lap runs line to line: its stations span the whole reference line.
        assert p.station_m[-1] - p.station_m[0] == pytest.approx(length, abs=3.0)
        # Traffic and mistakes take a lap up to ~9 m wide for a few dozen
        # metres; beyond 12 m the sample snapped to the wrong stretch.
        assert np.abs(p.offset_m).max() < 12
    # A different driver's line differs too: S2 at Aldeia 2026-10-11 runs
    # ~3 m (p95) from a reference built on S3, consistently on every lap.
    typical = np.median([np.percentile(np.abs(p.offset_m), 95) for _, p in projected])
    assert typical < 4.0


@pytest.mark.parametrize(("path", "track_id", "beacons_on_line"), FILES)
def test_slow_corners_sit_where_the_hand_analyses_put_them(path, track_id, beacons_on_line):
    if track_id not in SLOW_CORNERS_M:
        pytest.skip("no hand analysis for this layout")
    _, projected = _projected_laps(path, track_id)

    for corner, expected_m in SLOW_CORNERS_M[track_id].items():
        minima = []
        for lap, p in projected:
            near = np.abs(p.station_m - expected_m) < 30
            speed = lap.data["speed_kmh"].to_numpy()
            minima.append(p.station_m[near][np.argmin(speed[near])])
        assert np.median(minima) == pytest.approx(expected_m, abs=CORNER_TOLERANCE_M), corner
