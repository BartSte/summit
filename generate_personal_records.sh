#!/usr/bin/env bash
set -e

# Generate Personal Records (Cycling + Running)
# Output: ~/dropbox/org/personal_records.org

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
source .venv/bin/activate

# Date range: last 6 years
START_DATE=$(date -d '6 years ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)

OUTPUT_FILE="$HOME/dropbox/org/personal_records.org"

echo ">>> Generating personal records..."
echo "    Date range: $START_DATE to $END_DATE"
echo ""

# Step 1: Generate Cycling PRs (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 km)
echo ">>> Step 1: Cycling PRs (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 km)..."
python3 cycling_prs.py \
  --activity cycling \
  --distances 1,5,10,20,30,40,50,60,70,80,90,100 \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --output "$OUTPUT_FILE"
echo "    ✓ Cycling PRs written to $OUTPUT_FILE"

# Step 2: Generate Running PRs (1, 5, 10 km) and append
echo ""
echo ">>> Step 2: Running PRs (1, 5, 10 km)..."
python3 cycling_prs.py \
  --activity running \
  --distances 1,5,10 \
  --title "Running PRs" \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --output /tmp/running_prs.org

# Append running PRs to the output file
echo "" >> "$OUTPUT_FILE"
cat /tmp/running_prs.org >> "$OUTPUT_FILE"
rm /tmp/running_prs.org
echo "    ✓ Running PRs appended to $OUTPUT_FILE"

# Step 3: Append Segment KOMs (if they exist)
if [ -f /tmp/kom_results_full.json ]; then
  echo ""
  echo ">>> Step 3: Appending Segment KOMs..."
  python3 kom_to_org.py /tmp/kom_results_full.json "$OUTPUT_FILE"
  echo "    ✓ Segment KOMs appended"
else
  echo ""
  echo ">>> Step 3: No segment KOMs found (skipping)"
fi

echo ""
echo "✓ Personal records complete!"
echo "  Output: $OUTPUT_FILE"
echo "  Lines: $(wc -l < "$OUTPUT_FILE")"
