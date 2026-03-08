#!/usr/bin/env python3
"""
PHASE 1: SETUP — Build complete historical cache.
Collects 6 years of Garmin activities and all Komoot segments,
then computes initial personal records.
"""
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from summit.cli.generate import main as generate_main

logger = logging.getLogger(__name__)


def main():
    logger.info("================================")
    logger.info("PHASE 1: SETUP")
    logger.info("================================")
    logger.info("")
    logger.info("This will:")
    logger.info("1. Cache all Garmin cycling activities (past 6 years)")
    logger.info("2. Cache all Komoot segments (SEG- prefix)")
    logger.info("3. Compute personal records")
    logger.info("")

    reply = input("Continue? (y/n) ").strip().lower()
    if reply not in ("y", "yes"):
        sys.exit(1)

    start_date = (datetime.now() - timedelta(days=6 * 365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    # Step 1: Build Garmin activity cache (6 years)
    logger.info(">>> Step 1: Caching Garmin activities (past 6 years)...")
    logger.info("    This will download and cache GPX for all cycling and running activities.")
    logger.info("    (Can take 10-20 minutes depending on activity count)")
    logger.info("    Date range: %s to %s", start_date, end_date)
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "all",
            "--start", start_date,
            "--end", end_date,
            "--output", "/tmp/cache_build.json",
        ],
        check=True,
    )
    logger.info("    ✓ Activity cache built (cycling + running)")

    # Step 2: Download Komoot segments
    logger.info(">>> Step 2: Caching Komoot segments (SEG- prefix)...")
    subprocess.run(
        [sys.executable, "-m", "summit.komoot", "download-segments"],
        check=True,
    )
    logger.info("    ✓ Segment cache built")

    # Step 3: Detect segment KOMs
    logger.info(">>> Step 3: Detecting segment KOMs...")
    subprocess.run(
        [
            sys.executable, "-m", "summit.kom",
            "--start", start_date,
            "--end", end_date,
            "--output", "/tmp/kom_results_full.json",
        ],
        check=True,
    )
    logger.info("    ✓ KOM detection complete")

    # Step 3b: Generate personal records
    logger.info(">>> Step 3b: Generating personal records (cycling + running + segment KOMs)...")
    generate_main()
    logger.info("    ✓ Personal records generated")

    # Step 4: Sync to Dropbox
    logger.info(">>> Step 4: Syncing to Dropbox...")
    subprocess.run(
        ["rclone", "sync", str(Path.home() / "dropbox" / "org"), "dropbox:/org/"],
        check=True,
    )
    logger.info("    ✓ Synced to Dropbox")

    logger.info("")
    logger.info("================================")
    logger.info("SETUP COMPLETE ✓")
    logger.info("================================")
    logger.info("")
    logger.info("Output files:")
    logger.info("  ~/dropbox/org/personal_records.org (synced)")
    logger.info("")
    logger.info("Next: Use 'summit check' to detect when new activities/segments arrive,")
    logger.info("      then run 'summit update' to update.")


if __name__ == "__main__":
    main()
