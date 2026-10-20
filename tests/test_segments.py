import math

import pytest

from aim_csv import EARTH_RADIUS_M, write_circle_csv
from shave.aim import read_session
from shave.geo import to_local
from shave.laps import LapStatus, check_lap, split_laps
from shave.reference import build_reference_line, load_reference_line, project_lap
from shave.segments import detect_corners, propose_segments, segment_times
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


def test_segment_times_refuse_a_start_outside_the_lap(tmp_path):
    path = write_circle_csv(tmp_path / "s.csv", center=CENTER, circumference_m=CIRCUMFERENCE_M,
                            speed_ms=SPEED_MS, start_angle_rad=-0.3, duration_s=50.0)
    laps = [lap for lap in split_laps(read_session(path), TRACK)
            if check_lap(lap, TRACK).status == LapStatus.VALID]
    line = build_reference_line(laps, LINE)
    lap = laps[0]
    east, north = to_local(lap.data["lat_deg"], lap.data["lon_deg"], LINE.lat_deg, LINE.lon_deg)
    beyond = (Segment("A", 0.0), Segment("B", CIRCUMFERENCE_M + 5))

    with pytest.raises(ValueError, match="outside lap"):
        segment_times(lap, project_lap(line, east, north), beyond)


def test_proposal_refuses_a_corner_across_the_finish_line(tmp_path):
    # A circle turns everywhere: its one corner crosses the line.
    path = write_circle_csv(tmp_path / "s.csv", center=CENTER, circumference_m=CIRCUMFERENCE_M,
                            speed_ms=SPEED_MS, start_angle_rad=-0.3, duration_s=50.0)
    laps = [lap for lap in split_laps(read_session(path), TRACK)
            if check_lap(lap, TRACK).status == LapStatus.VALID]
    line = build_reference_line(laps, LINE)

    with pytest.raises(ValueError, match="crosses the finish line"):
        propose_segments(line, detect_corners(line))


# Detected corners per layout, in order: the segment each apex must fall in.
# The numbering is the driver's (hand analyses, or the driver for KGV).
# Not detected: flat-out kinks (Schincariol C6, Aldeia v3 C4, KGV C11 and
# C13) and KGV C4, which runs into C3 as one long left.
APEX_SEGMENTS = {
    "aldeia-v1": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"],
    "aldeia-v3": ["C1", "C2", "C3", "C5", "C6", "C7", "C8-9", "C8-9"],
    "schincariol-3": ["C1", "C2", "C3", "C4", "C5", "C7", "C8", "C9", "C10"],
    "kgv-101-invertido": ["C1", "C2", "C3", "C5", "C6", "C7", "C8", "C9", "C10", "C12", "C14"],
}


# Uses the versioned reference lines and layout files, not raw data.
@pytest.mark.parametrize("track_id", sorted(APEX_SEGMENTS))
def test_each_detected_apex_falls_in_its_corner_segment(track_id):
    track = load_track(track_id)
    line = load_reference_line(track)

    assert [_segment_at(track.segments, c.apex_m) for c in detect_corners(line)] == APEX_SEGMENTS[track_id]


@pytest.mark.parametrize("track_id", sorted(APEX_SEGMENTS))
def test_proposal_tiles_the_lap_with_one_apex_per_corner(track_id):
    line = load_reference_line(load_track(track_id))
    corners = detect_corners(line)
    proposal = propose_segments(line, corners)
    starts = [s.start_m for s in proposal]

    assert starts[0] == 0
    assert all(b > a for a, b in zip(starts, starts[1:]))
    assert starts[-1] < line.length_m
    holding = [_segment_at(proposal, c.apex_m) for c in corners]
    assert holding == [s.id for s in proposal if s.id.startswith("C")]


def _segment_at(segments, station_m):
    return [s.id for s in segments if s.start_m <= station_m][-1]
