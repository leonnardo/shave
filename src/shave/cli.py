import argparse
from pathlib import Path

from shave.aim import read_session
from shave.laps import check_lap, split_laps
from shave.tracks import load_track


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="shave")
    commands = parser.add_subparsers(dest="command", required=True)
    laps = commands.add_parser("laps", help="list a session's laps and whether each is valid")
    laps.add_argument("session", type=Path, help="AiM Race Studio CSV export")
    laps.add_argument("--track", required=True, help="layout id, a file name in tracks/")
    args = parser.parse_args(argv)

    session = read_session(args.session)
    track = load_track(args.track)
    print(f"{session.path.name} · {track.name} · {session.started_at:%Y-%m-%d %H:%M}")
    print(f"{'lap':>4}  {'time':>9}  {'length':>7}  {'status':<10}  reason")
    for lap in split_laps(session, track):
        check = check_lap(lap, track)
        print(
            f"{lap.number:>4}  {_lap_time(lap.time_s):>9}  {lap.length_m:>5.0f} m  "
            f"{check.status:<10}  {check.reason}"
        )


def _lap_time(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}"
