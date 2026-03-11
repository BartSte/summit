"""Compute personal KOMs for user-defined segments from Garmin activities.

Segments are GPX files (from planned rides/routes). Only files with a given
prefix are treated as segments (default: ``"SEG-"``).
"""

import argparse
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, TypedDict

try:
    from garminconnect import Garmin
except Exception:
    Garmin = None

from summit.credentials import get_credential

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


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the kom command.

    Returns:
        Parsed argument namespace.
    """
    p = argparse.ArgumentParser(
        description="Compute personal KOMs for GPX-defined segments"
    )
    p.add_argument(
        "--segments-dir",
        default="/home/barts/.cache/garmin/segments",
        help="Directory containing segment GPX files (default: cache)",
    )
    p.add_argument(
        "--segment-prefix",
        default="SEG-",
        help="Only GPX files starting with this name are segments",
    )
    p.add_argument(
        "--tolerance",
        type=float,
        default=25.0,
        help="Matching tolerance in meters",
    )
    p.add_argument("--activity", choices=["cycling", "all"], default="cycling")
    p.add_argument(
        "--range",
        choices=["this_year", "last_2_years", "last_year", "last_6_months"],
        default="this_year",
    )
    p.add_argument("--start", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--end", help="YYYY-MM-DD (overrides --range)")
    p.add_argument(
        "--limit-activities",
        type=int,
        default=None,
        help="Limit number of activities (debug)",
    )
    p.add_argument("--output", default=None, help="Write output to file")
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of fastest matches to include",
    )
    p.add_argument(
        "--format",
        choices=["json", "org"],
        default="json",
        help="Output format (default: json)",
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
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
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
        activity: Filter mode: ``'cycling'`` or ``'all'``.

    Returns:
        True if the activity should be included in processing.
    """
    if activity == "all":
        return True
    if activity == "cycling":
        return type_key in CYCLING_TYPES or (type_key and "bike" in type_key)
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
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def downsample_points(
    points: list[Any], min_spacing_m: float = 10.0
) -> list[Any]:
    """Reduce a list of GPS points by enforcing a minimum spacing.

    Args:
        points: List of (lat, lon, ...) tuples.
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


def calculate_distance_m(points: list[Any]) -> float:
    """Calculate total distance in metres from a list of GPS points.

    Args:
        points: List of (lat, lon, ...) tuples.

    Returns:
        Total distance in metres.
    """
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        total += haversine_m(
            points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]
        )
    return total


def calculate_elevation_gain_loss(points: list[Any]) -> tuple[float, float]:
    """Calculate total ascent and descent from GPS points with elevation.

    Args:
        points: List of (lat, lon, time, ele) tuples.

    Returns:
        Tuple of (ascent_m, descent_m).
    """
    ascent = 0.0
    descent = 0.0
    for i in range(len(points) - 1):
        # Points are (lat, lon, time, ele) - ele is at index 3
        if len(points[i]) < 4 or len(points[i + 1]) < 4:
            continue
        ele1 = points[i][3]
        ele2 = points[i + 1][3]
        if ele1 is None or ele2 is None:
            continue
        diff = ele2 - ele1
        if diff > 0:
            ascent += diff
        else:
            descent += abs(diff)
    return ascent, descent


def read_gpx_points(path: Any) -> tuple[list[Any], Optional[str], Any]:
    """Parse a GPX file and return its track or route points.

    Tries track points first, then falls back to route points.

    Args:
        path: Path to the GPX file.

    Returns:
        Tuple of (points, name, root) where points is a list of
        (lat, lon, time, ele) tuples, name is the GPX track name or
        None, and root is the parsed XML root element.
    """
    ns = {
        "gpx": "http://www.topografix.com/GPX/1/1",
    }
    try:
        tree = ET.parse(path)
    except Exception:
        return [], None, None
    root = tree.getroot()
    # name
    name = None
    name_el = root.find("gpx:name", ns)
    if name_el is not None and name_el.text:
        name = name_el.text.strip()

    points = []
    # Try track points
    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if lat is None or lon is None:
            continue
        t_el = trkpt.find("gpx:time", ns)
        t = parse_time(t_el.text) if t_el is not None else None
        ele_el = trkpt.find("gpx:ele", ns)
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
        points.append((float(lat), float(lon), t, ele))

    if not points:
        # Try route points (planned rides often export as routes)
        for rtept in root.findall(".//gpx:rtept", ns):
            lat = rtept.get("lat")
            lon = rtept.get("lon")
            if lat is None or lon is None:
                continue
            t_el = rtept.find("gpx:time", ns)
            t = parse_time(t_el.text) if t_el is not None else None
            ele_el = rtept.find("gpx:ele", ns)
            ele = (
                float(ele_el.text)
                if ele_el is not None and ele_el.text
                else None
            )
            points.append((float(lat), float(lon), t, ele))

    return points, name, root


def nearest_segment_index(
    lat: float, lon: float, seg_points: list[Any]
) -> tuple[Optional[int], Optional[float]]:
    """Find the index of the nearest segment point to a given coordinate.

    Args:
        lat: Latitude of the query point in decimal degrees.
        lon: Longitude of the query point in decimal degrees.
        seg_points: List of (lat, lon) tuples representing the segment.

    Returns:
        Tuple of (index, distance_m) for the closest point, or
        (None, None) if seg_points is empty.
    """
    best_i: Optional[int] = None
    best_d: Optional[float] = None
    for i, (slat, slon) in enumerate(seg_points):
        d = haversine_m(lat, lon, slat, slon)
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d


def match_segment(
    activity_points: list[Any], segment_points: list[Any], tolerance_m: float
) -> Optional[tuple[float, int, int]]:
    """Find the best matching traversal of a segment within an activity.

    Args:
        activity_points: List of (lat, lon, time, ele) tuples.
        segment_points: List of (lat, lon, ...) tuples defining the segment.
        tolerance_m: GPS matching tolerance in metres.

    Returns:
        Tuple of (duration_s, start_idx, end_idx) for the fastest match,
        or None if no match is found.
    """
    if len(activity_points) < 2 or len(segment_points) < 2:
        return None
    seg_points = downsample_points(
        [(p[0], p[1]) for p in segment_points], min_spacing_m=10.0
    )
    start_pt = seg_points[0]
    end_pt = seg_points[-1]

    best = None
    for i, pt in enumerate(activity_points):
        alat, alon, atime = pt[0], pt[1], pt[2]
        if atime is None:
            continue
        if haversine_m(alat, alon, start_pt[0], start_pt[1]) <= tolerance_m:
            seg_i = 0
            for j in range(i, len(activity_points)):
                bpt = activity_points[j]
                blat, blon, btime = bpt[0], bpt[1], bpt[2]
                if btime is None:
                    continue
                nearest_i, nearest_d = nearest_segment_index(
                    blat, blon, seg_points
                )
                if (
                    nearest_d is not None
                    and nearest_i is not None
                    and nearest_d <= tolerance_m
                    and nearest_i >= seg_i
                ):
                    seg_i = nearest_i
                if (
                    haversine_m(
                        blat, blon, end_pt[0], end_pt[1]) <= tolerance_m
                    and seg_i >= len(seg_points) - 2
                ):
                    duration = (btime - atime).total_seconds()
                    if duration > 0 and (best is None or duration < best[0]):
                        best = (duration, i, j)
                    break
    return best


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS or M:SS.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like ``'1:23:45'`` or ``'23:45'``.
    """
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def fetch_activities(client: Any, start_date: str, end_date: str) -> list[Any]:
    """Page through Garmin activities and return those within a date range.

    Activities are returned newest-first; iteration stops as soon as an
    activity falls before the start date.

    Args:
        client: Authenticated Garmin client.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        List of raw activity dicts within the date range.
    """
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date).replace(
        hour=23, minute=59, second=59
    )
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
                # Activities are returned newest-first; stop once past range.
                return acts
            if dt <= end_dt:
                acts.append(act)
        if len(batch) < limit:
            break
        offset += limit
    return acts


