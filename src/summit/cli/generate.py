#!/usr/bin/env python3
"""
Generate Personal Records (Cycling + Running + Segment KOMs).
Output: ~/dropbox/org/personal_records.org

Phase: called by setup, update, and auto_update after cache is populated.
"""
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def main():
    start_date = (datetime.now() - timedelta(days=6 * 365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    output_file = Path.home() / "dropbox" / "org" / "personal_records.org"

    print(">>> Generating personal records...")
    print(f"    Date range: {start_date} to {end_date}")
    print()

    # Step 1: Cycling PRs (write fresh file)
    print(">>> Step 1: Cycling PRs (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 km)...")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "cycling",
            "--distances", "1,5,10,20,30,40,50,60,70,80,90,100",
            "--start", start_date,
            "--end", end_date,
            "--output", str(output_file),
        ],
        check=True,
    )
    print(f"    ✓ Cycling PRs written to {output_file}")

    # Step 2: Running PRs → temp file, then append
    print()
    print(">>> Step 2: Running PRs (1, 5, 10 km)...")
    running_tmp = Path("/tmp/running_prs.org")
    subprocess.run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "running",
            "--distances", "1,5,10",
            "--title", "Running PRs",
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
    print(f"    ✓ Running PRs appended to {output_file}")

    # Step 3: Segment KOMs (if available)
    kom_json = Path("/tmp/kom_results_full.json")
    if kom_json.exists():
        print()
        print(">>> Step 3: Appending Segment KOMs...")
        subprocess.run(
            [
                sys.executable, "-m", "summit.org",
                str(kom_json),
                str(output_file),
            ],
            check=True,
        )
        print("    ✓ Segment KOMs appended")
    else:
        print()
        print(">>> Step 3: No segment KOMs found (skipping)")

    print()
    print("✓ Personal records complete!")
    print(f"  Output: {output_file}")
    line_count = len(output_file.read_text().splitlines())
    print(f"  Lines: {line_count}")


if __name__ == "__main__":
    main()
