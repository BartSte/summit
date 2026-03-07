# Garmin Scripts — Context Report

**Purpose:** This document gives an LLM complete context about the
`~/dotfiles-pi/scripts/garmin/` directory: what exists, how it works, what the
design decisions were, and what the current state is. Read this before making
any changes.

---

## Overview

This directory contains two independent but related systems:

| System | Script(s) | Output | Timer |
|--------|-----------|--------|-------|
| **Personal Records** | `cycling_prs.py`, `segment_kom.py`, `kom_to_org.py`, `komoot_cli.py`, `generate_personal_records.sh`, `auto_update.sh` | `~/dropbox/org/personal_records.org` | `garmin-update.timer` |
| **YTD Activity Summary** | `activities_ytd.py` | `~/dropbox/org/activities.org` | `garmin-activities.timer` |

Both systems run automatically every 15 minutes via separate systemd timers. Both
sync their output to Dropbox (remote wins for personal records via `rclone sync`;
local wins for activity summary via `rclone copyto`).

---

## Directory Layout

```
~/dotfiles-pi/scripts/garmin/
├── activities_ytd.py             # YTD activity summary → activities.org
├── auto_update.sh                # Systemd target for personal records updates
├── check_updates.py              # Detect new Garmin activities or Komoot segments
├── cycling_prs.py                # Compute personal records by distance
├── generate_personal_records.sh  # Assemble final personal_records.org
├── komoot_cli.py                 # Download Komoot segment GPX files
├── kom_to_org.py                 # Convert KOM JSON → org-mode section
├── README.md                     # Legacy README (may be out of date)
├── requirements.txt              # Python deps for the shared venv
├── segment_kom.py                # Detect segment KOMs (outputs JSON)
├── setup_cache.sh                # One-time Phase 1 historical setup
└── update_cache.sh               # Manual Phase 2 alternative to auto_update.sh
```

**Not committed to git:**
- `.venv/` — auto-created by `auto_update.sh` on first run
- Outputs (`personal_records.org`, `activities.org`) live in `~/dropbox/org/`
- Caches live in `~/.cache/garmin/`

---

## Environment

- **Machine:** Raspberry Pi 5, running 24/7
- **OS:** Linux (arm64), Debian-based
- **Python:** 3.x via system Python
- **Venv:** `~/dotfiles-pi/scripts/garmin/.venv` — shared by both systems
- **Credentials:** Managed via `rbw` (Bitwarden CLI):
  - `rbw get --field username 'Garmin Connect'`
  - `rbw get 'Garmin Connect'`  ← password
  - `rbw get --field username 'Komoot'`
  - `rbw get 'Komoot'`
- **Git repo:** Bare repo at `~/dotfiles-pi.git`, work tree at `~/`
  - Commit with: `GIT_DIR=~/dotfiles-pi.git GIT_WORK_TREE=~ git add/commit`
- **Dropbox sync:** via `rclone` with a remote named `dropbox`

---

## Python Dependencies

`requirements.txt`:
```
garminconnect==0.2.38
komPYoot>=1.0.5
gpxpy>=1.6.1
lxml>=4.9.0
requests>=2.31.0
```

The `garminconnect` library handles Garmin SSO auth and API pagination internally.
`get_activities_by_date(start, end)` paginates 20/page automatically.

---

## Cache Structure

```
~/.cache/garmin/
├── tracks/              # GPX/JSON tracks for cycling+running (for PR computation)
│   └── {activityId}.json   # 673 files covering ~6 years
├── segments/            # Komoot planned tour GPX files (SEG- prefix only)
│   └── SEG-*.gpx
├── activity_meta/       # Lightweight metadata for YTD summary
│   └── 2026.json            # All activity types; 44 activities as of 2026-03-07
└── auto_update.log      # Log output from garmin-update.timer runs
```

### `activity_meta/YYYY.json` format

A JSON array (not object) of activity metadata dicts. Keyed by `activityId` in
memory, but stored as a list on disk.

