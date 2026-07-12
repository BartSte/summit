"""Generate Personal Records (Cycling + Running + Segment KOMs).

Output: ~/dropbox/org/personal_records.org

Phase: called by setup, update, and auto_update after cache is populated.
"""
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CYCLING_TYPES = {
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "virtual_ride",
    "e_bike_fitness",
    "e_bike",
    "cyclocross",
}


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return ""
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _load_latest_ride() -> dict | None:
    meta_dir = Path.home() / ".cache" / "garmin" / "activity_meta"
    latest = None
    for meta_file in sorted(meta_dir.glob("*.json")):
        try:
            activities = json.loads(meta_file.read_text())
        except Exception:
            continue
        if not isinstance(activities, list):
            continue
        for activity in activities:
            type_key = activity.get("typeKey") or activity.get("activityType", {}).get("typeKey")
            if type_key not in CYCLING_TYPES:
                continue
            start_time = activity.get("startTimeLocal") or activity.get("startTimeGMT")
            if not start_time:
                continue
            if latest is None or start_time > latest["startTimeLocal"]:
                latest = {
                    "id": activity.get("activityId"),
                    "name": activity.get("activityName") or "Ride",
                    "startTimeLocal": start_time,
                    "distance_km": activity.get("distance_km"),
                }
    return latest


def _render_recent_ride_kom_summary(kom_json: Path) -> str:
    latest_ride = _load_latest_ride()
    if not latest_ride:
        return ""
    try:
        kom_data = json.loads(kom_json.read_text())
    except Exception:
        return ""

    rows = []
    for segment_name, data in kom_data.items():
        if not isinstance(data, dict):
            continue
        match = data.get("recent_ride_match")
        if not match or str(match.get("id")) != str(latest_ride.get("id")):
            continue
        normalized_power = match.get("normalized_power_w")
        avg_power = match.get("avg_power_w")
        rows.append({
            "segment": segment_name.removeprefix("SEG-"),
            "time": _format_duration(match.get("duration_s")),
            "rank": match.get("rank"),
            "avg_speed": f"{match.get('avg_speed_kmh', 0):.1f} km/h",
            "normalized_power": f"{normalized_power:.0f} W" if normalized_power is not None else "",
            "avg_power": f"{avg_power:.0f} W" if avg_power is not None else "",
            "status": "KOM" if match.get("is_kom") else "",
        })

    rows.sort(key=lambda row: (row["rank"] if row["rank"] is not None else 999999, row["segment"]))

    lines = [
        "",
        "* Recent Ride KOM Summary",
        "",
        f"- Activity: {latest_ride['name']}",
        f"- Date: {latest_ride['startTimeLocal']}",
    ]
    distance_km = latest_ride.get("distance_km")
    if distance_km is not None:
        lines.append(f"- Distance: {distance_km:.2f} km")
    lines.append(f"- Segments ridden: {len(rows)}")
    lines.append("")

    if rows:
        lines.append("| Segment | Time | Rank | Avg speed | Avg power | Normalized power | Status |")
        lines.append("|---------|------|------|-----------|-----------|--------|")
        for row in rows:
            rank = row["rank"] if row["rank"] is not None else ""
            lines.append(
                f"| {row['segment']} | {row['time']} | {rank} | {row['avg_speed']} | {row['avg_power']} | {row['normalized_power']} | {row['status']} |"
            )
    else:
        lines.append("- No tracked KOM segments matched on the most recent ride")

    return "\n".join(lines)


def main() -> None:
    """Assemble the personal_records.org file from PRs and KOM data."""
    start_date = (datetime.now() - timedelta(days=6 * 365)
                  ).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    output_file = Path.home() / "dropbox" / "org" / "personal_records.org"

    logger.info(">>> Generating personal records...")
    logger.info("    Date range: %s to %s", start_date, end_date)

    # Step 1: Cycling PRs (write fresh file)
    logger.info(
        ">>> Step 1: Cycling PRs "
        "(1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 km)..."
    )
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "cycling",
            "--distances", "1,5,10,20,30,40,50,60,70,80,90,100,150,200",
            "--power-durations", "1,2,5,10,20,30,60,90,120,180,240,360",
            "--format", "org",
            "--start", start_date,
            "--end", end_date,
            "--output", str(output_file),
        ],
        check=True,
    )
    logger.info("    ✓ Cycling PRs written to %s", output_file)

    # Step 2: Running PRs → temp file, then append
    logger.info(">>> Step 2: Running PRs (1, 5, 10 km)...")
    running_tmp = Path("/tmp/running_prs.org")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "running",
            "--distances", "1,5,10",
            "--title", "Running PRs",
            "--format", "org",
            "--start", start_date,
            "--end", end_date,
            "--output", str(running_tmp),
        ],
        check=True,
    )
    with open(output_file, "a") as f:
        f.write("\n")
        f.write(running_tmp.read_text())
    running_tmp.unlink(missing_ok=True)
    logger.info("    ✓ Running PRs appended to %s", output_file)

    # Step 3: Segment KOMs (if available)
    kom_json = Path("/tmp/kom_results_full.json")
    if kom_json.exists():
        logger.info(">>> Step 3: Appending Segment KOMs...")
        kom_tmp = Path("/tmp/kom_results.org")
        subprocess.run(
            [
                sys.executable, "-m", "summit.org",
                str(kom_json),
                "--format", "org",
                "--output", str(kom_tmp),
            ],
            check=True,
        )
        with open(output_file, "a") as f:
            f.write("\n")
            f.write(kom_tmp.read_text())
            recent_ride_summary = _render_recent_ride_kom_summary(kom_json)
            if recent_ride_summary:
                f.write("\n")
                f.write(recent_ride_summary)
        kom_tmp.unlink(missing_ok=True)
        logger.info("    ✓ Segment KOMs appended")
        if recent_ride_summary:
            logger.info("    ✓ Recent ride KOM summary appended")
    else:
        logger.info(">>> Step 3: No segment KOMs found (skipping)")

    line_count = len(output_file.read_text().splitlines())
    logger.info("✓ Personal records complete — %s (%d lines)",
                output_file, line_count)


if __name__ == "__main__":
    main()
