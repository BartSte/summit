"""Auto-update for systemd timer (every 15 minutes).

Non-interactive: checks for updates and, if found, runs a full cache
refresh and regenerates personal records. No LLM usage — all local
processing.
"""
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any


def main() -> None:
    """Open the auto-update log file and run the update pipeline."""
    log_file = Path.home() / ".cache" / "garmin" / "auto_update.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as log:
        _run(log)


def _run(log: IO[str]) -> None:
    """Execute the full update pipeline, logging all output.

    Args:
        log: Open file handle for log output.
    """
    def p(*args: Any) -> None:
        line = " ".join(str(a) for a in args)
        print(line, file=log, flush=True)

    def run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        return subprocess.run(cmd, stdout=log, stderr=log, **kwargs)

    p()
    p("=========================================")
    p(f"Auto-update: {datetime.now()}")
    p("=========================================")

    # Step 0: Prune deleted activities from cache
    p(">>> Step 0: Pruning deleted activities from cache...")
    try:
        from summit.updates import prune_deleted_activities
        pruned = prune_deleted_activities(window=60)
        if pruned.get("error"):
            p(f"    ⚠ Prune error: {pruned['error']}")
        else:
            total = len(pruned.get("pruned_tracks", [])) + len(pruned.get("pruned_meta", []))
            if total:
                p(f"    ✓ Removed {total} deleted activity/activities from cache")
                for aid in pruned.get("pruned_tracks", []):
                    p(f"      - track: {aid}")
                for aid in pruned.get("pruned_meta", []):
                    p(f"      - meta:  {aid}")
            else:
                p("    ✓ No deleted activities found")
    except Exception as e:
        p(f"    ⚠ Prune step failed (non-fatal): {e}")

    # Check for updates (exit 0 = no updates, exit 1 = updates available)
    p(">>> Checking for updates...")
    result = run(
        [sys.executable, "-m", "summit.updates", "--quiet"],
        check=False,
    )
    if result.returncode == 0:
        p("✓ No updates needed")
        return

    p(">>> Updates detected - processing...")

    start_date = (datetime.now() - timedelta(days=6 * 365)
                  ).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    # Step 1: Update Garmin activity cache (last 6 months)
    p()
    p(">>> Step 1: Updating Garmin activity cache...")
    run(
        [
            sys.executable, "-m", "summit.prs",
            "--activity", "all",
            "--range", "last_6_months",
            "--output", "/tmp/auto_update_cache.json",
        ],
        check=True,
    )
    p("    ✓ Activity cache updated")

    # Step 2: Update Komoot segments
    p()
    p(">>> Step 2: Updating Komoot segment cache...")
    run(
        [sys.executable, "-m", "summit.komoot", "download-segments"],
        check=True,
    )
    p("    ✓ Segment cache updated")

    # Step 3: Regenerate segment KOMs (full 6-year history)
    p()
    p(">>> Step 3: Regenerating segment KOMs...")
    run(
        [
            sys.executable, "-m", "summit.kom",
            "--start", start_date,
            "--end", end_date,
            "--output", "/tmp/kom_results_full.json",
        ],
        check=True,
    )
    p("    ✓ KOM detection complete")

    # Step 4: Generate personal records
    p()
    p(">>> Step 4: Generating personal records...")
    run(
        [sys.executable, "-m", "summit.cli.generate"],
        check=True,
    )
    p("    ✓ Personal records generated")

    # Step 5: Sync personal_records.org to Dropbox
    p()
    p(">>> Step 5: Syncing to Dropbox...")
    org_file = str(Path.home() / "dropbox" / "org" / "personal_records.org")
    run(
        ["rclone", "copy", "--ignore-times", org_file, "dropbox:/org/"],
        check=True,
    )
    p("    ✓ Synced to Dropbox")

    p()
    p(f"✓ Auto-update complete: {datetime.now()}")
    p("=========================================")
