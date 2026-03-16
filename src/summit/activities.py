"""Generate a year-to-date activity summary in org-mode format.

Output: ~/dropbox/org/activities.org
  - One * section per month (Jan → current month)
  - Org table per month: date, activity name, type, duration
  - Footer row with total duration per month

Metadata cache: ~/.cache/garmin/activity_meta/YYYY.json
  - Covers ALL activity types (not just cycling/running)
  - Lightweight: no GPX downloads, just activity list metadata
  - Merged/upserted on each run by activityId
"""

import argparse
import json
import logging
import subprocess
import sys
from calendar import month_abbr, month_name
from datetime import date, datetime, timedelta
from pathlib import Path

from garminconnect import Garmin

from summit.credentials import get_credential

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "garmin" / "activity_meta"

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
# Cache
# ---------------------------------------------------------------------------


def cache_path(year: int) -> Path:
    """Return the cache file path for the given year.

    Args:
        year: The calendar year.

    Returns:
        Path to the JSON cache file.
    """
    return CACHE_DIR / f"{year}.json"


def load_cache(year: int) -> dict:
    """Load cached activity metadata, keyed by activityId (str).

    Args:
        year: The calendar year to load.

    Returns:
        Dict mapping activityId strings to activity metadata dicts.
        Returns an empty dict if the file is missing or corrupt.
    """
    path = cache_path(year)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return {str(a["activityId"]): a for a in data}
        except Exception:
            pass
    return {}


def save_cache(year: int, by_id: dict) -> None:
    """Persist activity metadata for a year to disk.

    Args:
        year: The calendar year.
        by_id: Dict of activity metadata keyed by activityId (str).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(year).write_text(json.dumps(list(by_id.values()), indent=2))


# ---------------------------------------------------------------------------
# Garmin fetch
# ---------------------------------------------------------------------------


def fetch_activities(client: Garmin, start_date: str, end_date: str) -> list:
    """Fetch all activities between two dates.

    Uses garminconnect which paginates internally (20 per page).

    Args:
        client: Authenticated Garmin client.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        List of raw activity dicts from the Garmin API.
    """
    return client.get_activities_by_date(
        start_date, end_date, activitytype=None
    )


def extract_meta(act: dict) -> dict:
    """Extract only the fields needed for the YTD summary from a raw activity.

    Args:
        act: Raw activity dict from the Garmin API.

    Returns:
        Dict with activityId, startTimeLocal, activityName, typeKey,
        duration (seconds), and distance_km fields.
    """
    at = act.get("activityType") or {}
    type_key = at.get("typeKey") or ""
    distance_m = act.get("distance") or 0.0
    return {
        "activityId": act.get("activityId"),
        "startTimeLocal": act.get("startTimeLocal")
        or act.get("startTimeGMT")
        or "",
        "activityName": act.get("activityName") or "",
        "typeKey": type_key,
        "duration": act.get("duration") or 0.0,
        "distance_km": distance_m / 1000.0 if distance_m else 0.0,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def fmt_duration(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string in H:MM:SS format.
    """
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def type_label(type_key: str) -> str:
    """Return a human-readable label for a Garmin typeKey.

    Args:
        type_key: Garmin activity typeKey string.

    Returns:
        Human-readable label, or a Title Case fallback for unknown keys.
    """
    if type_key in TYPE_LABELS:
        return TYPE_LABELS[type_key]
    # Fallback: convert snake_case to Title Case
    return type_key.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------


def iso_week_date_range(year: int, week: int) -> tuple[date, date]:
    """Return the Monday and Sunday for the given ISO year and week.

    Args:
        year: ISO year.
        week: ISO week number (1-53).

    Returns:
        Tuple of (monday, sunday) as date objects.
    """
    monday = datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday, sunday


