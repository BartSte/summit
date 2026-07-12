"""Compute personal cycling PRs for fixed distances (e.g., 5/10/40 km).

Reuses the KOM track cache to avoid redundant GPX downloads.
"""
import argparse
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

try:
    from garminconnect import Garmin
except Exception:
    Garmin = None

from summit.credentials import get_garmin_client
from summit.kom import (
    SEGMENT_POWER_STREAM_START,
    calculate_segment_average_power,
    calculate_segment_normalized_power,
    get_activity_detail_points,
)

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

DEFAULT_CACHE_DIR = Path("/home/barts/.cache/garmin")
TRACKS_DIRNAME = "tracks"
DEFAULT_POWER_DURATIONS_MIN = "1,2,5,10,20,30,60,90,120,180,240,360"


def format_power_duration(minutes: float) -> str:
    """Format power-PR durations compactly while keeping 60/90 minutes explicit."""
    if minutes >= 120 and minutes % 60 == 0:
        return f"{int(minutes / 60)} h"
    return f"{int(minutes)} min" if minutes == int(minutes) else f"{minutes:g} min"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the prs command.

    Returns:
        Parsed argument namespace.
    """
    p = argparse.ArgumentParser(
        description="Compute cycling PRs for fixed distances using cached tracks"
    )
    p.add_argument("--distances", default="5,10,40",
                   help="Comma-separated distances in km (e.g., 5,10,40)")
    p.add_argument(
        "--activity", choices=["cycling", "running", "all"], default="cycling")
    p.add_argument("--title", default=None,
                   help="Section title for org output")
    p.add_argument("--range", choices=["this_year", "last_2_years",
                   "last_year", "last_6_months"], default="this_year")
    p.add_argument("--start", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--end", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--limit-activities", type=int, default=None,
                   help="Limit number of activities (debug)")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR),
                   help="Cache directory (default: /skills/kom/cache)")
    p.add_argument("--cache-spacing", type=float, default=5.0,
                   help="Downsample spacing for cached tracks (meters)")
    p.add_argument("--top", type=int, default=10,
                   help="Number of fastest results to include per distance")
    p.add_argument("--time-mode", choices=["elapsed", "moving"],
                   default="moving", help="Use elapsed or moving time")
    p.add_argument("--moving-threshold-m", type=float, default=1.0,
                   help="Distance threshold below which time is ignored in moving mode")
    p.add_argument(
        "--moving-speed-threshold-kmh",
        type=float,
        default=1.0,
        help="Min speed (km/h) for a segment to count as moving. Default: 1.0 km/h.",
    )
    p.add_argument("--output", default=None, help="Write output to file")
    p.add_argument("--format", choices=["json", "org"],
                   default="json", help="Output format (default: json)")
    p.add_argument(
        "--power-durations",
        default=DEFAULT_POWER_DURATIONS_MIN,
        help="Comma-separated durations in minutes for max avg power PRs "
             f"(e.g. '5,20,60'). Set to '' to disable. Default: '{DEFAULT_POWER_DURATIONS_MIN}'.",
    )
    return p.parse_args()


def resolve_range(args: Any) -> tuple[datetime, datetime]:
    """Resolve the date range from parsed CLI arguments.

    Args:
        args: Parsed argument namespace with range, start, and end fields.

    Returns:
        Tuple of (start, end) datetime objects.
    """
    now = datetime.now()
    if args.start and args.end:
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end)
    elif args.range == "this_year":
        start = now.replace(month=1, day=1, hour=0,
                            minute=0, second=0, microsecond=0)
        end = now
    elif args.range == "last_year":
        end = now
        start = end - timedelta(days=365)
    elif args.range == "last_6_months":
        end = now
        start = end - timedelta(days=183)
    else:
        end = now
        start = end - timedelta(days=365 * 2)
    return start, end


def want_activity(type_key: Any, activity: str) -> bool:
    """Return True if the activity type matches the requested filter.

    Args:
        type_key: Garmin typeKey string for the activity.
        activity: Filter mode: ``'cycling'``, ``'running'``, or ``'all'``.

    Returns:
        True if the activity should be included in processing.
    """
    if activity == "all":
        return True
    if activity == "cycling":
        return type_key in CYCLING_TYPES or (type_key and "bike" in type_key)
    if activity == "running":
        running_types = {
            "running", "trail_running", "treadmill_running", "track_running"
        }
        return type_key in running_types or (
            type_key and "run" in type_key
        )
    return False


def parse_time(t: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string to a datetime, or return None.

    Args:
        t: Timestamp string, possibly ending in ``'Z'``, or None.

    Returns:
        Parsed datetime, or None if input is None or unparseable.
    """
    if t is None:
        return None
    t = t.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t)
    except Exception:
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two coordinates.

    Args:
        lat1: Latitude of the first point in decimal degrees.
        lon1: Longitude of the first point in decimal degrees.
        lat2: Latitude of the second point in decimal degrees.
        lon2: Longitude of the second point in decimal degrees.

    Returns:
        Distance in metres.
    """
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * \
        math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def downsample_activity(
    points: list[Any], min_spacing_m: float = 5.0
) -> list[Any]:
    """Reduce a list of GPS points by enforcing a minimum spacing.

    Args:
        points: List of (lat, lon, time, ele) tuples.
        min_spacing_m: Minimum distance in metres between kept points.

    Returns:
        Downsampled list of points, always including the last original point.
    """
    if not points:
        return points
    kept = [points[0]]
    last = points[0]
    for p in points[1:]:
        if haversine_m(last[0], last[1], p[0], p[1]) >= min_spacing_m:
            kept.append(p)
            last = p
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def _parse_power_from_extensions(trkpt: ET.Element) -> Optional[float]:
    """Extract power in watts from a GPX track point's extensions element.

    Args:
        trkpt: A ``<trkpt>`` XML element.

    Returns:
        Power in watts as a float, or None if not present.
    """
    for child in trkpt.iter():
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "power" and child.text:
            try:
                return float(child.text)
            except ValueError:
                pass
    return None


def parse_gpx_text(gpx_text: str) -> list[Any]:
    """Parse GPX XML text into a list of track points.

    Args:
        gpx_text: GPX file content as a string.

    Returns:
        List of (lat, lon, time, ele, power) tuples, or empty list on parse
        error. ``power`` is watts as a float, or None if not recorded.
    """
    try:
        root = ET.fromstring(gpx_text)
    except Exception:
        return []
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    points = []
    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if lat is None or lon is None:
            continue
        t_el = trkpt.find("gpx:time", ns)
        t = parse_time(t_el.text) if t_el is not None else None
        ele_el = trkpt.find("gpx:ele", ns)
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
        power = _parse_power_from_extensions(trkpt)
        points.append((float(lat), float(lon), t, ele, power))
    return points


def ensure_cache_dirs(cache_dir: Path) -> None:
    """Create required cache subdirectories if they do not exist.

    Args:
        cache_dir: Root cache directory path.
    """
    (cache_dir / TRACKS_DIRNAME).mkdir(parents=True, exist_ok=True)


def cache_track_path(cache_dir: Path, activity_id: Any) -> Path:
    """Return the file path for a cached activity track.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.

    Returns:
        Path to the JSON cache file for the activity.
    """
    return cache_dir / TRACKS_DIRNAME / f"{activity_id}.json"


def cache_meta_path(cache_dir: Path, activity_id: Any) -> Path:
    """Return the file path for cached activity metadata.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.

    Returns:
        Path to the JSON metadata sidecar file for the activity.
    """
    return cache_dir / TRACKS_DIRNAME / f"{activity_id}.meta.json"


def save_cached_meta(
    cache_dir: Path, activity_id: Any, meta: dict[str, Any]
) -> None:
    """Save activity metadata to a sidecar JSON file.

    Stores Garmin-reported summary values (e.g. ``avg_power_w``) that are
    not available from the GPX track points.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.
        meta: Dict of metadata fields to persist.
    """
    cache_meta_path(cache_dir, activity_id).write_text(json.dumps(meta))


def load_cached_meta(
    cache_dir: Path, activity_id: Any
) -> Optional[dict[str, Any]]:
    """Load cached activity metadata, or return None if absent.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.

    Returns:
        Metadata dict, or None if no sidecar file exists.
    """
    path = cache_meta_path(cache_dir, activity_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_cached_track(
    cache_dir: Path, activity_id: Any, points: list[Any]
) -> None:
    """Serialise and save a downsampled track to the JSON cache.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.
        points: List of (lat, lon, time, ele, power) tuples. ``power`` is
            watts as a float, or None.
    """
    rows = []
    for p in points:
        t = p[2] if len(p) > 2 else None
        ele = p[3] if len(p) > 3 else None
        power = p[4] if len(p) > 4 else None
        rows.append([p[0], p[1], t.isoformat() if t else None, ele, power])
    cache_track_path(cache_dir, activity_id).write_text(json.dumps(rows))


def load_cached_track(
    cache_dir: Path, activity_id: Any
) -> Optional[list[Any]]:
    """Load a previously cached track, or return None if absent.

    Args:
        cache_dir: Root cache directory path.
        activity_id: Garmin activity ID.

    Returns:
        List of (lat, lon, time, ele, power) tuples, or None if not cached.
        ``power`` is watts as a float, or None if not recorded or not present
        in an older cache file.
    """
    path = cache_track_path(cache_dir, activity_id)
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    points = []
    for row in rows:
        lat, lon, t, ele = row[0], row[1], row[2], row[3]
        power = row[4] if len(row) > 4 else None
        points.append((lat, lon, parse_time(t) if t else None, ele, power))
    return points


def fetch_activities(client: Any, start_date: str, end_date: str) -> list[Any]:
    """Page through Garmin activities and return those within a date range.

    Args:
        client: Authenticated Garmin client.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        List of raw activity dicts within the date range.
    """
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date).replace(
        hour=23, minute=59, second=59)
    acts = []
    offset = 0
    limit = 100
    while True:
        batch = client.get_activities(start=offset, limit=limit)
        if not batch:
            break
        for act in batch:
            t = act.get("startTimeLocal") or act.get("startTimeGMT")
            dt = None
            if t:
                try:
                    dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if dt is None:
                continue
            if dt < start_dt:
                return acts
            if dt <= end_dt:
                acts.append(act)
        if len(batch) < limit:
            break
        offset += limit
    return acts


def compute_best_for_distance(
    points: list[Any],
    distance_m: float,
    time_mode: str = "elapsed",
    moving_threshold_m: float = 1.0,
    moving_speed_threshold_ms: float = 0.0,
) -> Optional[dict[str, Any]]:
    """Find the minimum time to cover a fixed distance within a track.

    Uses a sliding-window algorithm over timestamped GPS points.

    Args:
        points: List of (lat, lon, time, ele) tuples with timestamps.
        distance_m: Target distance in metres.
        time_mode: ``'elapsed'`` uses raw clock time; ``'moving'`` excludes
            paused segments below the speed threshold.
        moving_threshold_m: Minimum inter-point distance (m) to count as
            movement in moving mode.
        moving_speed_threshold_ms: Minimum speed (m/s) to count as
            movement in moving mode.

    Returns:
        Dict with ``duration_s`` (float) and ``start_time`` (datetime)
        keys, or None if no window of the required distance exists.
    """
    # Filter points with time.
    pts = [p for p in points if len(p) > 2 and p[2] is not None]
    if len(pts) < 2:
        return None

    cumdist = [0.0]
    cumtime = [0.0]

    for i in range(1, len(pts)):
        a = pts[i - 1]
        b = pts[i]
        d = haversine_m(a[0], a[1], b[0], b[1])
        dt = (b[2] - a[2]).total_seconds()
        if dt < 0:
            dt = 0.0
        if time_mode == "moving":
            speed_ms = d / dt if dt > 0 else 0.0
            if d < moving_threshold_m or speed_ms < moving_speed_threshold_ms:
                dt = 0.0
        cumdist.append(cumdist[-1] + d)
        cumtime.append(cumtime[-1] + dt)

    best = None  # (duration_s, start_idx, end_idx)
    j = 0
    for i in range(len(pts)):
        if j < i:
            j = i
        target = cumdist[i] + distance_m
        while j < len(pts) and cumdist[j] < target:
            j += 1
        if j >= len(pts):
            break
        # Interpolate between j-1 and j for exact distance
        if j == i:
            continue
        d0 = cumdist[j - 1]
        d1 = cumdist[j]
        t0 = cumtime[j - 1]
        t1 = cumtime[j]
        if d1 <= d0:
            continue
        frac = (target - d0) / (d1 - d0)
        t_at = t0 + frac * (t1 - t0)
        duration = t_at - cumtime[i]
        if duration <= 0:
            continue
        if best is None or duration < best[0]:
            best = (duration, i, j)
    if best is None:
        return None
    duration_s, start_idx, end_idx = best
    start_time = pts[start_idx][2]
    normalized_power_w = calculate_segment_normalized_power(
        pts, start_idx, end_idx
    )
    avg_power_w = calculate_segment_average_power(pts, start_idx, end_idx)
    return {
        "duration_s": duration_s,
        "start_time": start_time,
        "normalized_power_w": normalized_power_w,
        "avg_power_w": avg_power_w,
    }


def main() -> None:
    """Compute personal cycling/running records and output results."""
    args = parse_args()
    if Garmin is None:
        raise SystemExit(
            "garminconnect not installed. Activate venv and pip install garminconnect")

    distances_km = [float(x.strip())
                    for x in args.distances.split(",") if x.strip()]
    distances_m = [d * 1000.0 for d in distances_km]

    cache_dir = Path(args.cache_dir)
    ensure_cache_dirs(cache_dir)

    start, end = resolve_range(args)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    client = get_garmin_client()

    activities = fetch_activities(client, start_date, end_date)
    if args.limit_activities:
        activities = activities[: args.limit_activities]

    results = {str(d): [] for d in distances_km}

    power_durations_min: list[float] = []
    if args.power_durations.strip() and args.activity in ("cycling", "all"):
        power_durations_min = [
            float(x.strip())
            for x in args.power_durations.split(",")
            if x.strip()
        ]
    power_results: dict[str, list[Any]] = {
        str(d): [] for d in power_durations_min}

    for act in activities:
        at = act.get("activityType", {})
        typekey = at.get("typeKey") or at.get("parentTypeKey")
        if not want_activity(typekey, args.activity):
            continue
        activity_id = act.get("activityId")
        if not activity_id:
            continue

        points_ds = load_cached_track(cache_dir, activity_id)
        if points_ds is None:
            try:
                gpx_data = client.download_activity(
                    activity_id, dl_fmt=Garmin.ActivityDownloadFormat.GPX)
            except Exception:
                continue
            if isinstance(gpx_data, bytes):
                gpx_text = gpx_data.decode("utf-8", errors="ignore")
            else:
                gpx_text = str(gpx_data)
            points_full = parse_gpx_text(gpx_text)
            if not points_full:
                continue
            points_ds = downsample_activity(points_full, args.cache_spacing)
            save_cached_track(cache_dir, activity_id, points_ds)

        # Persist summary-level power metrics from the activity list.
        # avg_power_w is a fallback for GPX (which strips per-point power).
        # max_avg_power stores Garmin's best-effort max-average-power values
        # keyed by duration in seconds, used for power PR calculations.
        activity_avg_power = act.get("avgPower")
        max_avg_power: dict[str, float] = {}
        for dur_s in (60, 120, 300, 600, 1200, 1800, 3600, 5400, 7200, 10800, 14400, 21600):
            val = act.get(f"maxAvgPower_{dur_s}")
            if val is not None:
                max_avg_power[str(dur_s)] = float(val)
        save_cached_meta(
            cache_dir,
            activity_id,
            {"avg_power_w": activity_avg_power, "max_avg_power": max_avg_power},
        )

        # Collect max avg power PRs from Garmin summary metadata
        for dur_min in power_durations_min:
            dur_s = str(int(dur_min * 60))
            power_w = max_avg_power.get(dur_s)
            if power_w is not None:
                power_results[str(dur_min)].append({
                    "duration_min": dur_min,
                    "max_avg_power_w": power_w,
                    "activityId": activity_id,
                    "activityName": act.get("activityName"),
                    "startTimeLocal": act.get("startTimeLocal"),
                })

        analysis_points = points_ds
        activity_date = (act.get("startTimeLocal") or "").split(" ")[0]
        if typekey in CYCLING_TYPES and activity_date >= SEGMENT_POWER_STREAM_START:
            detail_points = get_activity_detail_points(client, activity_id)
            if detail_points:
                analysis_points = detail_points

        for dist_km, dist_m in zip(distances_km, distances_m):
            best = compute_best_for_distance(
                analysis_points,
                dist_m,
                time_mode=args.time_mode,
                moving_threshold_m=args.moving_threshold_m,
                moving_speed_threshold_ms=args.moving_speed_threshold_kmh / 3.6,
            )
            if not best:
                continue
            if best.get("avg_power_w") is None and activity_avg_power is not None:
                best["avg_power_w"] = activity_avg_power
            duration = best["duration_s"]
            avg_kmh = (dist_km) / (duration / 3600.0) if duration > 0 else None
            entry = {
                "distance_km": dist_km,
                "duration_s": duration,
                "avg_kmh": avg_kmh,
                "normalized_power_w": best.get("normalized_power_w"),
                "avg_power_w": best.get("avg_power_w"),
                "activityId": activity_id,
                "activityName": act.get("activityName"),
                "startTimeLocal": act.get("startTimeLocal"),
                "segmentStartTime": (
                    t.isoformat()
                    if (t := best.get("start_time")) is not None else None
                ),
            }
            results[str(dist_km)].append(entry)

    # Sort and keep top N
    for k in list(results.keys()):
        results[k] = sorted(results[k], key=lambda x: x["duration_s"])[
            : args.top]

    # Sort power results by power descending, keep top N
    for k in list(power_results.keys()):
        power_results[k] = sorted(
            power_results[k], key=lambda x: x["max_avg_power_w"], reverse=True
        )[: args.top]

    def render_org(results_dict: dict, power_results_dict: dict) -> str:
        """Render PR results as org-mode formatted text.

        Args:
            results_dict: Dict mapping distance strings to lists of PR
                entries.
            power_results_dict: Dict mapping duration-in-minutes strings to
                lists of power PR entries.

        Returns:
            Org-mode formatted string with headers and tables.
        """
        title = args.title or (
            "Cycling PRs" if args.activity == "cycling" else "Running PRs")
        lines = [f"* {title}"]
        lines.append(f"- Time mode: {args.time_mode}")
        lines.append(
            f"- Distances: {', '.join(str(d) for d in distances_km)} km")
        lines.append("** Time")
        for dist in distances_km:
            key = str(dist)
            lines.append(f"*** {dist:.1f} km")
            rows = results_dict.get(key, [])
            if not rows:
                lines.append("- no results")
                continue
            headers = ["Rank", "Time", "Avg speed", "Avg power", "Normalized power", "Date"]
            table_rows = []
            for i, r in enumerate(rows, 1):
                d = r["duration_s"]
                h = int(d // 3600)
                m = int((d % 3600) // 60)
                s = int(d % 60)
                time_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
                date = (r.get("startTimeLocal") or "").split()[
                    0]  # Extract date only
                normalized_power = r.get("normalized_power_w")
                avg_power = r.get("avg_power_w")
                power_str = f"{normalized_power:.0f} W" if normalized_power is not None else ""
                avg_power_str = f"{avg_power:.0f} W" if avg_power is not None else ""
                table_rows.append([
                    str(i),
                    time_str,
                    f"{(r.get('avg_kmh') or 0):.1f} km/h",
                    avg_power_str,
                    power_str,
                    date,
                ])
            cols = list(zip(*([headers] + table_rows))
                        ) if table_rows else list(zip(*([headers])))
            widths = [max(len(str(cell)) for cell in col) for col in cols]

            def fmt_row_dist(cells: Any) -> str:
                """Format a list of cells as a padded org-mode table row.

                Args:
                    cells: Iterable of cell values to format.

                Returns:
                    Org-mode table row string with cell separators.
                """
                return (
                    "| "
                    + " | ".join(
                        str(c).ljust(widths[i])
                        for i, c in enumerate(cells)
                    )
                    + " |"
                )
            lines.append(fmt_row_dist(headers))
            lines.append("|" + "+".join("-" * (w + 2) for w in widths) + "|")
            for r in table_rows:
                lines.append(fmt_row_dist(r))

        if power_results_dict:
            dur_labels = []
            for dur_min_str in power_results_dict:
                dur_min = float(dur_min_str)
                dur_labels.append(format_power_duration(dur_min))
            lines.append("** Max average power")
            lines.append(f"- Times: {', '.join(dur_labels)}")
            for dur_min_str, entries in power_results_dict.items():
                dur_min = float(dur_min_str)
                dur_label = format_power_duration(dur_min)
                lines.append(f"*** {dur_label}")
                if not entries:
                    lines.append("- no results")
                    continue
                headers = ["Rank", "Avg power", "Date"]
                table_rows = []
                for i, r in enumerate(entries, 1):
                    date = (r.get("startTimeLocal") or "").split()[0]
                    power_w = r["max_avg_power_w"]
                    table_rows.append([
                        str(i),
                        f"{power_w:.0f} W",
                        date,
                    ])
                cols = list(zip(*([headers] + table_rows)))
                widths = [max(len(str(cell)) for cell in col) for col in cols]

                def fmt_row_power(cells: Any) -> str:
                    """Format a list of cells as a padded org-mode table row.

                    Args:
                        cells: Iterable of cell values to format.

                    Returns:
                        Org-mode table row string with cell separators.
                    """
                    return (
                        "| "
                        + " | ".join(
                            str(c).ljust(widths[i]) for i, c in enumerate(cells)
                        )
                        + " |"
                    )

                lines.append(fmt_row_power(headers))
                lines.append("|" + "+".join("-" * (w + 2)
                             for w in widths) + "|")
                for row in table_rows:
                    lines.append(fmt_row_power(row))

        return "\n".join(lines) + "\n"

    if args.format == "org":
        content = render_org(results, power_results)
    else:
        content = json.dumps(
            {"distance_prs": results, "power_prs": power_results}, indent=2
        )

    if args.output:
        Path(args.output).write_text(content)
    else:
        print(content)


if __name__ == "__main__":
    main()
