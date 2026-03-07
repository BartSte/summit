# Garmin Activity Scripts

Personal records and KOM detection for Garmin cycling activities, with Komoot segment integration.

**Two-phase workflow:**
- **PHASE 1 (SETUP):** Initial cache build (6 years of activities + all segments)
- **PHASE 2 (MAINTAIN):** Keep caches fresh after new activities/segments

## Dependencies

```bash
pip install garminconnect komPYoot
```

## Credentials

Credentials are resolved via environment variables using a two-step priority chain.

### Option 1 — Direct env vars (good for CI / simple setups)

```bash
export SUMMIT_GARMIN_USERNAME="you@example.com"
export SUMMIT_GARMIN_PASSWORD="your-garmin-password"
export SUMMIT_KOMOOT_USERNAME="you@example.com"
export SUMMIT_KOMOOT_PASSWORD="your-komoot-password"
```

### Option 2 — Command env vars (good for password managers)

Set `*_CMD` variants to any shell command whose **stdout** is the credential:

```bash
# rbw (Bitwarden CLI)
export SUMMIT_GARMIN_USERNAME_CMD="rbw get --field username 'Garmin Connect'"
export SUMMIT_GARMIN_PASSWORD_CMD="rbw get 'Garmin Connect'"
export SUMMIT_KOMOOT_USERNAME_CMD="rbw get --field username 'Komoot'"
export SUMMIT_KOMOOT_PASSWORD_CMD="rbw get 'Komoot'"

# 1Password CLI
export SUMMIT_GARMIN_PASSWORD_CMD="op item get 'Garmin Connect' --fields password"

# pass / gopass
export SUMMIT_GARMIN_PASSWORD_CMD="pass show garmin/password"
```

### Shell profile example

Add to `~/.zshrc` or `~/.bashrc`:

```bash
export SUMMIT_GARMIN_USERNAME_CMD="rbw get --field username 'Garmin Connect'"
export SUMMIT_GARMIN_PASSWORD_CMD="rbw get 'Garmin Connect'"
export SUMMIT_KOMOOT_USERNAME_CMD="rbw get --field username 'Komoot'"
export SUMMIT_KOMOOT_PASSWORD_CMD="rbw get 'Komoot'"
```

If a credential is missing, the tool prints a helpful error showing exactly which env var to set.

## Cache Directories

- **Garmin activities:** `/home/barts/.cache/garmin/tracks/`
- **Komoot segments:** `/home/barts/.cache/garmin/segments/`

Created automatically on first run.

---

## Phase 1: SETUP (One-Time)

### Automated Setup
```bash
./setup_cache.sh
```

This script:
1. Caches all Garmin cycling activities (past 6 years)
2. Downloads all Komoot segments (`SEG-` prefix)
3. Computes personal records → `~/dropbox/org/personal_records.org`
4. Detects segment KOMs

**Takes:** 10-30 minutes (depending on activity count)

### Manual Setup (Step-by-Step)

If you prefer to run steps individually:

```bash
# 1. Cache Garmin activities (6 years)
./cycling_prs.py \
  --activity cycling \
  --start 2020-02-26 \
  --end 2026-02-26 \
  --output ~/dropbox/org/personal_records.org

# 2. Cache Komoot segments
./komoot_cli.py download-segments

# 3. Detect KOMs
./segment_kom.py
```

---

## Phase 2: MAINTAIN (Recurring)

### Detect Updates

Check if there are new activities or segments:
```bash
./check_updates.py
```

**Output:**
- Shows latest Garmin activity vs. last cached
- Shows Komoot segment count (cached vs. planned)
- Suggests which commands to run

### Update Caches & Personal Records

```bash
./update_cache.sh
```

This script:
1. Updates Garmin cache (last 6 months)
2. Updates Komoot segments
3. Regenerates personal records (full historical cache)
4. Regenerates segment KOMs

---

## Manual Workflow

If you prefer to run commands individually:

### Update Only Garmin Activities

```bash
# Fetch last 6 months of activities (caches new ones)
./cycling_prs.py \
  --activity cycling \
  --range last_6_months \
  --output /tmp/cache_update.json
```

### Update Only Komoot Segments

```bash
./komoot_cli.py download-segments
```

### Regenerate Personal Records

```bash
# Using full 6-year cache
./cycling_prs.py \
  --activity cycling \
  --start 2020-02-26 \
  --end 2026-02-26 \
  --output ~/dropbox/org/personal_records.org
```

### Detect Segment KOMs

```bash
./segment_kom.py
```

---

## Scripts Reference

### Workflow Scripts

#### `setup_cache.sh` - Phase 1: Initial Setup
Builds complete historical cache and generates initial personal records.

```bash
./setup_cache.sh
```

Runs: `cycling_prs.py` → `komoot_cli.py` → `segment_kom.py`

#### `update_cache.sh` - Phase 2: Maintain
Updates caches when new activities/segments arrive, then regenerates personal records.

