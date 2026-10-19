from datetime import datetime

import pytest

from aim_csv import SIM, write_aim_csv
from shave.aim import read_session


def test_reads_metadata(tmp_path):
    session = read_session(write_aim_csv(tmp_path / "s.csv", [0, 1, 2], beacons_s=[0.05, 0.1]))

    assert session.venue == "Test"
    assert session.user == "Driver"
    assert session.started_at == datetime(2026, 10, 11, 9, 28, 29)
    assert session.sample_rate_hz == 20
    assert session.beacon_markers_s == (0.05, 0.1)


def test_renames_channels_with_units_and_converts_distance_to_meters(tmp_path):
    session = read_session(write_aim_csv(tmp_path / "s.csv", [0, 1, 2], beacons_s=[]))

    assert session.data["time_s"].to_list() == pytest.approx([0.0, 0.05, 0.1])
    assert session.data["distance_m"].to_list() == pytest.approx([0.0, 1.0, 2.0])
    assert session.data["lap_distance_m"].to_list() == [0, 1, 2]


def test_drops_simulated_channels(tmp_path):
    session = read_session(write_aim_csv(tmp_path / "s.csv", [0, 1], beacons_s=[]))

    assert SIM not in session.data.columns
    assert not any("sim" in c for c in session.data.columns)


def test_rejects_unknown_channels(tmp_path):
    path = write_aim_csv(tmp_path / "s.csv", [0, 1], beacons_s=[], extra_channels=("Water Temp",))

    with pytest.raises(ValueError, match="Water Temp"):
        read_session(path)


def test_rejects_files_that_are_not_aim_exports(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text('"a","b"\n"1","2"\n')

    with pytest.raises(ValueError, match="not an AiM CSV export"):
        read_session(path)
