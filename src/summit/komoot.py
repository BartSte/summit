#!/usr/bin/env python3
"""Komoot helper CLI using komPYoot + direct API PATCH.

Usage examples:
  komoot list-planned
  komoot rename --id 123 --name "New Name"
  komoot bulk-prefix --old "LE-" --new "L-"
  komoot download-segments --prefix "SEG-" --cache-dir /home/barts/.cache/garmin/segments
"""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import requests
from komPYoot.api import API, TourOwner, TourType

API_BASE = "https://api.komoot.de/v007/tours"


def rbw_get(field: str | None = None) -> str:
    cmd = ["rbw", "get"]
    if field:
        cmd += ["--field", field]
    cmd += ["Komoot"]
    return subprocess.check_output(cmd, text=True).strip()


def login() -> API:
    email = rbw_get("username")
    password = rbw_get(None)
    api = API()
    ok = api.login(email, password)
    if not ok:
        raise RuntimeError("Komoot login failed")
    return api


def parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def list_planned(api: API) -> List[dict]:
    tours = api.get_user_tours_list(tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
    rows: List[Tuple[datetime.datetime | None, dict]] = []
    for t in tours:
        rows.append((parse_date(t.get("date")), t))
    rows.sort(key=lambda x: x[0] or datetime.datetime.min, reverse=True)

    for d, t in rows:
        date_str = d.date().isoformat() if d else t.get("date")
        dist_km = (t.get("distance") or 0) / 1000.0
        print(f"{date_str} | {t.get('name')} | {dist_km:.1f} km | {t.get('sport')} | id {t.get('id')}")
    return [t for _, t in rows]


def rename_tour(api: API, tour_id: int, new_name: str) -> None:
    uid = api.user_details["user_id"]
    token = api.user_details["token"]
    r = requests.patch(f"{API_BASE}/{tour_id}", json={"name": new_name}, auth=(uid, token))
    if r.status_code != 200:
        raise RuntimeError(f"Rename failed: {r.status_code} {r.text[:200]}")


def bulk_prefix(api: API, old: str, new: str) -> List[tuple]:
    tours = api.get_user_tours_list(tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
    uid = api.user_details["user_id"]
    token = api.user_details["token"]
    renamed = []
    for t in tours:
        name = t.get("name")
        if name and name.startswith(old):
            new_name = new + name[len(old):]
            tour_id = t.get("id")
            r = requests.patch(f"{API_BASE}/{tour_id}", json={"name": new_name}, auth=(uid, token))
            if r.status_code == 200:
                renamed.append((tour_id, name, new_name))
            else:
                raise RuntimeError(f"Rename failed for {tour_id}: {r.status_code} {r.text[:200]}")
    return renamed


def download_segments(api: API, prefix: str, cache_dir: str) -> List[tuple]:
    """Download GPX for planned tours matching prefix and cache locally."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    tours = api.get_user_tours_list(tour_type=TourType.PLANNED, tour_owner=TourOwner.SELF)
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
            print(f"✓ {name} (id {tour_id})")
        except Exception as e:
            print(f"✗ {name} (id {tour_id}): {e}")

    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Komoot helper CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-planned", help="List planned (saved) tours")

    p_rename = sub.add_parser("rename", help="Rename a tour by id")
    p_rename.add_argument("--id", type=int, required=True)
    p_rename.add_argument("--name", required=True)

    p_bulk = sub.add_parser("bulk-prefix", help="Rename tours by prefix")
    p_bulk.add_argument("--old", required=True)
    p_bulk.add_argument("--new", required=True)

    p_download = sub.add_parser("download-segments", help="Download GPX for tours matching prefix")
    p_download.add_argument("--prefix", default="SEG-", help="Tour name prefix (default: SEG-)")
    p_download.add_argument("--cache-dir", default="/home/barts/.cache/garmin/segments", help="Cache directory for GPX files")

    args = parser.parse_args()
    api = login()

    if args.cmd == "list-planned":
        list_planned(api)
    elif args.cmd == "rename":
        rename_tour(api, args.id, args.name)
        print(f"Renamed {args.id} -> {args.name}")
    elif args.cmd == "bulk-prefix":
        renamed = bulk_prefix(api, args.old, args.new)
        print(f"RENAMED {len(renamed)}")
        for tid, old, new in renamed:
            print(f"{tid}: {old} -> {new}")
    elif args.cmd == "download-segments":
        downloaded = download_segments(api, args.prefix, args.cache_dir)
        print(f"\nDOWNLOADED {len(downloaded)} segments to {args.cache_dir}")


if __name__ == "__main__":
    main()
