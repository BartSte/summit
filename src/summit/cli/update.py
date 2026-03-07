#!/usr/bin/env python3
"""
PHASE 2: MAINTAIN — Update caches with new activities/segments.
Refreshes Garmin activity cache and Komoot segments, then regenerates
personal records.
"""
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from summit.cli.generate import main as generate_main


def main():
    print("================================")
    print("PHASE 2: MAINTAIN")
    print("================================")
    print()

    # Check for updates first (verbose mode)
    print("Checking for updates...")
    subprocess.run(
        [sys.executable, "-m", "summit.updates"],
        check=False,  # non-zero exit is expected when updates are available
    )

    print()
    reply = input("Update caches? (y/n) ").strip().lower()
    print()
    if reply not in ("y", "yes"):
        sys.exit(1)

    start_date = (datetime.now() - timedelta(days=6 * 365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    # Step 1: Update Garmin activity cache (last 6 months)
    print()
    print(">>> Step 1: Updating Garmin activity cache...")
    print("    (Fetches cycling and running activities from past 6 months)")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "all",
            "--range", "last_6_months",
            "--output", "/tmp/update_cache.json",
        ],
        check=True,
    )
    print("    ✓ Activity cache updated (cycling + running)")

    # Step 2: Update Komoot segments
    print()
    print(">>> Step 2: Updating Komoot segment cache...")
    subprocess.run(
        [sys.executable, "-m", "summit.komoot", "download-segments"],
        check=True,
    )
    print("    ✓ Segment cache updated")

    # Step 3: Regenerate segment KOMs (full historical cache)
    print()
    print(">>> Step 3: Regenerating segment KOMs...")
    print("    (Using full historical cache)")
    subprocess.run(
        [
            sys.executable, "-m", "summit.kom",
            "--start", start_date,
            "--end", end_date,
            "--output", "/tmp/kom_results_full.json",
        ],
        check=True,
    )
    print("    ✓ KOM detection complete")

    # Step 4: Generate personal records
    print()
    print(">>> Step 4: Generating personal records (cycling + running + segment KOMs)...")
    generate_main()
    print("    ✓ Personal records generated")

    # Step 5: Sync to Dropbox
    print()
    print(">>> Step 5: Syncing to Dropbox...")
    subprocess.run(
        ["rclone", "sync", str(Path.home() / "dropbox" / "org"), "dropbox:/org/"],
        check=True,
    )
    print("    ✓ Synced to Dropbox")

    print()
    print("================================")
    print("UPDATE COMPLETE ✓")
    print("================================")
    print()
    print("Output files:")
    print("  ~/dropbox/org/personal_records.org (updated & synced)")
    print()


if __name__ == "__main__":
    main()
