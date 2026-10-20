# Session schema (draft)

Status: agreed 2026-10-19; implementation starting with the reference line.

`shave` turns one logger export into one **session document** (JSON). The web
app stores and draws these documents; an agent reads them to write an
interpretation. Neither recomputes numbers: if a number is on screen, it came
from here.

## 1. Comparing laps needs a fixed reference line per layout

Lap distance from GPS follows the driven line, so the same apex sits at 935 m
on one lap and 948 m on another. Corner metrics and cross-session evolution
need a position that means the same thing every lap.

Each layout gets a **reference line**: a polyline, finish line to finish line,
built once from the median of good laps and stored next to the layout file
(`tracks/<layout>.line.csv`, one `lat_deg,lon_deg` row every ~1 m).

Every sample is projected onto it, giving:

- `station_m`: distance along the reference line from the finish line.
- `offset_m`: signed lateral distance from it (positive = right of the
  direction of travel). This is what "1 m more inside at the apex" is measured
  in.

Projection searches forward from the previous sample's station, so parts of
the track that run close together (Aldeia) can't snap to the wrong stretch.

The reference line is a ruler, not a racing line: any stable line works, and
once corners are drawn on it, it never changes. It is built automatically from
the median of the valid laps of one session, recorded in the layout file.

**Per-session alignment.** The Solo's GPS shifts up to ~1 m between sessions.
Before projecting, each session is translated by the shift that best fits its
valid laps to the reference line (least squares on the lateral offsets). The
shift is stored in the document; without it, a GPS shift reads as "drove 1 m
wider".

**Track edges** (later): the envelope of the innermost and outermost offsets
ever driven at each station approximates usable width. Satellite imagery is a
visual background only: it is offset by metres and can't be trusted at the
±0.5 m these comparisons need.

**Ideal line** is a different thing: the best segments of a session stitched
together (time, speed, position). It is the comparison target for deltas and
the map overlay, derived from the document like the ideal lap.

## 2. Corners live in the layout file, by station

```toml
[[corner]]
id = "C4"            # stable name, used across sessions of this layout
kind = "freio"        # "freio" | "de_pe"
entry_m = 420         # segment boundaries; consecutive segments tile the lap
apex_m = 450
exit_m = 480
```

Segments between corners are straights (`R1`, `R2`, ...), so a lap is fully
tiled and segment times add up to the lap time. Corner ids are per layout:
`aldeia-v1:C4` and `aldeia-v3:C4` are different corners.

Initial definitions come from the hand analyses (Aldeia v1 and v3 have all
apexes; Schincariol has only C1-C10 roughly) and get redrawn on the reference
line.

## 3. Session document

```jsonc
{
  "schema_version": 1,
  "shave_version": "0.2.0",          // code that produced the numbers
  "layout": "aldeia-v1",
  "alignment": { "east_m": 0.42, "north_m": -0.18 },  // GPS shift applied
  "source": {
    "file": "Leo Rabello_ADSv1_a_0181_027320.csv",
    "sha256": "…",                    // same file → same session id
    "started_at": "2026-08-29T09:20:00-03:00",
    "logger_user": "Leo Rabello"
  },
  "notes": {                          // typed by the driver at upload; free text allowed
    "driver": "Leo",
    "kart": "B",
    "tyres": null,
    "weather": null,
    "text": ""
  },
  "laps": [
    {
      "number": 2,
      "start_s": 64.102, "time_s": 51.228, "length_m": 938.1,
      "status": "valid", "status_reason": "",
      "segments": [
        {
          "id": "C4",
          "time_s": 3.412,
          "entry_kmh": 71.2, "min_kmh": 44.2, "min_station_m": 452.1, "exit_kmh": 58.0,
          "brake_station_m": 398.0,       // first decel > 0.25 g
          "brake_peak_g": 0.61,
          "release_station_m": 445.0,     // last decel before the minimum
          "throttle_station_m": 455.0,    // start of sustained accel > 0.05 g
          "apex_offset_m": -0.4           // offset at apex_m
        }
      ]
    }
  ],
  "traces": {                          // per lap, resampled every 2 m of station
    "step_m": 2,
    "laps": {
      "2": {
        "time_s":   [0.000, 0.081, …], // since the lap started
        "speed_kmh":[88.1, 88.3, …],
        "offset_m": [0.2, 0.2, …],
        "accel_long_g": [0.10, 0.11, …],
        "accel_lat_g":  [0.02, 0.03, …],
        "lat_deg": […], "lon_deg": […]
      }
    }
  }
}
```

Size: ~500 stations × 7 channels × ~20 laps ≈ 70k numbers, a few hundred KB of
JSON before compression. Small enough to load whole in the browser.

## 4. What is deliberately not in the document

- **Ideal lap, fast-vs-slow comparisons, evolution.** All derive from
  `segments` (sum of best segments; split laps by time within the session).
  Computing them from the document keeps one source of truth and lets the
  method change without reprocessing raw files. They can move into `shave` as
  functions over documents once they stabilise.
- **The interpretation.** A separate record that points to a session id and
  the `shave_version` it read, so a stale reading is visible after
  reprocessing.
- **Raw samples.** The original export stays in storage (R2); the document is
  rebuilt from it whenever the code changes.

## 5. Decisions

1. **Reference line**: automatic, median of the valid laps of one session per
   layout, frozen once corners are drawn.
2. **Brake/throttle** come from GPS acceleration (thresholds 0.25 g / 0.05 g,
   constants versioned with `shave_version`). The Solo's accelerometer is
   mounted tilted (+0.30 g bias at Aldeia 11/10, axis likely swapped at
   Schincariol) and carries ~10× the GPS noise at 20 Hz. Calibrating its
   orientation against GPS and fusing both (complementary filter, zero-phase
   since we run offline) is an experiment, kept only if brake points become
   more consistent lap to lap. Higher-rate exports (≥ 25 Hz) to be tested.
3. **Turn-in** comes from the gyro (`YawRate`), the closest thing to a
   steering sensor.
4. **Driver identity**: free text in `notes.driver` for now.
