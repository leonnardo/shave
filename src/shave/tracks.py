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
class Track:
    id: str
    name: str
    expected_length_m: float
    length_tolerance_m: float
    finish_line: FinishLine


def load_track(track_id: str, tracks_dir: Path = TRACKS_DIR) -> Track:
    path = tracks_dir / f"{track_id}.toml"
    if not path.exists():
        known = sorted(p.stem for p in tracks_dir.glob("*.toml"))
        raise ValueError(f"unknown track {track_id!r}; known: {known}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    line = raw["finish_line"]
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
    )
