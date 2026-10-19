"""Checks lap splitting against the real exports in data/raw (not versioned).

Skipped when the data isn't there.
"""

from pathlib import Path

import pytest

from shave.aim import read_session
from shave.laps import LapStatus, check_lap, split_laps
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
