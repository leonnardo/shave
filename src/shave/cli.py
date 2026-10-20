import argparse
from pathlib import Path

from shave.aim import read_session
from shave.laps import LapStatus, check_lap, split_laps
from shave.reference import build_reference_line, save_reference_line
from shave.tracks import TRACKS_DIR, load_track


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="shave")
    commands = parser.add_subparsers(dest="command", required=True)

    laps = commands.add_parser("laps", help="list a session's laps and whether each is valid")
    laps.add_argument("session", type=Path, help="AiM Race Studio CSV export")
    laps.add_argument("--track", required=True, help="layout id, a file name in tracks/")

    reference = commands.add_parser(
        "reference", help="build a layout's reference line from a session's valid laps"
    )
    reference.add_argument("session", type=Path, help="AiM Race Studio CSV export")
    reference.add_argument("--track", required=True, help="layout id, a file name in tracks/")

    args = parser.parse_args(argv)
    {"laps": _laps, "reference": _reference}[args.command](args)


def _laps(args: argparse.Namespace) -> None:
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


def _reference(args: argparse.Namespace) -> None:
    session = read_session(args.session)
    track = load_track(args.track)
    valid = [lap for lap in split_laps(session, track)
             if check_lap(lap, track).status == LapStatus.VALID]
    line = build_reference_line(valid, track.finish_line)
    path = TRACKS_DIR / f"{track.id}.line.csv"
    save_reference_line(
        line, path,
        f"Median of {len(valid)} valid laps of {session.path.name} "
        f"({session.started_at:%Y-%m-%d}). Do not rebuild once corners are drawn on it.",
    )
    print(f"{path.name}: {line.length_m:.1f} m from {len(valid)} laps")


def _lap_time(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}"
