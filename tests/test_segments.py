import math

import pytest

from aim_csv import EARTH_RADIUS_M, write_circle_csv
from shave.aim import read_session
from shave.geo import to_local
from shave.laps import LapStatus, check_lap, split_laps
from shave.reference import build_reference_line, load_reference_line, project_lap
from shave.segments import detect_corners, segment_times
from shave.tracks import FinishLine, Segment, Track, load_track

CENTER = (-23.5, -46.9)
CIRCUMFERENCE_M = 300.0
RADIUS_M = CIRCUMFERENCE_M / (2 * math.pi)
SPEED_MS = 20.0
LINE = FinishLine(lat_deg=CENTER[0] - RADIUS_M / (math.pi / 180 * EARTH_RADIUS_M),
                  lon_deg=CENTER[1], heading_deg=90.0)
SEGMENTS = (Segment("A", 0.0), Segment("B", 60.0), Segment("C", 210.0))
TRACK = Track(id="circle", name="Circle", expected_length_m=CIRCUMFERENCE_M,
              length_tolerance_m=10, finish_line=LINE, segments=SEGMENTS)


def test_segment_times_follow_distance_and_add_up_to_the_lap(tmp_path):
    path = write_circle_csv(tmp_path / "s.csv", center=CENTER, circumference_m=CIRCUMFERENCE_M,
                            speed_ms=SPEED_MS, start_angle_rad=-0.3, duration_s=50.0)
    laps = [lap for lap in split_laps(read_session(path), TRACK)
            if check_lap(lap, TRACK).status == LapStatus.VALID]
    line = build_reference_line(laps, LINE)

    for lap in laps:
        east, north = to_local(lap.data["lat_deg"], lap.data["lon_deg"], LINE.lat_deg, LINE.lon_deg)
        times = segment_times(lap, project_lap(line, east, north), SEGMENTS)

        # constant 20 m/s: 60 m, 150 m and 90 m take 3, 7.5 and 4.5 s
        assert times == pytest.approx([3.0, 7.5, 4.5], abs=0.03)
        assert sum(times) == pytest.approx(lap.time_s, abs=1e-9)


def _layout(tmp_path, segments: str) -> None:
    (tmp_path / "x.toml").write_text(
        'name = "X"\nexpected_length_m = 100\nlength_tolerance_m = 10\n'
        "[finish_line]\nlat_deg = 0\nlon_deg = 0\nheading_deg = 90\n" + segments
    )


@pytest.mark.parametrize(("segments", "error"), [
    ('[[segment]]\nid = "A"\nstart_m = 5\n', "must start at the finish line"),
    ('[[segment]]\nid = "A"\nstart_m = 0\n[[segment]]\nid = "B"\nstart_m = 0\n', "must increase"),
    ('[[segment]]\nid = "A"\nstart_m = 0\n[[segment]]\nid = "A"\nstart_m = 50\n', "duplicate"),
])
def test_layout_refuses_segments_that_do_not_tile_the_lap(tmp_path, segments, error):
    _layout(tmp_path, segments)

    with pytest.raises(ValueError, match=error):
        load_track("x", tracks_dir=tmp_path)


# Uses the versioned reference lines, not raw data.
@pytest.mark.parametrize("track_id", ["aldeia-v1", "aldeia-v3", "schincariol-3"])
def test_detected_corners_fall_in_the_hand_analysis_corner_segments(track_id):
    track = load_track(track_id)
    line = load_reference_line(track)
    starts = [s.start_m for s in track.segments] + [line.length_m]

    found = set()
    for corner in detect_corners(line):
        i = max(i for i, s in enumerate(starts[:-1]) if s <= corner.apex_m)
        assert track.segments[i].id.startswith("C"), (corner, track.segments[i].id)
        found.add(track.segments[i].id)
    # Only flat-out kinks of a few degrees may go undetected.
    undetected = {s.id for s in track.segments if s.id.startswith("C")} - found
    assert undetected <= {"schincariol-3": {"C6"}, "aldeia-v3": {"C4"}}.get(track_id, set())
