"""PHASE 2: MAINTAIN — Update caches with new activities/segments.

Refreshes Garmin activity cache and Komoot segments, then regenerates
personal records.
"""

import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from summit.cli.generate import main as generate_main

logger = logging.getLogger(__name__)


def main() -> None:
    """Refresh caches and regenerate personal records interactively."""
    logger.info("================================")
    logger.info("PHASE 2: MAINTAIN")
    logger.info("================================")

    # Check for updates first (verbose mode)
    logger.info("Checking for updates...")
    subprocess.run(
        [sys.executable, "-m", "summit.updates"],
        check=False,  # non-zero exit is expected when updates are available
    )

    reply = input("Update caches? (y/n) ").strip().lower()
    if reply not in ("y", "yes"):
        sys.exit(1)

    start_date = (datetime.now() - timedelta(days=6 * 365)
                  ).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    # Step 1: Update Garmin activity cache (last 6 months)
    logger.info(">>> Step 1: Updating Garmin activity cache...")
    logger.info(
        "    (Fetches cycling and running activities from past 6 months)"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "summit.prs",
            "--activity",
            "all",
            "--range",
            "last_6_months",
            "--output",
            "/tmp/update_cache.json",
        ],
        check=True,
    )
    logger.info("    ✓ Activity cache updated (cycling + running)")

    # Step 2: Update Komoot segments
    logger.info(">>> Step 2: Updating Komoot segment cache...")
    subprocess.run(
        [sys.executable, "-m", "summit.komoot", "download-segments"],
        check=True,
    )
    logger.info("    ✓ Segment cache updated")

    # Step 3: Regenerate segment KOMs (full historical cache)
    logger.info(">>> Step 3: Regenerating segment KOMs...")
    logger.info("    (Using full historical cache)")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "summit.kom",
            "--start",
            start_date,
            "--end",
            end_date,
            "--output",
            "/tmp/kom_results_full.json",
        ],
        check=True,
    )
    logger.info("    ✓ KOM detection complete")

    # Step 4: Generate personal records
    logger.info(
        ">>> Step 4: Generating personal records "
        "(cycling + running + segment KOMs)..."
    )
    generate_main()
    logger.info("    ✓ Personal records generated")

    # Step 5: Sync to Dropbox
    logger.info(">>> Step 5: Syncing to Dropbox...")
    subprocess.run(
        [
            "rclone",
            "sync",
            "--ignore-times",
            str(Path.home() / "dropbox" / "org"),
            "dropbox:/org/",
        ],
        check=True,
    )
    logger.info("    ✓ Synced to Dropbox")

    logger.info("")
    logger.info("================================")
    logger.info("UPDATE COMPLETE ✓")
    logger.info("================================")
    logger.info("")
    logger.info("Output: ~/dropbox/org/personal_records.org (updated & synced)")