def week_month_label(year: int, week: int, abbrev: bool = False) -> str:
    """Return a human label showing which month(s) the week belongs to.

    Full examples (abbrev=False)::

        'January 2026'
        'February / March 2026'
        'December 2025 / January 2026'

    Abbreviated examples (abbrev=True, no year)::

        'Jan'
        'Feb / Mar'
        'Dec / Jan'

    Args:
        year: ISO year.
        week: ISO week number.
        abbrev: If True, use abbreviated month names without year.

    Returns:
        Human-readable month label for the week.
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
        return (
            f"{month_name[monday.month]} / "
            f"{month_name[sunday.month]} {monday.year}"
        )
    # Crosses a year boundary.
    return (
        f"{month_name[monday.month]} {monday.year} / "
        f"{month_name[sunday.month]} {sunday.year}"
    )


def current_iso_week(year: int) -> int:
    """Return the current ISO week number, capped at the last week of year.

    Args:
        year: The target year.

    Returns:
        Current ISO week number if year matches today, otherwise the
        last ISO week of the specified year.
    """
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
    """Format a distance in km with one decimal, or '-' if negligible.

    Args:
        km: Distance in kilometres.

    Returns:
        Formatted string like '10.5', or '-' if less than 0.1 km.
    """
    return f"{km:.1f}" if km >= 0.1 else "-"


def org_table(activities: list) -> str:
    """Render an org-mode table for a list of activity metadata dicts.

    Args:
        activities: List of activity metadata dicts (from extract_meta).

    Returns:
        Org-mode table string with header, separator, activity rows, and
        a totals row, or an italicised 'no activities' note if empty.
    """
    if not activities:
        return "/(no activities)/\n"

    header = (
        "| Date       | Activity                              "
        "| Type                 | Duration |   km |"
    )
    sep = (
        "|------------+---------------------------------------"
        "+----------------------+----------+------|"
    )

    rows = []
    total_seconds = 0.0
    total_km = 0.0
    for act in sorted(activities, key=lambda a: a["startTimeLocal"]):
        act_date = act["startTimeLocal"][:10]
        name = act["activityName"][:37]
        ttype = type_label(act["typeKey"])[:20]
        dur = fmt_duration(act["duration"])
        dist = fmt_distance(act.get("distance_km", 0.0))
        total_seconds += act["duration"]
        total_km += act.get("distance_km", 0.0)
        rows.append(
            f"| {act_date} | {name:<37} | {ttype:<20} | {dur:>8} | {dist:>4} |"
        )

    total_row = (
        f"| {'Total':<10} | {'':37} | {'':20} "
        f"| {fmt_duration(total_seconds):>8} | {total_km:>4.1f} |"
    )

    lines = [header, sep] + rows + [sep, total_row]
    return "\n".join(lines) + "\n"


def summary_table(by_week: dict, intensity_by_week: dict, year: int) -> str:
    """Render a top-level summary org-mode table with one row per week.

    Args:
        by_week: Dict mapping 'YYYY-Www' keys to lists of activity dicts.
        intensity_by_week: Dict mapping ISO week number to intensity data.
        year: The target year.

    Returns:
        Org-mode table string with weekly duration, distance, and
        intensity minute totals.
    """
    last_week = current_iso_week(year)

    header = "| Week | Month     | Duration |     km | Mod | Vig | Intensity |"
    sep = "|------+-----------+----------+--------+-----+-----+-----------|"

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

        mod_str = str(mod) if idata else "-"
        vig_str = str(vig) if idata else "-"
        eff_str = str(effective) if idata else "-"

        rows.append(
            f"| {week:>4} | {label:<9} | {dur:>8} | {km_str:>6} "
            f"| {mod_str:>3} | {vig_str:>3} | {eff_str:>9} |"
        )

    lines = [header, sep] + rows
    return "\n".join(lines) + "\n"


def intensity_line(data: dict) -> str:
    """Format a one-line intensity minutes summary for a week.

    Args:
        data: Garmin weekly intensity data dict with moderateValue and
            vigorousValue keys.

    Returns:
        Org-mode italic string showing moderate, vigorous, and effective
        intensity minutes (1 vigorous = 2 effective).
    """
    mod = data.get("moderateValue", 0) or 0
    vig = data.get("vigorousValue", 0) or 0
    # Garmin: 1 vigorous min = 2 intensity mins toward goal
    effective = mod + vig * 2
    return f"/{mod} mod + {vig} vig = {effective} intensity min/\n"


def generate_org(by_week: dict, intensity_by_week: dict, year: int) -> str:
    """Generate the full org file content with one section per ISO week.

    Args:
        by_week: Dict mapping 'YYYY-Www' keys to lists of activity dicts.
        intensity_by_week: Dict mapping ISO week number to intensity data.
        year: The target year.

    Returns:
        Complete org-mode file content as a string.
    """
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


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the activities command.

    Returns:
        Parsed argument namespace with format and output attributes.
    """
    p = argparse.ArgumentParser(description="Generate YTD activity summary")
    p.add_argument(
        "--format",
        choices=["json", "org"],
        default="json",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--output", default=None, help="Write output to file (default: stdout)"
    )
    return p.parse_args()


