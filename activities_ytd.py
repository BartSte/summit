#!/usr/bin/env python3
"""
Generate a year-to-date activity summary in org-mode format.

Output: ~/dropbox/org/activities.org
  - One * section per month (Jan → current month)
  - Org table per month: date, activity name, type, duration
  - Footer row with total duration per month

Metadata cache: ~/.cache/garmin/activity_meta/YYYY.json
  - Covers ALL activity types (not just cycling/running)
  - Lightweight: no GPX downloads, just activity list metadata
  - Merged/upserted on each run by activityId
"""

import json
import subprocess
import sys
from calendar import month_abbr, month_name
from datetime import datetime, timedelta
from pathlib import Path

try:
    from garminconnect import Garmin
except ImportError:
    print("Error: garminconnect not installed. Activate venv first.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "garmin" / "activity_meta"
OUTPUT_FILE = Path.home() / "dropbox" / "org" / "activities.org"

# Human-readable labels for Garmin typeKey values
TYPE_LABELS = {
    # Cycling
    "road_biking": "Road Biking",
    "cycling": "Cycling",
    "mountain_biking": "Mountain Biking",
    "gravel_cycling": "Gravel Cycling",
    "virtual_ride": "Virtual Ride",
    "e_bike_fitness": "E-Bike",
    "e_bike": "E-Bike",
    "cyclocross": "Cyclocross",
    "indoor_cycling": "Indoor Cycling",
    # Running
    "running": "Running",
    "trail_running": "Trail Running",
    "treadmill_running": "Treadmill Run",
    "track_running": "Track Running",
    "indoor_running": "Indoor Running",
    "virtual_run": "Virtual Run",
    # Walking / Hiking
    "walking": "Walking",
    "hiking": "Hiking",
    "indoor_walking": "Indoor Walking",
    # Swimming
    "open_water_swimming": "Open Water Swim",
    "lap_swimming": "Lap Swimming",
    "swimming": "Swimming",
    # Strength / Gym
    "strength_training": "Strength Training",
    "fitness_equipment": "Fitness Equipment",
    "indoor_climbing": "Indoor Climbing",
    "yoga": "Yoga",
    "pilates": "Pilates",
    "cardio_training": "Cardio",
    "hiit": "HIIT",
    # Multisport
    "triathlon": "Triathlon",
    "duathlon": "Duathlon",
    # Winter
    "resort_skiing_snowboarding_ws": "Skiing",
    "cross_country_skiing_ws": "XC Skiing",
    "snowshoeing": "Snowshoeing",
    # Water
    "kayaking": "Kayaking",
    "rowing": "Rowing",
    "stand_up_paddleboarding": "SUP",
    # Other
    "breathwork": "Breathwork",
    "other": "Other",
}


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def rbw_get(service, field=None):
    cmd = ["rbw", "get"]
    if field:
        cmd += ["--field", field]
    cmd += [service]
    return subprocess.check_output(cmd, text=True).strip()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_path(year: int) -> Path:
    return CACHE_DIR / f"{year}.json"


def load_cache(year: int) -> dict:
    """Load cached activity metadata, keyed by activityId (str)."""
    path = cache_path(year)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return {str(a["activityId"]): a for a in data}
        except Exception:
            pass
    return {}


def save_cache(year: int, by_id: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(year).write_text(json.dumps(list(by_id.values()), indent=2))


# ---------------------------------------------------------------------------
# Garmin fetch
# ---------------------------------------------------------------------------

def fetch_activities(client: Garmin, start_date: str, end_date: str) -> list:
    """Fetch all activities between two dates (YYYY-MM-DD).
    garminconnect paginates internally (20/page) and returns the full list."""
    return client.get_activities_by_date(start_date, end_date, activitytype=None)


def extract_meta(act: dict) -> dict:
    """Extract only the fields we care about from a raw Garmin activity."""
    at = act.get("activityType") or {}
    type_key = at.get("typeKey") or ""
    distance_m = act.get("distance") or 0.0
    return {
        "activityId": act.get("activityId"),
        "startTimeLocal": act.get("startTimeLocal") or act.get("startTimeGMT") or "",
        "activityName": act.get("activityName") or "",
        "typeKey": type_key,
        "duration": act.get("duration") or 0.0,
        "distance_km": distance_m / 1000.0 if distance_m else 0.0,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def type_label(type_key: str) -> str:
    if type_key in TYPE_LABELS:
        return TYPE_LABELS[type_key]
    # Fallback: convert snake_case to Title Case
    return type_key.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

def iso_week_date_range(year: int, week: int):
    """Return (monday, sunday) date objects for the given ISO year+week."""
    monday = datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday, sunday


def week_month_label(year: int, week: int, abbrev: bool = False) -> str:
    """Return a human label showing which month(s) the week belongs to.

    Full (abbrev=False):
      'January 2026'
      'February / March 2026'
      'December 2025 / January 2026'

    Abbreviated (abbrev=True, no year):
      'Jan'
      'Feb / Mar'
      'Dec / Jan'
    """
    monday, sunday = iso_week_date_range(year, week)
    mfmt = month_abbr if abbrev else month_name

    if abbrev:
        if monday.month == sunday.month:
            return mfmt[monday.month]
        return f"{mfmt[monday.month]} / {mfmt[sunday.month]}"

    if monday.month == sunday.month and monday.year == sunday.year:
        return f"{month_name[monday.month]} {monday.year}"
    if monday.year == sunday.year:
        return f"{month_name[monday.month]} / {month_name[sunday.month]} {monday.year}"
    # Crosses a year boundary
    return f"{month_name[monday.month]} {monday.year} / {month_name[sunday.month]} {sunday.year}"


def current_iso_week(year: int) -> int:
    """Return the current ISO week number, capped at the last week of year."""
    now = datetime.now()
    if now.year == year:
        return now.isocalendar()[1]
    # For past years: return last ISO week of that year
    dec28 = datetime(year, 12, 28)  # Dec 28 is always in the last ISO week
    return dec28.isocalendar()[1]


# ---------------------------------------------------------------------------
# Org generation
# ---------------------------------------------------------------------------

def fmt_distance(km: float) -> str:
    """Format km with 1 decimal, or '-' if negligible."""
    return f"{km:.1f}" if km >= 0.1 else "-"


def org_table(activities: list) -> str:
    """Render an org-mode table for a list of activity meta dicts."""
    if not activities:
        return "/(no activities)/\n"

    header = "| Date       | Activity                              | Type                 | Duration |   km |"
    sep    = "|------------+---------------------------------------+----------------------+----------+------|"

    rows = []
    total_seconds = 0.0
    total_km = 0.0
    for act in sorted(activities, key=lambda a: a["startTimeLocal"]):
        date = act["startTimeLocal"][:10]
        name = act["activityName"][:37]
        ttype = type_label(act["typeKey"])[:20]
        dur = fmt_duration(act["duration"])
        dist = fmt_distance(act.get("distance_km", 0.0))
        total_seconds += act["duration"]
        total_km += act.get("distance_km", 0.0)
        rows.append(f"| {date} | {name:<37} | {ttype:<20} | {dur:>8} | {dist:>4} |")

    total_row = f"| {'Total':<10} | {'':37} | {'':20} | {fmt_duration(total_seconds):>8} | {total_km:>4.1f} |"

    lines = [header, sep] + rows + [sep, total_row]
    return "\n".join(lines) + "\n"


def summary_table(by_week: dict, intensity_by_week: dict, year: int) -> str:
    """Render a top-level summary table with one row per week."""
    last_week = current_iso_week(year)

    header = "| Week | Month     | Duration |     km | Mod | Vig | Intensity |"
    sep    = "|------+-----------+----------+--------+-----+-----+-----------|"

    rows = []
    for week in range(1, last_week + 1):
        week_key = f"{year}-W{week:02d}"
        acts = by_week.get(week_key, [])
        label = week_month_label(year, week, abbrev=True)

        total_s = sum(a.get("duration", 0) for a in acts)
        total_km = sum(a.get("distance_km", 0) for a in acts)
        dur = fmt_duration(total_s) if total_s else "-"
        km_str = f"{total_km:.1f}" if total_km >= 0.1 else "-"

        idata = intensity_by_week.get(week, {})
        mod = idata.get("moderateValue", 0) or 0
        vig = idata.get("vigorousValue", 0) or 0
        effective = mod + vig * 2

        mod_str = str(mod)       if idata else "-"
        vig_str = str(vig)       if idata else "-"
        eff_str = str(effective) if idata else "-"

        rows.append(
            f"| {week:>4} | {label:<9} | {dur:>8} | {km_str:>6} "
            f"| {mod_str:>3} | {vig_str:>3} | {eff_str:>9} |"
        )

    lines = [header, sep] + rows
    return "\n".join(lines) + "\n"


def intensity_line(data: dict) -> str:
    """Format a one-line intensity minutes summary for a week."""
    mod = data.get("moderateValue", 0) or 0
    vig = data.get("vigorousValue", 0) or 0
    # Garmin: 1 vigorous min = 2 intensity mins toward goal
    effective = mod + vig * 2
    return f"/{mod} mod + {vig} vig = {effective} intensity min/\n"


def generate_org(by_week: dict, intensity_by_week: dict, year: int) -> str:
    """Generate the full org file content, one section per ISO week."""
    now = datetime.now()
    last_week = current_iso_week(year)

    lines = [
        f"#+TITLE: Garmin Activities {year}",
        f"#+GENERATED: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
        "* Summary",
        "",
        summary_table(by_week, intensity_by_week, year),
    ]

    for week in range(1, last_week + 1):
        label = week_month_label(year, week, abbrev=False)
        week_key = f"{year}-W{week:02d}"
        acts = by_week.get(week_key, [])
        lines.append(f"* Week {week:02d} · {label}")
        lines.append("")
        if week in intensity_by_week:
            lines.append(intensity_line(intensity_by_week[week]))
        lines.append(org_table(acts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    year = datetime.now().year
    start_date = f"{year}-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")

    print(f">>> Loading cache for {year}...")
    by_id = load_cache(year)
    print(f"    Cached: {len(by_id)} activities")

    print(f">>> Fetching activity list from Garmin ({start_date} → {end_date})...")
    client = None
    try:
        user = rbw_get("Garmin Connect", "username")
        passwd = rbw_get("Garmin Connect")
        client = Garmin(user, passwd)
        client.login()
        raw = fetch_activities(client, start_date, end_date)
        print(f"    Fetched: {len(raw)} activities from API")
    except Exception as e:
        if by_id:
            print(f"    Warning: Garmin API failed ({e}), using cache only")
            raw = []
        else:
            print(f"    Error: Garmin API failed and no cache available: {e}")
            sys.exit(1)

    # Upsert into cache
    new_count = 0
    updated_count = 0
    for act in raw:
        aid = str(act.get("activityId", ""))
        if not aid:
            continue
        meta = extract_meta(act)
        if aid not in by_id:
            new_count += 1
        else:
            updated_count += 1
        by_id[aid] = meta

    print(f"    New: {new_count}  Updated: {updated_count} activities")
    save_cache(year, by_id)
    print(f"    Cache saved: {cache_path(year)}")

    # Group by ISO week ("YYYY-Www")
    by_week: dict = {}
    for meta in by_id.values():
        ts = meta.get("startTimeLocal", "")
        if not ts:
            continue
        try:
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
        except ValueError:
            continue
        iso = dt.isocalendar()
        # Use ISO year (may differ from calendar year near Jan 1)
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        # Only include weeks that belong to the target year's sequence
        if iso[0] != year:
            continue
        by_week.setdefault(week_key, []).append(meta)

    # Fetch weekly intensity minutes
    print(f">>> Fetching weekly intensity minutes ({start_date} → {end_date})...")
    intensity_by_week: dict = {}
    try:
        if client is None:
            raise RuntimeError("no Garmin client (API unavailable)")
        raw_intensity = client.get_weekly_intensity_minutes(start_date, end_date)
        for entry in raw_intensity:
            cal = entry.get("calendarDate")
            if not cal:
                continue
            dt = datetime.strptime(cal, "%Y-%m-%d")
            iso_year, iso_week, _ = dt.isocalendar()
            if iso_year == year:
                intensity_by_week[iso_week] = entry
        print(f"    Got {len(intensity_by_week)} weeks of intensity data")
    except Exception as e:
        print(f"    Warning: intensity minutes fetch failed ({e}), skipping")

    # Write org file
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = generate_org(by_week, intensity_by_week, year)
    OUTPUT_FILE.write_text(content)
    print(f">>> Written: {OUTPUT_FILE}")
    print(f"    Weeks: {len(by_week)}  Total activities: {len(by_id)}")

    # Sync to Dropbox (local wins)
    print(">>> Syncing to Dropbox...")
    try:
        subprocess.run(
            ["rclone", "copyto", str(OUTPUT_FILE), "dropbox:/org/activities.org"],
            check=True, capture_output=True,
        )
        print("    ✓ Synced")
    except Exception as e:
        print(f"    Warning: rclone sync failed ({e})")


if __name__ == "__main__":
    main()
