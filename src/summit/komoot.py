"""Komoot helper CLI using komPYoot + direct API PATCH.

Usage examples:
  komoot list-planned
  komoot rename --id 123 --name "New Name"
  komoot bulk-prefix --old "LE-" --new "L-"
  komoot download-segments --prefix "SEG-" --cache-dir /home/barts/.cache/garmin/segments
"""

import argparse
import datetime
import logging
from pathlib import Path

import requests
from komPYoot.api import API, TourOwner, TourType

from summit.credentials import get_credential

logger = logging.getLogger(__name__)


API_BASE = "https://api.komoot.de/v007/tours"


def login() -> API:
    """Authenticate with Komoot and return the API client.

    Returns:
        Authenticated komPYoot API instance.

    Raises:
        RuntimeError: If login fails.
    """
    email = get_credential("komoot", "username")
    password = get_credential("komoot", "password")
    api = API()
    ok = api.login(email, password)
    if not ok:
        raise RuntimeError("Komoot login failed")
    return api


def parse_date(s: str | None) -> datetime.datetime | None:
    """Parse an ISO 8601 date string to a datetime, or return None.

    Args:
        s: Date string, possibly ending in ``'Z'``, or None.

    Returns:
        Parsed datetime, or None if input is None or unparseable.
    """
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def list_planned(api: API) -> list[dict]:
    """List planned tours sorted by date descending and print a summary.

    Args:
        api: Authenticated komPYoot API instance.

    Returns:
        List of planned tour dicts, newest first.
    """
    tours = api.get_user_tours_list(
        tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
    rows: list[tuple[datetime.datetime | None, dict]] = []
    for t in tours:
        rows.append((parse_date(t.get("date")), t))
    rows.sort(key=lambda x: x[0] or datetime.datetime.min, reverse=True)

    for d, t in rows:
        date_str = d.date().isoformat() if d else t.get("date")
        dist_km = (t.get("distance") or 0) / 1000.0
        print(
            f"{date_str} | {t.get('name')} | "
            f"{dist_km:.1f} km | {t.get('sport')} | id {t.get('id')}"
        )
    return [t for _, t in rows]


def rename_tour(api: API, tour_id: int, new_name: str) -> None:
    """Rename a Komoot tour by ID using the REST API.

    Args:
        api: Authenticated komPYoot API instance.
        tour_id: Numeric Komoot tour ID.
        new_name: New name to assign to the tour.

    Raises:
        RuntimeError: If the PATCH request fails.
    """
    uid = api.user_details["user_id"]
    token = api.user_details["token"]
    r = requests.patch(
        f"{API_BASE}/{tour_id}", json={"name": new_name}, auth=(uid, token)
    )
    if r.status_code != 200:
        raise RuntimeError(f"Rename failed: {r.status_code} {r.text[:200]}")


def bulk_prefix(api: API, old: str, new: str) -> list[tuple]:
    """Rename all planned tours whose name starts with a given prefix.

    Args:
        api: Authenticated komPYoot API instance.
        old: Existing prefix to match and replace.
        new: Replacement prefix.

    Returns:
        List of (tour_id, old_name, new_name) tuples for renamed tours.

    Raises:
        RuntimeError: If any rename request fails.
    """
    tours = api.get_user_tours_list(
        tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
    uid = api.user_details["user_id"]
    token = api.user_details["token"]
    renamed = []
    for t in tours:
        name = t.get("name")
        if name and name.startswith(old):
            new_name = new + name[len(old):]
            tour_id = t.get("id")
            r = requests.patch(
                f"{API_BASE}/{tour_id}",
                json={"name": new_name},
                auth=(uid, token),
            )
            if r.status_code == 200:
                renamed.append((tour_id, name, new_name))
            else:
                raise RuntimeError(
                    f"Rename failed for {tour_id}: "
                    f"{r.status_code} {r.text[:200]}"
                )
    return renamed


def download_segments(api: API, prefix: str, cache_dir: str) -> list[tuple]:
    """Download GPX for planned tours matching a prefix and cache locally.

    Args:
        api: Authenticated komPYoot API instance.
        prefix: Tour name prefix to filter (e.g. ``'SEG-'``).
        cache_dir: Directory path to save downloaded GPX files.

    Returns:
        List of (tour_id, name, filepath) tuples for downloaded tours.
    """
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    tours = api.get_user_tours_list(
        tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
    downloaded = []

    for t in tours:
        name = t.get("name")
        if not name or not name.startswith(prefix):
            continue

        tour_id = t.get("id")
        filename = f"{name}.gpx"
        filepath = cache_path / filename

        try:
            api.download_tour_gpx(tour_id, cache_dir)
            # komPYoot saves as {name}.gpx in the target directory
            downloaded.append((tour_id, name, str(filepath)))
            logger.info("✓ %s (id %s)", name, tour_id)
        except Exception as e:
            logger.error("✗ %s (id %s): %s", name, tour_id, e)

    return downloaded


def main() -> None:
    """Dispatch Komoot helper subcommands (list, rename, download)."""
    parser = argparse.ArgumentParser(description="Komoot helper CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-planned", help="List planned (saved) tours")

    p_rename = sub.add_parser("rename", help="Rename a tour by id")
    p_rename.add_argument("--id", type=int, required=True)
    p_rename.add_argument("--name", required=True)

    p_bulk = sub.add_parser("bulk-prefix", help="Rename tours by prefix")
    p_bulk.add_argument("--old", required=True)
    p_bulk.add_argument("--new", required=True)

    p_download = sub.add_parser(
        "download-segments", help="Download GPX for tours matching prefix")
    p_download.add_argument("--prefix", default="SEG-",
                            help="Tour name prefix (default: SEG-)")
    p_download.add_argument(
        "--cache-dir",
        default="/home/barts/.cache/garmin/segments",
        help="Cache directory for GPX files",
    )

    args = parser.parse_args()
    api = login()

    if args.cmd == "list-planned":
        list_planned(api)
    elif args.cmd == "rename":
        rename_tour(api, args.id, args.name)
        logger.info("Renamed %s -> %s", args.id, args.name)
    elif args.cmd == "bulk-prefix":
        renamed = bulk_prefix(api, args.old, args.new)
        logger.info("Renamed %d tours", len(renamed))
        for tid, old, new in renamed:
            logger.info("  %s: %s -> %s", tid, old, new)
    elif args.cmd == "download-segments":
        downloaded = download_segments(api, args.prefix, args.cache_dir)
        logger.info("Downloaded %d segments to %s",
                    len(downloaded), args.cache_dir)


if __name__ == "__main__":
    main()
