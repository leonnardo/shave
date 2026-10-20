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
(`tracks/<layout>.line.csv`: `station_m,lat_deg,lon_deg`, one row per metre;
the closing segment back to the start is whatever is left, under 1.5 m).

Every sample is projected onto it, giving:

- `station_m`: distance along the reference line from the finish line.
- `offset_m`: signed lateral distance from it (positive = right of the
  direction of travel). This is what "1 m more inside at the apex" is measured
  in.

Projection searches forward from the previous sample's station, so within a
lap, parts of the track that run close together (Schincariol has two
stretches 12.5 m apart) can't snap to the wrong one. A sample more than 15 m
from the line (an off, the pit lane) falls back to searching the whole line
and may land anywhere, so out-laps and in-laps are not projected.

The reference line is a ruler, not a racing line: any stable line works, and
once corners are drawn on it, it never changes. It is built automatically from
the median of the valid laps of one session, recorded in the line file's
header. Rebuilding it from another session moves it (median 0.2-0.6 m, up to
3 m in places, stations drifting up to 4 m by the end of the lap), which would
move every corner: hence never rebuild.

**Per-session alignment.** The Solo's GPS shifts up to ~2 m between sessions,
even on the same day (Schincariol 2026-09-27: 2.0 m).
Before projecting, each session is translated by the shift that best fits its
valid laps to the reference line (least squares on the lateral offsets). The
shift is stored in the document; without it, a GPS shift reads as "drove 2 m
wider" (Schincariol 0203: p95 offset 2.5 m before, 1.0 m after). A shift that
can't be trusted (too few samples, or most of the session still far from the
line after shifting) is an error, not a number.

**Laps are cut after aligning.** A first cut on raw GPS finds the valid laps,
their shift is estimated, and laps are cut again on shifted GPS, so they start
at station 0 (within one sample) and lap cutting and projection agree. Every
command cuts laps this way. Lap times change by at most ~10 ms, except for a
standing start, where a 1.7 m shift moves the crossing by 0.25 s at walking
pace; a lap right at the length tolerance can change validity (Aldeia
2026-10-11 0207 lap 6: 1036.3 m raw, 1035.6 m aligned, limit 1036 m).

**Track edges** (later): the envelope of the innermost and outermost offsets
ever driven at each station approximates usable width. Satellite imagery is a
visual background only: it is offset by metres and can't be trusted at the
±0.5 m these comparisons need.

**Ideal line** is a different thing: the best segments of a session stitched
together (time, speed, position). It is the comparison target for deltas and
the map overlay, derived from the document like the ideal lap.

## 2. Segments live in the layout file, by station

```toml
[[segment]]
id = "C4"        # stable name, used across sessions of this layout
start_m = 480    # ends where the next segment starts
```

Segments tile the lap: the first (`R0`) starts at the finish line, the last
ends there, so segment times add up to the lap time exactly. A corner's
segment starts where the previous one ends, so it includes its braking zone
and runs until the next corner (or straight) begins. Long straights are
segments of their own (`RO`, `RB`, `RP`...): time there depends mostly on the
kart, which is how the analyses separated kart from driver. Ids are per
layout: `aldeia-v1:C4` and `aldeia-v3:C4` are different corners.

Aldeia v1, Aldeia v3 and Schincariol use the segments of their hand
analyses: each corner detected on the reference line falls in the corner
segment of the same name. Two Aldeia v3 boundaries were moved 3-7 m earlier
to where braking starts. KGV has a draft from `shave propose-segments`, not
yet checked against how the driver counts corners: corners are runs of
curvature in one direction (radius under 80 m, turning at least 20°), each
corner segment holds exactly its own apex, and boundaries that land in a
braking zone move back to where braking starts. Flat-out kinks of a few
degrees are not detected (Schincariol C6, Aldeia v3 C4) and are added by
hand; a corner across the finish line makes the proposal refuse.

No boundary sits in a braking zone (median GPS deceleration below 0.15 g on
the reference session): a boundary mid-braking would make two segments'
times depend on where each lap started braking.

Whether a segment is braked or flat out is not part of the layout: it
depends on the kart, the tyres and the driver, and is measured per lap.

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
          "min_offset_m": -0.4            // offset where speed is lowest
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
   constants versioned with `shave_version`). Tested 2026-10-19 on 10 sessions
   exported at 100 Hz: the Solo's accelerometer is mounted tilted and its
   calibration is unstable between sessions; neither it nor a GPS+IMU fusion
   made brake points more consistent (brake-start spread across laps 4.0 m
   GPS-only vs 4.5 m at best fused, 10-15 m IMU alone).
3. **Turn-in** comes from GPS yaw rate (lateral acceleration / speed): its
   onset spreads 3.1 m lap to lap, against ~10 m for the logger's gyro
   (`YawRate`). Heading rate, when needed, is computed from positions; the
   `GPS Heading` channel's derivative doesn't track it.
4. **Export rate**: 20 Hz. The Solo samples GPS at 25 Hz and the IMU/gyro at
   50 Hz; Race Studio's 20 Hz export is a plain decimation of its 100 Hz one,
   lap times agree within 1 ms, and nothing above 20 Hz proved useful. Files
   are 5× smaller.
5. **Driver identity**: free text in `notes.driver` for now.
