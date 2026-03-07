#!/usr/bin/env python3
"""
Compute personal KOMs for user-defined segments from Garmin activities.

Segments are GPX files (from planned rides/routes). Only files with a given
prefix are treated as segments (default: "SEG - ").
"""
import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from garminconnect import Garmin
except Exception as e:
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


def parse_args():
    p = argparse.ArgumentParser(description="Compute personal KOMs for GPX-defined segments")
    p.add_argument("--segments-dir", default="/home/barts/.cache/garmin/segments", help="Directory containing segment GPX files (default: cache)")
    p.add_argument("--segment-prefix", default="SEG-", help="Only GPX files starting with this name are segments")
    p.add_argument("--tolerance", type=float, default=25.0, help="Matching tolerance in meters")
    p.add_argument("--activity", choices=["cycling", "all"], default="cycling")
    p.add_argument("--range", choices=["this_year", "last_2_years", "last_year", "last_6_months"], default="this_year")
    p.add_argument("--start", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--end", help="YYYY-MM-DD (overrides --range)")
    p.add_argument("--limit-activities", type=int, default=None, help="Limit number of activities (debug)")
    p.add_argument("--output", default=None, help="Write JSON output to file")
    p.add_argument("--top", type=int, default=10, help="Number of fastest matches to include")
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
    # meters
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def downsample_points(points, min_spacing_m=10.0):
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


def calculate_distance_m(points):
    """Calculate total distance in meters from points (lat, lon, ...)"""
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        total += haversine_m(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
    return total


def calculate_elevation_gain_loss(points):
    """Calculate ascent and descent in meters from points with elevation data"""
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


def read_gpx_points(path):
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
            ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
            points.append((float(lat), float(lon), t, ele))

    return points, name, root


def nearest_segment_index(lat, lon, seg_points):
    best_i = None
    best_d = None
    for i, (slat, slon) in enumerate(seg_points):
        d = haversine_m(lat, lon, slat, slon)
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d


def match_segment(activity_points, segment_points, tolerance_m):
    if len(activity_points) < 2 or len(segment_points) < 2:
        return None
    seg_points = downsample_points([(p[0], p[1]) for p in segment_points], min_spacing_m=10.0)
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
                nearest_i, nearest_d = nearest_segment_index(blat, blon, seg_points)
                if nearest_d is not None and nearest_d <= tolerance_m and nearest_i >= seg_i:
                    seg_i = nearest_i
                if haversine_m(blat, blon, end_pt[0], end_pt[1]) <= tolerance_m and seg_i >= len(seg_points) - 2:
                    duration = (btime - atime).total_seconds()
                    if duration > 0 and (best is None or duration < best[0]):
                        best = (duration, i, j)
                    break
    return best


def format_duration(seconds):
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def fetch_activities(client, start_date, end_date):
    # Page through recent activities and filter by date range.
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
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
                # we can stop once we are past the range (activities are returned newest-first)
                return acts
            if dt <= end_dt:
                acts.append(act)
        if len(batch) < limit:
            break
        offset += limit
    return acts


def main():
    args = parse_args()
    if Garmin is None:
        raise SystemExit("garminconnect not installed. Activate venv and pip install garminconnect")

    segments_dir = Path(args.segments_dir)
    if not segments_dir.exists():
        raise SystemExit(f"Segments directory not found: {segments_dir}\nDownload segments first with: komoot download-segments")

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

        segments.append({
            "name": seg_name,
            "path": str(path),
            "points": points,
            "distance_m": distance_m,
            "ascent_m": ascent,
            "descent_m": descent,
        })

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

    results = {
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
            gpx_data = client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.GPX)
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
            ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
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

    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2))
    else:
        for name, res in out.items():
            if res.get("best") is None:
                print(f"{name}: no matches")
            else:
                act = res.get("activity") or {}
                print(f"{name}: {res['best']} (matches: {res['matches']}, activity: {act.get('name')} @ {act.get('startTimeLocal')})")
                for i, t in enumerate(res.get("top", []), 1):
                    print(f"  {i:02d}. {format_duration(t['duration_s'])} | {t.get('startTimeLocal')} | {t.get('name')}")


if __name__ == "__main__":
    main()
