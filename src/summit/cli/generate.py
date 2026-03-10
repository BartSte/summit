#!/usr/bin/env python3
"""
Generate Personal Records (Cycling + Running + Segment KOMs).
Output: ~/dropbox/org/personal_records.org

Phase: called by setup, update, and auto_update after cache is populated.
"""
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def main():
    start_date = (datetime.now() - timedelta(days=6 * 365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    output_file = Path.home() / "dropbox" / "org" / "personal_records.org"

    logger.info(">>> Generating personal records...")
    logger.info("    Date range: %s to %s", start_date, end_date)

    # Step 1: Cycling PRs (write fresh file)
    logger.info(">>> Step 1: Cycling PRs (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 km)...")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "cycling",
            "--distances", "1,5,10,20,30,40,50,60,70,80,90,100",
            "--format", "org",
            "--start", start_date,
            "--end", end_date,
            "--output", str(output_file),
        ],
        check=True,
    )
    logger.info("    ✓ Cycling PRs written to %s", output_file)

    # Step 2: Running PRs → temp file, then append
    logger.info(">>> Step 2: Running PRs (1, 5, 10 km)...")
    running_tmp = Path("/tmp/running_prs.org")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "running",
            "--distances", "1,5,10",
            "--title", "Running PRs",
            "--format", "org",
            "--start", start_date,
            "--end", end_date,
            "--output", str(running_tmp),
        ],
        check=True,
    )
    with open(output_file, "a") as f:
        f.write("\n")
        f.write(running_tmp.read_text())
    running_tmp.unlink(missing_ok=True)
    logger.info("    ✓ Running PRs appended to %s", output_file)

    # Step 3: Segment KOMs (if available)
    kom_json = Path("/tmp/kom_results_full.json")
    if kom_json.exists():
        logger.info(">>> Step 3: Appending Segment KOMs...")
        kom_tmp = Path("/tmp/kom_results.org")
        subprocess.run(
            [
                sys.executable, "-m", "summit.org",
                str(kom_json),
                "--format", "org",
                "--output", str(kom_tmp),
            ],
            check=True,
        )
        with open(output_file, "a") as f:
            f.write("\n")
            f.write(kom_tmp.read_text())
        kom_tmp.unlink(missing_ok=True)
        logger.info("    ✓ Segment KOMs appended")
    else:
        logger.info(">>> Step 3: No segment KOMs found (skipping)")

    line_count = len(output_file.read_text().splitlines())
    logger.info("✓ Personal records complete — %s (%d lines)", output_file, line_count)


if __name__ == "__main__":
    main()
