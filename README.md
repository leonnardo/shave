# shave

Shaving tenths off kart laps, the way programmers shave cycles.

Deterministic analysis of AiM Solo kart telemetry (Race Studio CSV exports).

```sh
uv run shave laps data/raw/aldeia/2026-10-11/ADSv3_a_0209_027320.csv --track aldeia-v3
uv run pytest
```

- `data/raw/<track>/<date>/` holds the original exports, untouched and not versioned.
- `tracks/<layout>.toml` describes each layout; lengths are measured from our own laps unless noted.
- Laps are cut where the GPS crosses the layout's `[finish_line]`, not at the logger's beacons, so a badly set up logger doesn't change lap times.
