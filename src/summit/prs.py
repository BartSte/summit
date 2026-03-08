#!/usr/bin/env python3
"""
Compute personal cycling PRs for fixed distances (e.g., 5/10/40 km)
from Garmin activities, reusing the /kom track cache.
"""
import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

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

DEFAULT_CACHE_DIR = Path("/home/barts/.cache/garmin")
TRACKS_DIRNAME = "tracks"


def parse_args():
    p = argparse.ArgumentParser(description="Compute cycling PRs for fixed distances using cached tracks")
    p.add_argument("--distances", default="5,10,40", help="Comma-separated distances in km (e.g., 5,10,40)")
    p.add_argument("--activity", choices=["cycling", "running", "all"], default="cycling")
    p.add_argument("--title", default=None, help="Section title for org output")
    p.add_argument("--range", choices=["this_year", "last_2_years", "last_year", "last_6_months"], default="this_year")
    p.add_argument("--start", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--end", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--limit-activities", type=int, default=None, help="Limit number of activities (debug)")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Cache directory (default: /skills/kom/cache)")
    p.add_argument("--cache-spacing", type=float, default=5.0, help="Downsample spacing for cached tracks (meters)")
    p.add_argument("--top", type=int, default=10, help="Number of fastest results to include per distance")
    p.add_argument("--time-mode", choices=["elapsed", "moving"], default="elapsed", help="Use elapsed or moving time")
    p.add_argument("--moving-threshold-m", type=float, default=1.0, help="Distance threshold below which time is ignored in moving mode")
    p.add_argument("--output", default=None, help="Write output to file")
    p.add_argument("--format", choices=["json", "org"], default="json", help="Output format (default: json)")
    return p.parse_args()


def resolve_range(args):
    now = datetime.now()
    if args.start and args.end:
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end)
    elif args.range == "this_year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
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


def want_activity(type_key, activity):
    if activity == "all":
        return True
    if activity == "cycling":
        return type_key in CYCLING_TYPES or (type_key and "bike" in type_key)
    if activity == "running":
        return type_key in {"running", "trail_running", "treadmill_running", "track_running"} or (type_key and "run" in type_key)
    return False


def parse_time(t):
    if t is None:
        return None
    t = t.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t)
    except Exception:
        return None


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def downsample_activity(points, min_spacing_m=5.0):
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


def parse_gpx_text(gpx_text):
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
        points.append((float(lat), float(lon), t, ele))
    return points


def ensure_cache_dirs(cache_dir: Path):
    (cache_dir / TRACKS_DIRNAME).mkdir(parents=True, exist_ok=True)


def cache_track_path(cache_dir: Path, activity_id):
    return cache_dir / TRACKS_DIRNAME / f"{activity_id}.json"


def save_cached_track(cache_dir: Path, activity_id, points):
    rows = []
    for p in points:
        t = p[2] if len(p) > 2 else None
        ele = p[3] if len(p) > 3 else None
        rows.append([p[0], p[1], t.isoformat() if t else None, ele])
    cache_track_path(cache_dir, activity_id).write_text(json.dumps(rows))


def load_cached_track(cache_dir: Path, activity_id):
    path = cache_track_path(cache_dir, activity_id)
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    points = []
    for lat, lon, t, ele in rows:
        points.append((lat, lon, parse_time(t) if t else None, ele))
    return points


def fetch_activities(client, start_date, end_date):
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59)
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


def compute_best_for_distance(points, distance_m, time_mode="elapsed", moving_threshold_m=1.0):
    # Filter points with time
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
        if time_mode == "moving" and d < moving_threshold_m:
            dt = 0.0
        cumdist.append(cumdist[-1] + d)
        cumtime.append(cumtime[-1] + dt)

    best = None  # (duration_s, start_idx)
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
            best = (duration, i)
    if best is None:
        return None
    duration_s, start_idx = best
    start_time = pts[start_idx][2]
    return {
        "duration_s": duration_s,
        "start_time": start_time,
    }


def main():
    args = parse_args()
    if Garmin is None:
        raise SystemExit("garminconnect not installed. Activate venv and pip install garminconnect")

    distances_km = [float(x.strip()) for x in args.distances.split(",") if x.strip()]
    distances_m = [d * 1000.0 for d in distances_km]

    cache_dir = Path(args.cache_dir)
    ensure_cache_dirs(cache_dir)

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

    results = {str(d): [] for d in distances_km}

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
                gpx_data = client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.GPX)
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

        for dist_km, dist_m in zip(distances_km, distances_m):
            best = compute_best_for_distance(
                points_ds,
                dist_m,
                time_mode=args.time_mode,
                moving_threshold_m=args.moving_threshold_m,
            )
            if not best:
                continue
            duration = best["duration_s"]
            avg_kmh = (dist_km) / (duration / 3600.0) if duration > 0 else None
            entry = {
                "distance_km": dist_km,
                "duration_s": duration,
                "avg_kmh": avg_kmh,
                "activityId": activity_id,
                "activityName": act.get("activityName"),
                "startTimeLocal": act.get("startTimeLocal"),
                "segmentStartTime": best.get("start_time").isoformat() if best.get("start_time") else None,
            }
            results[str(dist_km)].append(entry)

    # Sort and keep top N
    for k in list(results.keys()):
        results[k] = sorted(results[k], key=lambda x: x["duration_s"])[: args.top]

    def render_org(results_dict: dict) -> str:
        title = args.title or ("Cycling PRs" if args.activity == "cycling" else "Running PRs")
        lines = [f"* {title}"]
        lines.append(f"- Time mode: {args.time_mode}")
        lines.append(f"- Distances: {', '.join(str(d) for d in distances_km)} km")
        for dist in distances_km:
            key = str(dist)
            lines.append(f"** {dist:.1f} km")
            rows = results_dict.get(key, [])
            if not rows:
                lines.append("- no results")
                continue
            headers = ["Rank", "Time", "Avg speed", "Date"]
            table_rows = []
            for i, r in enumerate(rows, 1):
                d = r["duration_s"]
                h = int(d // 3600)
                m = int((d % 3600) // 60)
                s = int(d % 60)
                time_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
                date = (r.get("startTimeLocal") or "").split()[0]  # Extract date only
                table_rows.append([
                    str(i),
                    time_str,
                    f"{(r.get('avg_kmh') or 0):.1f} km/h",
                    date,
                ])
            cols = list(zip(*([headers] + table_rows))) if table_rows else list(zip(*([headers])))
            widths = [max(len(str(cell)) for cell in col) for col in cols]
            def fmt_row(cells):
                return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)) + " |"
            lines.append(fmt_row(headers))
            lines.append("|" + "+".join("-" * (w + 2) for w in widths) + "|")
            for r in table_rows:
                lines.append(fmt_row(r))
        return "\n".join(lines) + "\n"

    if args.format == "org":
        content = render_org(results)
    else:
        content = json.dumps(results, indent=2)

    if args.output:
        Path(args.output).write_text(content)
    else:
        print(content)


if __name__ == "__main__":
    main()