```json
[
  {
    "activityId": 22078045163,
    "startTimeLocal": "2026-03-06 06:58:28",
    "activityName": "Utrecht Road Cycling",
    "typeKey": "road_biking",
    "duration": 5385.626953125,
    "distance_km": 41.718578125
  },
  ...
]
```

Fields:
- `activityId` — integer (stored as int in JSON, cast to str for dict keys)
- `startTimeLocal` — `"YYYY-MM-DD HH:MM:SS"` in local time
- `activityName` — free-text name from Garmin
- `typeKey` — Garmin activity type identifier (snake_case), e.g. `road_biking`, `running`, `strength_training`
- `duration` — float, seconds
- `distance_km` — float, kilometres (0.0 for gym/strength workouts)

---

## System 1: Personal Records (`personal_records.org`)

### What it does

Computes fastest times over benchmark distances for cycling and running, and
finds the best time per Komoot segment (KOM = King of the Mountain, i.e. the
user's own PR on that segment).

### Scripts

**`cycling_prs.py`**
- Fetches Garmin cycling or running activities (GPX) for a date range
- Finds the fastest elapsed time over sliding windows of 1, 5, 10, ... km
- Outputs an org-mode table per distance with rank, time, avg speed, date, activity name
- CLI args: `--activity cycling|running`, `--distances 1,5,10,...`, `--start`, `--end`, `--output`

**`segment_kom.py`**
- Loads cached Komoot segment GPX files from `~/.cache/garmin/segments/`
- Matches each segment against all cached Garmin cycling activities
- Finds the fastest time the user rode each segment
- Outputs JSON to `/tmp/kom_results_full.json`

**`kom_to_org.py`**
- Reads the JSON output from `segment_kom.py`
- Appends a `* Segment KOMs` section to `personal_records.org`
- Each sub-section: segment name, distance, elevation, best time + leaderboard table

**`komoot_cli.py`**
- Downloads Komoot planned tour GPX files whose names start with `SEG-`
- Stores them in `~/.cache/garmin/segments/`

**`check_updates.py`**
- Checks whether the latest Garmin activity ID is already in the tracks cache
- Checks whether Komoot planned tours match cached segment GPX files
- `--quiet` mode: exits 0 (no updates) or 1 (updates needed) — used by `auto_update.sh`

**`auto_update.sh`**
- Systemd service target (runs every 15 min via `garmin-update.timer`)
- If `check_updates.py --quiet` returns 0: exits silently
- If updates needed: runs cycling_prs.py, komoot_cli.py, segment_kom.py, generate_personal_records.sh, rclone sync
- All output logged to `~/.cache/garmin/auto_update.log`

**`generate_personal_records.sh`**
- Calls `cycling_prs.py --activity cycling` (12 distances, 6-year range)
- Calls `cycling_prs.py --activity running` (1, 5, 10 km, 6-year range), appends to same file
- Calls `kom_to_org.py` if `/tmp/kom_results_full.json` exists
- Output: `~/dropbox/org/personal_records.org`

### Output format (`personal_records.org`)

```org
* Cycling PRs
** 5.0 km
| #  | Time | Avg (km/h) | Start               | Activity          |
|----+------+------------+---------------------+-------------------|
| 1  | 6:39 | 45.0       | 2024-06-15 09:33:15 | Utrecht Cycling   |

* Running PRs
** 5.0 km
| #  | Time  | Avg (km/h) | Start               | Activity           |
|----+-------+------------+---------------------+--------------------|
| 1  | 23:46 | 12.6       | 2020-05-30 12:50:50 | Opsterland Running |

* Segment KOMs
** SEG-Amerongse Berg
- Distance: 1.27 km  Ascent: 42 m  Best: 3:29 (KOM)
| Rank | Time  | Avg speed  | Date       |
|------+-------+------------+------------|
| 1    | 03:29 | 21.9 km/h  | 2022-07-23 |
```

---

## System 2: YTD Activity Summary (`activities.org`)

### What it does

Generates a year-to-date summary of **all** Garmin activity types (not just
cycling/running). Groups by ISO week. Writes `~/dropbox/org/activities.org`.

### Script: `activities_ytd.py`

**Full flow:**

1. Load `~/.cache/garmin/activity_meta/{year}.json` into `by_id` dict (keyed by str activityId)
2. Fetch all activities Jan 1 → today from Garmin API via `get_activities_by_date()`
3. Upsert into `by_id` (new count + updated count tracked separately)
4. Save updated cache back to disk
5. Group activities by ISO week key (`"YYYY-Www"`)
6. Fetch weekly intensity minutes via `get_weekly_intensity_minutes(start, end)`
7. Build `intensity_by_week` dict keyed by ISO week number (int)
8. Generate org file via `generate_org()`
9. Write to `~/dropbox/org/activities.org`
10. Sync to Dropbox with `rclone copyto` (local always wins — overwrites remote)

**Graceful degradation:**
- If Garmin API fails but cache exists → uses cache only (no crash)
- If intensity API fails → skips intensity lines silently

**ISO week handling:**
- Uses `datetime.isocalendar()` which returns (ISO year, week, weekday)
- ISO year ≠ calendar year near Jan 1 (e.g. Dec 29 can be Week 01 of next year)
- Activities with `iso_year != target_year` are excluded from grouping
- Week 01 of 2026 started Mon 2025-12-29; those activities appear in 2026 sections

**Intensity minutes:**
- Garmin API: `get_weekly_intensity_minutes(start, end)` returns list of `{calendarDate, moderateValue, vigorousValue, weeklyGoal}`
- `calendarDate` is the Monday of each ISO week
- Vigorous counts double: `effective = moderateValue + vigorousValue * 2`
- Goal and percentage are intentionally **not shown** in the output

**Distance:**
- Raw Garmin API `distance` field is in **metres**
- `extract_meta()` divides by 1000 → stores as `distance_km`
- Activities with `distance_km < 0.1` (e.g. gym workouts) display as `-`

**Type labels:**
- `TYPE_LABELS` dict maps Garmin `typeKey` → human label
- Fallback for unknown types: `snake_case` → `Title Case`
- Known gap: `skating_ws` → falls back to `Skating Ws` (not yet in TYPE_LABELS)

### Output format (`activities.org`)

```org
#+TITLE: Garmin Activities 2026
#+GENERATED: 2026-03-07 10:25

* Summary

| Week | Month     | Duration |     km | Mod | Vig | Intensity |
|------+-----------+----------+--------+-----+-----+-----------|
|    1 | Dec / Jan |  3:00:58 |   57.6 | 254 |  24 |       302 |
|    2 | Jan       |  3:42:01 |   63.0 | 187 |  71 |       329 |
...

* Week 01 · December 2025 / January 2026

/254 mod + 24 vig = 302 intensity min/

| Date       | Activity                              | Type                 | Duration |   km |
|------------+---------------------------------------+----------------------+----------+------|
| 2026-01-02 | Utrecht Running                       | Running              |  0:51:58 |  7.2 |
| 2026-01-03 | Threshold Indoor                      | Cycling              |  0:50:00 | 23.0 |
| 2026-01-03 | Gym Workout - MyFitnessPal            | Other                |  0:19:00 |    - |
|------------+---------------------------------------+----------------------+----------+------|
| Total      |                                       |                      |  3:00:58 | 57.6 |
```

**Summary table columns:**
- `Week` — ISO week number (1–53)
- `Month` — abbreviated, no year (e.g. `Jan`, `Feb / Mar`, `Dec / Jan`)
- `Duration` — `H:MM:SS` total for the week
- `km` — total km for the week (1 decimal)
- `Mod` — moderate intensity minutes
- `Vig` — vigorous intensity minutes
- `Intensity` — effective total (`Mod + Vig × 2`)

**Weekly section:**
- Header: full month name(s) + year (e.g. `February / March 2026`)
- Intensity line in org italic markup (`/…/`)
- Table: sorted by `startTimeLocal`, activity name truncated to 37 chars, type to 20 chars
- Total row: summed duration + km

---

## Systemd Units

All unit files live in `~/dotfiles-pi/systemd/user/` and are symlinked to
`~/.config/systemd/user/` by `~/dotfiles-pi/systemd/main`.

### `garmin-update.service` + `garmin-update.timer`
```ini
# service
ExecStart=/bin/bash %h/dotfiles-pi/scripts/garmin/auto_update.sh

# timer
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true
```

### `garmin-activities.service` + `garmin-activities.timer`
```ini
# service
ExecStart=/bin/bash -c 'cd %h/dotfiles-pi/scripts/garmin && source .venv/bin/activate && python3 activities_ytd.py'

# timer
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true
```

**Useful commands:**
```bash
systemctl --user list-timers
systemctl --user status garmin-activities.timer
systemctl --user start garmin-activities.service   # trigger now
journalctl --user -u garmin-activities.service -n 50
journalctl --user -u garmin-update.service -n 50
```

---

## Current State (as of 2026-03-07)

- **Activities in YTD cache:** 44 (all of 2026 so far)
- **Weeks covered:** Week 01–10 (2026)
- **GPX track cache:** 673 files covering ~6 years of cycling + running
- **Komoot segments:** several SEG- prefixed tours in `~/.cache/garmin/segments/`
- **Both timers:** active and running

---

## Known Gaps / Future Work

1. **`skating_ws` typeKey** — not in `TYPE_LABELS`, falls back to `Skating Ws`.
   Add to the dict: `"skating_ws": "Skating"`.

2. **`auto_update.sh` does not call `activities_ytd.py`** — the two systems run
   via separate timers. If you want them consolidated into one flow, add a call
   to `activities_ytd.py` at the end of `auto_update.sh`.

3. **`check_updates.py` only checks cycling/running tracks cache** — it doesn't
   know about the `activity_meta/` cache. If you add a "check" step for the YTD
   summary, it would need to compare the latest Garmin activity ID against the
   newest entry in `activity_meta/YYYY.json`.

4. **Multi-year support for `activities_ytd.py`** — currently hardcoded to
   `datetime.now().year`. To generate past-year summaries, add a `--year` CLI arg.

5. **Rclone remote name** — hardcoded as `dropbox` in `activities_ytd.py`. Same
   convention used elsewhere in the codebase.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `activity_meta/` cache from `tracks/` | `tracks/` contains full GPX data for PR computation (large). `activity_meta/` is lightweight (just metadata fields needed for the table). Don't mix them. |
| Store cache as list on disk, dict in memory | JSON lists are simpler to inspect/debug. Dict (keyed by str activityId) is needed for O(1) upsert. `load_cache()` converts on load. |
| ISO week grouping with `isocalendar()` | Handles year-boundary edge cases correctly. Week 01 of 2026 started 2025-12-29; `isocalendar()` returns `(2026, 1, ...)` for that date, so activities land in the right section. |
| `distance_km < 0.1` → show `-` | Gym/strength workouts report `0.0` distance from Garmin. The threshold avoids showing `0.0` for those. |
| `rclone copyto` (not `sync`) for activities.org | `copyto` copies a single file to a named remote path. Local always overwrites remote. `sync` is used for `personal_records.org` (directory-level sync). |
| No goal/percentage in output | User preference — intensity goal is a personal Garmin setting and clutters the output. |
| Abbreviated months in summary table, full names in section headers | Summary table is compact (overview). Section headers need year context for navigation. |
| `vigorous × 2` for effective intensity | Garmin's own formula: 1 vigorous minute = 2 intensity minutes toward the weekly goal. |