```bash
./update_cache.sh
```

Runs: `check_updates.py` → `cycling_prs.py` → `komoot_cli.py` → `segment_kom.py`

#### `check_updates.py` - Detect Updates
Checks if there are new Garmin activities or Komoot segments.

```bash
./check_updates.py
```

**Output:** Shows cache state and what's new. Suggests which commands to run.

---

### Core Scripts

### `komoot_cli.py` - Komoot Management

Download and manage your Komoot tours.

**Commands:**

```bash
# List all planned tours
./komoot_cli.py list-planned

# Rename a tour
./komoot_cli.py rename --id 12345 --name "New Name"

# Bulk rename by prefix
./komoot_cli.py bulk-prefix --old "LE-" --new "L-"

# Download segments matching prefix (default: SEG-)
./komoot_cli.py download-segments
./komoot_cli.py download-segments --prefix "SEGMENT-"
./komoot_cli.py download-segments --cache-dir /path/to/segments
```

### `cycling_prs.py` - Personal Records (Fixed Distances)

Computes your fastest times for set distances.

```bash
./cycling_prs.py [options] [--output FILE]
```

**Options:**
- `--distances`: Comma-separated distances in km (default: `5,10,40`)
- `--activity`: `cycling`, `running`, or `all` (default: `cycling`)
- `--title`: Org-mode section title (default: "Cycling PRs" or "Running PRs")
- `--range`: `this_year`, `last_year`, `last_6_months`, `last_2_years`
- `--start` / `--end`: Custom date range (YYYY-MM-DD)
- `--time-mode`: `elapsed` or `moving` (default: `elapsed`)
- `--output`: Output file (`.org` for org-mode, `.json` for JSON, `.txt` for stdout)
- `--top`: Number of results per distance (default: 10)
- `--limit-activities`: Limit processed activities (debug)

**Examples:**
```bash
# Generate this year's cycling PRs as org
./cycling_prs.py --output personal_records.org

# Running PRs (last 6 months)
./cycling_prs.py --activity running --range last_6_months --output running_prs.org

# Custom distances and date range
./cycling_prs.py \
  --distances 5,10,20,30,40,50 \
  --start 2025-01-01 \
  --end 2026-02-26 \
  --output prs_custom.org

# JSON output for processing
./cycling_prs.py --distances 10,40 --output /tmp/prs.json
```

### `segment_kom.py` - KOM Detection on Segments

Finds your fastest times on Komoot segments.

```bash
./segment_kom.py [options] [--output FILE]
```

**Options:**
- `--segments-dir`: GPX segment directory (default: `/home/barts/.cache/garmin/segments`)
- `--segment-prefix`: GPX filename prefix to match (default: `SEG-`)
- `--tolerance`: GPS matching tolerance in meters (default: 25.0)
- `--activity`: `cycling` or `all` (default: `cycling`)
- `--range`: `this_year`, `last_year`, `last_6_months`, `last_2_years`
- `--start` / `--end`: Custom date range (YYYY-MM-DD)
- `--output`: Output file (`.json` only)
- `--top`: Number of results per segment (default: 10)
- `--limit-activities`: Limit processed activities (debug)

**Examples:**
```bash
# Detect KOMs on cached segments
./segment_kom.py

# With custom tolerance
./segment_kom.py --tolerance 50.0

# Last 6 months
./segment_kom.py --range last_6_months

# JSON output
./segment_kom.py --output kom_results.json

# Specify segments directory
./segment_kom.py --segments-dir /path/to/segments
```

## Output Formats

### Org-mode Tables (`.org`)

Used by `cycling_prs.py`:
```
* Cycling PRs
- Time mode: elapsed
- Distances: 5.0, 10.0, 40.0 km
** 5.0 km
| # | Time    | Avg (km/h) | Start              | Activity       |
|---+---------+------------+--------------------+----------------|
| 1 | 9:45    | 30.8       | 2026-02-20 10:30   | Morning Ride   |
| 2 | 9:52    | 30.4       | 2026-02-18 14:15   | Commute        |
```

### JSON Output

Used by `segment_kom.py` and optionally by `cycling_prs.py`:
```json
{
  "SEG-Climb": {
    "best": "5:32",
    "best_seconds": 332,
    "activity": { ... },
    "matches": 3,
    "top": [ ... ]
  }
}
```

## Tips

1. **Cache management:** Older cached tracks are reused on subsequent runs. To rebuild the cache, delete `/home/barts/.cache/garmin/` and run the scripts again.

2. **Segment naming:** Keep `SEG-` prefixes in Komoot tour names for easy filtering. Use the bulk-rename command if needed.

3. **Org files:** Generate separate org files for different activities or date ranges, then merge them into your main records file manually.

4. **Moving time:** For fair comparisons, use `--time-mode moving` to exclude pauses/stops.

5. **Debug mode:** Use `--limit-activities 10` to test quickly without processing your entire activity history.
