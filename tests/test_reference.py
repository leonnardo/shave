import math

import numpy as np
import pytest

from aim_csv import EARTH_RADIUS_M, write_circle_csv
from shave.aim import read_session
from shave.geo import to_local
from shave.laps import LapStatus, check_lap, split_laps
from shave.reference import (
    build_reference_line,
    estimate_shift,
    load_reference_line,
    project,
    save_reference_line,
)
from shave.tracks import FinishLine, Track

CENTER = (-23.5, -46.9)
CIRCUMFERENCE_M = 300.0
RADIUS_M = CIRCUMFERENCE_M / (2 * math.pi)
SPEED_MS = 20.0  # 15 s laps
LINE = FinishLine(lat_deg=CENTER[0] - RADIUS_M / (math.pi / 180 * EARTH_RADIUS_M),
                  lon_deg=CENTER[1], heading_deg=90.0)
TRACK = Track(id="circle", name="Circle", expected_length_m=CIRCUMFERENCE_M,
              length_tolerance_m=10, finish_line=LINE)


def wobble(t: float) -> float:
    """Each lap drives a slightly different line, ±0.5 m around the circle.

    2.4 cycles per 15 s lap: consecutive laps are 0.4 cycle out of phase, so
    across laps the offsets at any one point spread around zero.
    """
    return 0.5 * math.sin(2 * math.pi * t / 6.25)


def valid_laps(tmp_path, name="s.csv", **kwargs):
    path = write_circle_csv(
        tmp_path / name, center=CENTER, circumference_m=CIRCUMFERENCE_M, speed_ms=SPEED_MS,
        start_angle_rad=-0.3, duration_s=95.0, **kwargs,
    )
    laps = split_laps(read_session(path), TRACK)
    return [lap for lap in laps if check_lap(lap, TRACK).status == LapStatus.VALID]


def local(lat, lon):
    return to_local(lat, lon, LINE.lat_deg, LINE.lon_deg)


def test_line_follows_the_median_of_the_laps(tmp_path):
    line = build_reference_line(valid_laps(tmp_path, radial_offset_m=wobble), LINE)

    # circle centre in the local frame, which is centred on the finish line
    radius = np.hypot(line.east_m, line.north_m - RADIUS_M)
    assert line.length_m == pytest.approx(CIRCUMFERENCE_M, abs=1.0)
    assert np.abs(radius - RADIUS_M).max() < 0.3
    assert line.east_m[0] == pytest.approx(0, abs=0.1)  # starts on the finish line
    assert line.north_m[0] == pytest.approx(0, abs=0.3)


@pytest.mark.parametrize(("outwards_m", "expected_offset_m"), [(1.0, 1.0), (-1.0, -1.0)])
def test_projection_gives_station_from_the_line_and_offset_to_the_right(
    tmp_path, outwards_m, expected_offset_m
):
    line = build_reference_line(valid_laps(tmp_path), LINE)
    # counterclockwise travel: the centre is on the left, outside is on the right
    theta = 1.0
    r = RADIUS_M + outwards_m
    east, north = np.array([r * math.sin(theta)]), np.array([RADIUS_M - r * math.cos(theta)])

    p = project(line, east, north)

    assert p.station_m[0] == pytest.approx(RADIUS_M * theta, abs=0.5)
    assert p.offset_m[0] == pytest.approx(expected_offset_m, abs=0.1)


def test_estimates_a_sessions_gps_shift(tmp_path):
    line = build_reference_line(valid_laps(tmp_path, "ref.csv", radial_offset_m=wobble), LINE)
    shifted = valid_laps(tmp_path, "shifted.csv", radial_offset_m=wobble, shift_m=(1.0, -0.5))

    assert estimate_shift(line, shifted) == pytest.approx((-1.0, 0.5), abs=0.1)


def test_saved_line_loads_back(tmp_path):
    line = build_reference_line(valid_laps(tmp_path), LINE)
    save_reference_line(line, tmp_path / "circle.line.csv", "test")

    loaded = load_reference_line(TRACK, tracks_dir=tmp_path)

    assert np.abs(loaded.east_m - line.east_m).max() < 0.01
    assert np.abs(loaded.north_m - line.north_m).max() < 0.01
