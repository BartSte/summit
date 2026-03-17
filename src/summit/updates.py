"""
Check if there are new Garmin activities or Komoot segments that need updating.
Compares cache state against live data.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from summit.credentials import get_credential, get_garmin_client

logger = logging.getLogger(__name__)


class _KomootInfo(TypedDict):
    cached_segments: int
    planned_segments: int
    missing_in_cache: list[str]
    extra_in_cache: list[str]


try:
    from garminconnect import Garmin
    from komPYoot.api import API, TourOwner, TourType
except Exception as e:
    logger.error(
        "Missing dependencies (%s). Install with: pip install garminconnect komPYoot", e)
    sys.exit(1)


def check_garmin_activities() -> tuple[dict | None, bool | None, str | None]:
    """Check whether there are new Garmin activities since the last cache.

    Returns:
        Tuple of (info, is_new, error). info contains latest_id,
        latest_time, last_cached_time, and id_in_cache keys.
        is_new is True if an uncached activity is found.
        error contains an error message string on failure, else None.
    """
    cache_dir = Path("/home/barts/.cache/garmin/tracks")

    # Get most recent cached activity
    cached_files: list[Path] = []
    if cache_dir.exists():
        cached_files = sorted(cache_dir.glob("*.json"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        if cached_files:
            last_cached = cached_files[0].stat().st_mtime
            last_cached_dt = datetime.fromtimestamp(last_cached)
        else:
            last_cached_dt = None
    else:
        last_cached_dt = None

    # Get latest activity from Garmin
    try:
        client = get_garmin_client()

        recent = client.get_activities(start=0, limit=1)
        if not recent or not isinstance(recent, list):
            return None, None, None

        activity = recent[0]
        activity_time_str = activity.get(
            "startTimeLocal") or activity.get("startTimeGMT")
        activity_dt = datetime.fromisoformat(
            activity_time_str.replace("Z", "+00:00"))
        activity_id = activity.get("activityId")

        # Check if new: ID-based check (timestamp comparison fails when activity
        # is uploaded after the cache run but has an earlier start time).
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


def check_komoot_segments() -> tuple[_KomootInfo | None, bool | None, str | None]:
    """Check whether Komoot segment cache is in sync with planned tours.

    Returns:
        Tuple of (info, is_new, error). info contains cached and planned
        segment counts. is_new is True if cache differs from planned tours.
        error contains an error message string on failure, else None.
    """
    cache_dir = Path("/home/barts/.cache/garmin/segments")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Get cached segments
    cached_files = set(p.stem for p in cache_dir.glob("SEG-*.gpx"))

    # Get planned tours from Komoot
    try:
        user = get_credential("komoot", "username")
        passwd = get_credential("komoot", "password")
        api = API()
        ok = api.login(user, passwd)
        if not ok:
            return None, None, "Komoot login failed"

        tours = api.get_user_tours_list(
            tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
        seg_tours = [t for t in tours if (
            t.get("name") or "").startswith("SEG-")]

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


def main() -> None:
    """Check for new Garmin activities and Komoot segments."""
    import argparse
    parser = argparse.ArgumentParser(description="Check for updates")
    parser.add_argument("--quiet", action="store_true",
                        help="Quiet mode: exit code 1 if updates needed, 0 otherwise")
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
    logger.info("=" * 70)
    logger.info("Checking for updates...")
    logger.info("=" * 70)

    # Garmin
    logger.info("\n[Garmin Activities]")
    if garmin_err:
        logger.error("✗ Garmin error: %s", garmin_err)
    elif garmin_info:
        logger.info("  Latest activity:  %s (id: %s)",
                    garmin_info['latest_time'], garmin_info['latest_id'])
        logger.info("  Last cached:      %s", garmin_info['last_cached_time'])
        if garmin_new:
            logger.info("  → New activities detected ✓")
        else:
            logger.info("  → No new activities")

    # Komoot
    logger.info("\n[Komoot Segments]")
    if komoot_err:
        logger.error("✗ Komoot error: %s", komoot_err)
    elif komoot_info:
        logger.info("  Cached segments:  %d", komoot_info['cached_segments'])
        logger.info("  Planned segments: %d", komoot_info['planned_segments'])
        if komoot_info['missing_in_cache']:
            logger.info("  Missing in cache: %s", ', '.join(
                komoot_info['missing_in_cache'][:3]))
            if len(komoot_info['missing_in_cache']) > 3:
                logger.info("                   ... and %d more",
                            len(komoot_info['missing_in_cache']) - 3)
        if komoot_info['extra_in_cache']:
            logger.info("  Extra in cache:   %s", ', '.join(
                komoot_info['extra_in_cache'][:3]))
        if komoot_new:
            logger.info("  → New/modified segments detected ✓")
        else:
            logger.info("  → Segments up-to-date")

    logger.info("\n" + "=" * 70)

    if updates_needed:
        logger.info(
            "⚠ Updates available! Run: summit update  (or: summit auto-update)")
    else:
        logger.info("✓ All caches are up-to-date")

    logger.info("=" * 70)


if __name__ == "__main__":
    main()
