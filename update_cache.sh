#!/bin/bash
# PHASE 2: MAINTAIN - Update caches with new activities/segments
# Refreshes Garmin activity cache and Komoot segments
# Then regenerates personal records

set -e

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPTS_DIR"

# Activate venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "================================"
echo "PHASE 2: MAINTAIN"
echo "================================"
echo ""

# Check for updates first
echo "Checking for updates..."
python3 check_updates.py

echo ""
read -p "Update caches? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Step 1: Update Garmin activity cache (last 6 months)
echo ""
echo ">>> Step 1: Updating Garmin activity cache..."
echo "    (Fetches cycling and running activities from past 6 months)"
python3 cycling_prs.py \
    --activity all \
    --range last_6_months \
    --output /tmp/update_cache.json

echo "    ✓ Activity cache updated (cycling + running)"

# Step 2: Update Komoot segments
echo ""
echo ">>> Step 2: Updating Komoot segment cache..."
python3 komoot_cli.py download-segments
echo "    ✓ Segment cache updated"

# Step 3: Regenerate segment KOMs
echo ""
echo ">>> Step 3: Regenerating segment KOMs..."
echo "    (Using full historical cache)"

START_DATE=$(date -d '6 years ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
python3 segment_kom.py --start "$START_DATE" --end "$END_DATE" --output /tmp/kom_results_full.json
echo "    ✓ KOM detection complete"

# Step 4: Generate personal records (cycling + running + KOMs)
echo ""
echo ">>> Step 4: Generating personal records (cycling + running + segment KOMs)..."
./generate_personal_records.sh
echo "    ✓ Personal records generated"

echo ""
echo ">>> Step 5: Syncing to Dropbox..."
rclone sync ~/dropbox/org/ dropbox:/org/
echo "    ✓ Synced to Dropbox"

echo ""
echo "================================"
echo "UPDATE COMPLETE ✓"
echo "================================"
echo ""
echo "Output files:"
echo "  ~/dropbox/org/personal_records.org (updated & synced)"
echo ""
