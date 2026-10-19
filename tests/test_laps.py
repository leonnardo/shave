import math

import pytest

from aim_csv import EARTH_RADIUS_M, write_circle_csv
from shave.aim import read_session
from shave.laps import LapStatus, check_lap, split_laps
from shave.tracks import FinishLine, Track

CENTER = (-23.5, -46.9)
CIRCUMFERENCE_M = 100.0
SPEED_MS = 20.0  # one 100 m lap every 5 s
START_ANGLE = -0.5  # rad before the line, so the first crossing is at a known time

# The circle's southernmost point, crossed heading east when driving counterclockwise.
_R = CIRCUMFERENCE_M / (2 * math.pi)
LINE = FinishLine(lat_deg=CENTER[0] - _R / (math.pi / 180 * EARTH_RADIUS_M),
                  lon_deg=CENTER[1], heading_deg=90.0)
TRACK = Track(id="t", name="Test", expected_length_m=100, length_tolerance_m=10, finish_line=LINE)


def drive(tmp_path, *, track=TRACK, circumference_m=CIRCUMFERENCE_M, duration_s=12.0, **kwargs):
    path = write_circle_csv(
        tmp_path / "s.csv", center=CENTER, circumference_m=circumference_m, speed_ms=SPEED_MS,
        start_angle_rad=START_ANGLE, duration_s=duration_s, **kwargs,
    )
    return split_laps(read_session(path), track)


def first_crossing_s(circumference_m=CIRCUMFERENCE_M):
    return -START_ANGLE * circumference_m / (2 * math.pi) / SPEED_MS


def test_cuts_laps_where_the_track_crosses_the_line(tmp_path):
    laps = drive(tmp_path)

    t0 = first_crossing_s()
    assert [lap.number for lap in laps] == [1, 2, 3, 4]
    assert [lap.complete for lap in laps] == [False, True, True, False]
    assert laps[1].start_s == pytest.approx(t0, abs=1e-3)
    assert laps[1].time_s == pytest.approx(5.0, abs=1e-3)
    assert laps[1].length_m == pytest.approx(100, abs=0.1)


def test_lap_distance_restarts_at_our_line_not_the_loggers(tmp_path):
    lap = drive(tmp_path)[1]

    distance = lap.data["lap_distance_m"].to_list()
    assert 0 <= distance[0] < 1.0
    assert distance[-1] == pytest.approx(100, abs=1.0)


def test_ignores_crossings_against_the_direction_of_travel(tmp_path):
    laps = drive(tmp_path, clockwise=True)

    assert [lap.complete for lap in laps] == [False]


def test_ignores_passes_outside_the_line_width(tmp_path):
    k = math.pi / 180 * EARTH_RADIUS_M
    far = FinishLine(lat_deg=LINE.lat_deg, lon_deg=LINE.lon_deg + 30 / (k * math.cos(math.radians(LINE.lat_deg))),
                     heading_deg=90.0)
    track = Track(id="t", name="Test", expected_length_m=100, length_tolerance_m=10, finish_line=far)

    assert [lap.complete for lap in drive(tmp_path, track=track)] == [False]


def test_complete_lap_of_expected_length_with_good_gps_is_valid(tmp_path):
    laps = drive(tmp_path)

    assert [check_lap(lap, TRACK).status for lap in laps] == [
        LapStatus.PARTIAL, LapStatus.VALID, LapStatus.VALID, LapStatus.PARTIAL,
    ]


def test_lap_outside_length_tolerance_is_bad_length(tmp_path):
    check = check_lap(drive(tmp_path, circumference_m=85)[1], TRACK)

    assert check.status == LapStatus.BAD_LENGTH
    assert "-15 m" in check.reason


@pytest.mark.parametrize("gps", [{"gps_accuracy_mm": 3000}, {"gps_sats": 4}])
def test_lap_with_untrusted_gps_is_bad_gps(tmp_path, gps):
    assert check_lap(drive(tmp_path, **gps)[1], TRACK).status == LapStatus.BAD_GPS