class _SegResult(TypedDict):
    best_seconds: Optional[float]
    activity: Optional[dict[str, Any]]
    matches: int
    all: list[dict[str, Any]]
    distance_m: float
    ascent_m: float
    descent_m: float


def main() -> None:
    """Detect personal KOM times for all configured segments."""
    args = parse_args()
    if Garmin is None:
        raise SystemExit(
            "garminconnect not installed. Activate venv and pip install garminconnect"
        )

    segments_dir = Path(args.segments_dir)
    if not segments_dir.exists():
        raise SystemExit(
            f"Segments directory not found: {segments_dir}\nDownload segments first with: komoot download-segments"
        )

    # Load segments
    segments = []
    for path in sorted(segments_dir.glob("*.gpx")):
        name = path.stem
        if args.segment_prefix and not name.startswith(args.segment_prefix):
            continue
        points, gpx_name, root = read_gpx_points(path)
        if not points:
            continue
        seg_name = gpx_name or name

        # Calculate segment metrics
        distance_m = calculate_distance_m(points)
        ascent, descent = calculate_elevation_gain_loss(points)

        segments.append(
            {
                "name": seg_name,
                "path": str(path),
                "points": points,
                "distance_m": distance_m,
                "ascent_m": ascent,
                "descent_m": descent,
            }
        )

    if not segments:
        raise SystemExit("No segment GPX files found with the given prefix.")

    start, end = resolve_range(args)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    user = get_credential("garmin", "username")
    passwd = get_credential("garmin", "password")
    client = Garmin(user, passwd)
    client.login()

    activities = fetch_activities(client, start_date, end_date)
    if args.limit_activities:
        activities = activities[: args.limit_activities]

    results: dict[str, _SegResult] = {
        s["name"]: {
            "best_seconds": None,
            "activity": None,
            "matches": 0,
            "all": [],
            "distance_m": s["distance_m"],
            "ascent_m": s["ascent_m"],
            "descent_m": s["descent_m"],
        }
        for s in segments
    }

    for act in activities:
        at = act.get("activityType", {})
        typekey = at.get("typeKey") or at.get("parentTypeKey")
        if not want_activity(typekey, args.activity):
            continue
        activity_id = act.get("activityId")
        if not activity_id:
            continue
        # Download GPX for this activity
        try:
            gpx_data = client.download_activity(
                activity_id, dl_fmt=Garmin.ActivityDownloadFormat.GPX
            )
        except Exception:
            continue
        if isinstance(gpx_data, bytes):
            gpx_text = gpx_data.decode("utf-8", errors="ignore")
        else:
            gpx_text = str(gpx_data)

        # Parse activity points
        try:
            root = ET.fromstring(gpx_text)
        except Exception:
            continue
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
            ele = (
                float(ele_el.text)
                if ele_el is not None and ele_el.text
                else None
            )
            points.append((float(lat), float(lon), t, ele))

        if not points:
            continue

        for seg in segments:
            match = match_segment(points, seg["points"], args.tolerance)
            if not match:
                continue
            duration, start_idx, end_idx = match
            name = seg["name"]
            res = results[name]
            res["matches"] += 1

            # Calculate average speed (km/h)
            distance_km = seg["distance_m"] / 1000.0
            duration_h = duration / 3600.0
            avg_speed_kmh = distance_km / duration_h if duration_h > 0 else 0

            entry = {
                "id": activity_id,
                "name": act.get("activityName"),
                "startTimeLocal": act.get("startTimeLocal"),
                "duration_s": duration,
                "avg_speed_kmh": avg_speed_kmh,
            }
            res["all"].append(entry)
            if res["best_seconds"] is None or duration < res["best_seconds"]:
                res["best_seconds"] = duration
                res["activity"] = entry

    def render_org(out_dict: dict) -> str:
        """Render KOM results as org-mode formatted text.

        Args:
            out_dict: Dict mapping segment names to result dicts.

        Returns:
            Org-mode formatted string with segment sections and tables.
        """
        lines = ["", "* Segment KOMs", ""]
        for segment_name in sorted(out_dict.keys()):
            data = out_dict[segment_name]
            lines.append(f"** {segment_name}")
            distance_km = data.get("distance_m", 0) / 1000.0
            ascent_m = data.get("ascent_m", 0)
            descent_m = data.get("descent_m", 0)
            lines.append(f"- Distance: {distance_km:.2f} km")
            lines.append(f"- Ascent: {ascent_m:.0f} m")
            lines.append(f"- Descent: {descent_m:.0f} m")
            if data.get("best"):
                lines.append(f"- Best: {data['best']} (KOM)")
                lines.append(f"- Matches: {data['matches']} times")
            else:
                lines.append("- Best: no matches")
            lines.append("")
            lines.append("| Rank | Time | Avg speed | Date |")
            lines.append("|------|------|-----------|------|")
            for idx, activity in enumerate(data.get("top", [])[:10], 1):
                time_hms = format_duration(activity["duration_s"])
                date = (activity.get("startTimeLocal") or "").split()[0]
                avg_speed = activity.get("avg_speed_kmh", 0)
                lines.append(
                    f"| {idx} | {time_hms} | {avg_speed:.1f} km/h | {date} |"
                )
            lines.append("")
        return "\n".join(lines)

    # Output
    out = {}
    for name, res in results.items():
        if res["best_seconds"] is None:
            out[name] = {
                "best": None,
                "matches": 0,
                "top": [],
                "distance_m": res["distance_m"],
                "ascent_m": res["ascent_m"],
                "descent_m": res["descent_m"],
            }
        else:
            top = sorted(res["all"], key=lambda x: x["duration_s"])[: args.top]
            out[name] = {
                "best": format_duration(res["best_seconds"]),
                "best_seconds": res["best_seconds"],
                "activity": res["activity"],
                "matches": res["matches"],
                "top": top,
                "distance_m": res["distance_m"],
                "ascent_m": res["ascent_m"],
                "descent_m": res["descent_m"],
            }

    if args.format == "org":
        content = render_org(out)
    else:
        content = json.dumps(out, indent=2)

    if args.output:
        Path(args.output).write_text(content)
    else:
        print(content)
