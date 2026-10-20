"""Track layouts, one TOML file per layout under tracks/ at the repo root."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

TRACKS_DIR = Path(__file__).resolve().parents[2] / "tracks"

# How far to each side of the line point a pass still counts as crossing it.
# Wider than any kart track; small enough not to catch a parallel stretch.
DEFAULT_HALF_WIDTH_M = 12.0


@dataclass(frozen=True)
class FinishLine:
    """A line through a point, perpendicular to the direction of travel."""

    lat_deg: float
    lon_deg: float
    heading_deg: float  # direction of travel when crossing, clockwise from north
    half_width_m: float = DEFAULT_HALF_WIDTH_M


@dataclass(frozen=True)
class Segment:
    """A stretch of the lap, from `start_m` to the next segment's start.

    Stations are on the layout's reference line. Segments tile the lap: the
    first starts at the finish line (0 m), the last ends there.
    """

    id: str
    start_m: float


@dataclass(frozen=True)
class Track:
    id: str
    name: str
    expected_length_m: float
    length_tolerance_m: float
    finish_line: FinishLine
    segments: tuple[Segment, ...] = ()


def load_track(track_id: str, tracks_dir: Path = TRACKS_DIR) -> Track:
    path = tracks_dir / f"{track_id}.toml"
    if not path.exists():
        known = sorted(p.stem for p in tracks_dir.glob("*.toml"))
        raise ValueError(f"unknown track {track_id!r}; known: {known}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    line = raw["finish_line"]
    segments = tuple(Segment(id=str(s["id"]), start_m=float(s["start_m"])) for s in raw.get("segment", []))
    _check_segments(track_id, segments)
    return Track(
        id=track_id,
        name=raw["name"],
        expected_length_m=float(raw["expected_length_m"]),
        length_tolerance_m=float(raw["length_tolerance_m"]),
        finish_line=FinishLine(
            lat_deg=float(line["lat_deg"]),
            lon_deg=float(line["lon_deg"]),
            heading_deg=float(line["heading_deg"]),
            half_width_m=float(line.get("half_width_m", DEFAULT_HALF_WIDTH_M)),
        ),
        segments=segments,
    )


def _check_segments(track_id: str, segments: tuple[Segment, ...]) -> None:
    if not segments:
        return
    if segments[0].start_m != 0:
        raise ValueError(f"{track_id}: the first segment must start at the finish line (0 m)")
    starts = [s.start_m for s in segments]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError(f"{track_id}: segment starts must increase: {starts}")
    ids = [s.id for s in segments]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{track_id}: duplicate segment ids: {ids}")
