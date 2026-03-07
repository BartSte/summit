#!/usr/bin/env python3
"""
Check if there are new Garmin activities or Komoot segments that need updating.
Compares cache state against live data.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from garminconnect import Garmin
    from komPYoot.api import API, TourOwner, TourType
except Exception as e:
    print(f"Error: Missing dependencies ({e})")
    print("Install with: pip install garminconnect komPYoot")
    sys.exit(1)


def rbw_get(service, field=None):
    cmd = ["rbw", "get"]
    if field:
        cmd += ["--field", field]
    cmd += [service]
    return subprocess.check_output(cmd, text=True).strip()


def check_garmin_activities():
    """Check if there are new Garmin activities since last cache."""
    cache_dir = Path("/home/barts/.cache/garmin/tracks")
    
    # Get most recent cached activity
    if cache_dir.exists():
        cached_files = sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if cached_files:
            last_cached = cached_files[0].stat().st_mtime
            last_cached_dt = datetime.fromtimestamp(last_cached)
        else:
            last_cached_dt = None
    else:
        last_cached_dt = None
    
    # Get latest activity from Garmin
    try:
        user = rbw_get("Garmin Connect", "username")
        passwd = rbw_get("Garmin Connect")
        client = Garmin(user, passwd)
        client.login()
        
        recent = client.get_activities(start=0, limit=1)
        if not recent:
            return None, None, False
        
        activity = recent[0]
        activity_time_str = activity.get("startTimeLocal") or activity.get("startTimeGMT")
        activity_dt = datetime.fromisoformat(activity_time_str.replace("Z", "+00:00"))
        activity_id = activity.get("activityId")
        
        # Check if new: ID-based check (timestamp comparison fails when activity
        # is uploaded after the cache run but has an earlier start time)
        latest_id_cached = str(cached_files[0].stem) if cached_files else None
        id_in_cache = (cache_dir / f"{activity_id}.json").exists()
        is_new = (last_cached_dt is None) or not id_in_cache
        
        return {
            "latest_id": activity_id,
            "latest_time": activity_time_str,
            "last_cached_time": last_cached_dt.isoformat() if last_cached_dt else "none",
            "id_in_cache": id_in_cache,
        }, is_new, None
    except Exception as e:
        return None, None, str(e)


def check_komoot_segments():
    """Check if there are new/modified Komoot segments since last cache."""
    cache_dir = Path("/home/barts/.cache/garmin/segments")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Get cached segments
    cached_files = set(p.stem for p in cache_dir.glob("SEG-*.gpx"))
    
    # Get planned tours from Komoot
    try:
        user = rbw_get("Komoot", "username")
        passwd = rbw_get("Komoot")
        api = API()
        ok = api.login(user, passwd)
        if not ok:
            return None, None, "Komoot login failed"
        
        tours = api.get_user_tours_list(tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
        seg_tours = [t for t in tours if (t.get("name") or "").startswith("SEG-")]
        
        planned_names = set(t.get("name") for t in seg_tours)
        
        # Check for differences
        missing_in_cache = planned_names - cached_files
        extra_in_cache = cached_files - planned_names
        
        is_new = bool(missing_in_cache or extra_in_cache)
        
        return {
            "cached_segments": len(cached_files),
            "planned_segments": len(seg_tours),
            "missing_in_cache": sorted(list(missing_in_cache)),
            "extra_in_cache": sorted(list(extra_in_cache)),
        }, is_new, None
    except Exception as e:
        return None, None, str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check for updates")
    parser.add_argument("--quiet", action="store_true", help="Quiet mode: exit code 1 if updates needed, 0 otherwise")
    args = parser.parse_args()
    
    # Check Garmin
    garmin_info, garmin_new, garmin_err = check_garmin_activities()
    
    # Check Komoot
    komoot_info, komoot_new, komoot_err = check_komoot_segments()
    
    # Summary
    updates_needed = (garmin_new or False) or (komoot_new or False)
    
    if args.quiet:
        # Quiet mode: exit with code 1 if updates needed
        sys.exit(1 if updates_needed else 0)
    
    # Verbose output
    print("=" * 70)
    print("Checking for updates...")
    print("=" * 70)
    
    # Check Garmin
    print("\n[Garmin Activities]")
    if garmin_err:
        print(f"✗ Error: {garmin_err}")
    elif garmin_info:
        print(f"  Latest activity:  {garmin_info['latest_time']} (id: {garmin_info['latest_id']})")
        print(f"  Last cached:      {garmin_info['last_cached_time']}")
        if garmin_new:
            print(f"  → New activities detected ✓")
        else:
            print(f"  → No new activities")
    
    # Check Komoot
    print("\n[Komoot Segments]")
    if komoot_err:
        print(f"✗ Error: {komoot_err}")
    elif komoot_info:
        print(f"  Cached segments:  {komoot_info['cached_segments']}")
        print(f"  Planned segments: {komoot_info['planned_segments']}")
        if komoot_info['missing_in_cache']:
            print(f"  Missing in cache: {', '.join(komoot_info['missing_in_cache'][:3])}")
            if len(komoot_info['missing_in_cache']) > 3:
                print(f"                   ... and {len(komoot_info['missing_in_cache']) - 3} more")
        if komoot_info['extra_in_cache']:
            print(f"  Extra in cache:   {', '.join(komoot_info['extra_in_cache'][:3])}")
        if komoot_new:
            print(f"  → New/modified segments detected ✓")
        else:
            print(f"  → Segments up-to-date")
    
    print("\n" + "=" * 70)
    
    if updates_needed:
        print("⚠ Updates available!")
        print("\nRun to update:")
        print("  ./update_cache.sh")
        print("  # or for auto mode:")
        print("  ./auto_update.sh")
    else:
        print("✓ All caches are up-to-date")
    
    print("=" * 70)


if __name__ == "__main__":
    main()