def main() -> None:
    """Fetch Garmin activities and generate a YTD activity summary."""
    args = parse_args()
    year = datetime.now().year
    start_date = f"{year}-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("Loading cache for %d...", year)
    by_id = load_cache(year)
    logger.info("Cached: %d activities", len(by_id))

    logger.info(
        "Fetching activity list from Garmin (%s → %s)...", start_date, end_date
    )
    client = None
    try:
        user = get_credential("garmin", "username")
        passwd = get_credential("garmin", "password")
        client = Garmin(user, passwd)
        client.login()
        raw = fetch_activities(client, start_date, end_date)
        logger.info("Fetched: %d activities from API", len(raw))
    except Exception as e:
        if by_id:
            logger.warning("Garmin API failed (%s), using cache only", e)
            raw = []
        else:
            logger.error("Garmin API failed and no cache available: %s", e)
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

    logger.info("New: %d  Updated: %d activities", new_count, updated_count)
    save_cache(year, by_id)
    logger.info("Cache saved: %s", cache_path(year))

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
    logger.info(
        "Fetching weekly intensity minutes (%s → %s)...", start_date, end_date
    )
    intensity_by_week: dict = {}
    try:
        if client is None:
            raise RuntimeError("no Garmin client (API unavailable)")
        raw_intensity = client.get_weekly_intensity_minutes(
            start_date, end_date
        )
        for entry in raw_intensity:
            cal = entry.get("calendarDate")
            if not cal:
                continue
            dt = datetime.strptime(cal, "%Y-%m-%d")
            iso_year, iso_week, _ = dt.isocalendar()
            if iso_year == year:
                intensity_by_week[iso_week] = entry
        logger.info("Got %d weeks of intensity data", len(intensity_by_week))
    except Exception as e:
        logger.warning("Intensity minutes fetch failed (%s), skipping", e)

    # Generate output
    if args.format == "org":
        content = generate_org(by_week, intensity_by_week, year)
    else:
        content = json.dumps(list(by_id.values()), indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
        logger.info("Written: %s", out_path)
        logger.info("Weeks: %d  Total activities: %d",
                    len(by_week), len(by_id))
        # Sync to Dropbox only when writing an org file
        if args.format == "org":
            logger.info("Syncing to Dropbox...")
            try:
                subprocess.run(
                    [
                        "rclone",
                        "copyto",
                        str(out_path),
                        "dropbox:/org/activities.org",
                    ],
                    check=True,
                    capture_output=True,
                )
                logger.info("Synced to Dropbox")
            except Exception as e:
                logger.warning("rclone sync failed (%s)", e)
    else:
        print(content)


if __name__ == "__main__":
    main()
