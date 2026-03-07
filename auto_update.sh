#!/usr/bin/env bash
# Auto-update script for systemd timer (every 15 minutes)
# Non-interactive: updates caches and regenerates personal records if new data available
# NO LLM usage - all local processing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$HOME/.cache/garmin/auto_update.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Redirect all output to log
exec >> "$LOG_FILE" 2>&1

echo ""
echo "========================================="
echo "Auto-update: $(date)"
echo "========================================="

# Activate venv (create and install deps if missing)
if [ ! -d ".venv" ]; then
    echo ">>> Creating venv and installing dependencies..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    source .venv/bin/activate
fi

# Check for updates (exit code 1 = updates available, 0 = no updates)
echo ">>> Checking for updates..."
if python3 check_updates.py --quiet; then
    echo "✓ No updates needed"
    exit 0
fi

echo ">>> Updates detected - processing..."

# Step 1: Update Garmin cache (last 6 months, catches all recent activities)
echo ""
echo ">>> Step 1: Updating Garmin activity cache..."
python3 cycling_prs.py \
    --activity all \
    --range last_6_months \
    --output /tmp/auto_update_cache.json \
    >> "$LOG_FILE" 2>&1

echo "    ✓ Activity cache updated"

# Step 2: Update Komoot segments
echo ""
echo ">>> Step 2: Updating Komoot segment cache..."
python3 komoot_cli.py download-segments >> "$LOG_FILE" 2>&1
echo "    ✓ Segment cache updated"

# Step 3: Regenerate segment KOMs (full 6-year history)
echo ""
echo ">>> Step 3: Regenerating segment KOMs..."
START_DATE=$(date -d '6 years ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
python3 segment_kom.py \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --output /tmp/kom_results_full.json \
    >> "$LOG_FILE" 2>&1
echo "    ✓ KOM detection complete"

# Step 4: Generate personal records (cycling + running + KOMs)
echo ""
echo ">>> Step 4: Generating personal records..."
./generate_personal_records.sh >> "$LOG_FILE" 2>&1
echo "    ✓ Personal records generated"

# Step 5: Sync to Dropbox
echo ""
echo ">>> Step 5: Syncing to Dropbox..."
rclone sync ~/dropbox/org/personal_records.org dropbox:/org/ >> "$LOG_FILE" 2>&1
echo "    ✓ Synced to Dropbox"

echo ""
echo "✓ Auto-update complete: $(date)"
echo "========================================="
