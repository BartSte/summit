# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# File type: Python

You must follow the "Google Python Style Guide" at all times when writing Python code. This means docstrings must also be "Google style" docstrings.

## Commands

```bash
# Install in editable mode (required to use the `summit` CLI)
pip install -e .

# Run all tests
pytest

# Run a single test file
pytest tests/test_prs.py -v

# Run a single test by name
pytest tests/test_prs.py::test_haversine_m -v

# Run with coverage
pytest --cov=summit --cov-report=html

# Use the CLI (after install)
summit prs --activity cycling --format org
summit kom
summit activities
summit check
summit auto-update
```

There is no configured linter or formatter.

## Architecture

Summit is a CLI tool for tracking Garmin cycling/running personal records (PRs) and segment KOM times using Komoot GPX files. It runs on a Raspberry Pi via systemd timers.

### Two independent systems

| System | Key module | Output |
|--------|-----------|--------|
| Personal Records + KOMs | `prs.py`, `kom.py` | `~/dropbox/org/personal_records.org` |
| YTD Activity Summary | `activities.py` | `~/dropbox/org/activities.org` |

Both sync to Dropbox via `rclone` (different strategies: `sync` for PRs, `copyto` for activities).

### Dual cache design

```
~/.cache/garmin/
├── tracks/          # Full GPX/JSON tracks for cycling+running (used by prs.py + kom.py)
├── segments/        # Komoot planned tour GPX files (SEG-*.gpx prefix filter)
└── activity_meta/   # Lightweight metadata for YTD summary (YYYY.json arrays)
```

`tracks/` and `activity_meta/` are intentionally separate: tracks contain full GPS data (large); metadata contains only the fields needed for the weekly table.

`activity_meta/YYYY.json` is stored as a JSON array on disk but loaded as a dict (keyed by str `activityId`) in memory for O(1) upsert.

### PR computation (`prs.py`)

Sliding-window algorithm over downsampled GPS tracks. For each target distance, finds the minimum elapsed (or moving) time across all windows. Supports filtering by activity type (`cycling`, `running`, or all).

### KOM detection (`kom.py`)

Loads Komoot segment GPX files, matches against cached Garmin activity tracks using GPS tolerance (default 25 m). Finds segment start/end in the track, then interpolates time and elevation.

### Credential resolution (`credentials.py`)

Two-step priority chain per service+field:
1. Env var: `SUMMIT_{SERVICE}_{FIELD}` (e.g. `SUMMIT_GARMIN_USERNAME`)
2. Shell command: `SUMMIT_{SERVICE}_{FIELD}_CMD` (e.g. `SUMMIT_GARMIN_PASSWORD_CMD="rbw get 'Garmin Connect'"`)

Services: `garmin`, `komoot`. Fields: `username`, `password`.

### CLI structure (`src/summit/cli/`)

- `main.py` — entry point, subcommand dispatcher
- `setup.py` — Phase 1: one-time 6-year historical cache build
- `update.py` — Phase 2: interactive cache refresh
- `auto_update.py` — non-interactive systemd target
- `generate.py` — assembles final org-mode output

### ISO week handling (`activities.py`)

Uses `datetime.isocalendar()` which correctly handles year-boundary edge cases (e.g. ISO week 1 of 2026 starts 2025-12-29). Activities where `iso_year != target_year` are excluded from grouping.

### Output formats

Default output is JSON; add `--format org` for org-mode tables. Org-mode output uses Emacs-style table separators (`|---+---|`).

### Intensity minutes formula

`effective = moderateValue + vigorousValue * 2` — matches Garmin's own formula (1 vigorous = 2 effective minutes).

### Known gaps

- `skating_ws` typeKey not in `TYPE_LABELS` dict (falls back to `Skating Ws`)
- `summit check` only inspects the `tracks/` cache, not `activity_meta/`
- `activities.py` is hardcoded to current year (no `--year` flag)
- Rclone remote name is hardcoded as `dropbox`
