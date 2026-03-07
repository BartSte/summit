#!/bin/bash
# PHASE 1: SETUP - Build complete historical cache
# Collects 6 years of Garmin activities and all Komoot segments
# Then computes initial personal records

set -e

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPTS_DIR"

# Activate venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "================================"
echo "PHASE 1: SETUP"
echo "================================"
echo ""
echo "This will:"
echo "1. Cache all Garmin cycling activities (past 6 years)"
echo "2. Cache all Komoot segments (SEG- prefix)"
echo "3. Compute personal records"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Step 1: Build Garmin activity cache (6 years)
echo ""
echo ">>> Step 1: Caching Garmin activities (past 6 years)..."
echo "    This will download and cache GPX for all cycling and running activities."
echo "    (Can take 10-20 minutes depending on activity count)"

START_DATE=$(date -d '6 years ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
echo "    Date range: $START_DATE to $END_DATE"

# Build cache by running cycling PRs (cache will be populated)
python3 cycling_prs.py \
    --activity all \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --output /tmp/cache_build.org

echo "    ✓ Activity cache built (cycling + running)"

# Step 2: Download Komoot segments
echo ""
echo ">>> Step 2: Caching Komoot segments (SEG- prefix)..."
python3 komoot_cli.py download-segments
echo "    ✓ Segment cache built"

# Step 3: Detect segment KOMs
echo ""
echo ">>> Step 3: Detecting segment KOMs..."
START_DATE=$(date -d '6 years ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
python3 segment_kom.py --start "$START_DATE" --end "$END_DATE" --output /tmp/kom_results_full.json
echo "    ✓ KOM detection complete"

# Step 3b: Generate personal records (cycling + running + KOMs)
echo ""
echo ">>> Step 3b: Generating personal records (cycling + running + segment KOMs)..."
./generate_personal_records.sh
echo "    ✓ Personal records generated"

echo ""
echo ">>> Step 4: Syncing to Dropbox..."
rclone sync ~/dropbox/org/ dropbox:/org/
echo "    ✓ Synced to Dropbox"

echo ""
echo "================================"
echo "SETUP COMPLETE ✓"
echo "================================"
echo ""
echo "Output files:"
echo "  ~/dropbox/org/personal_records.org (synced)"
echo ""
echo "Next: Use 'check_updates.py' to detect when new activities/segments arrive,"
echo "      then run 'update_cache.sh' to update."
