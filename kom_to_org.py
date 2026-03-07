#!/usr/bin/env python3
"""Convert segment KOM JSON to org-mode format and append to personal_records.org"""
import json
import sys
from pathlib import Path
from datetime import datetime


def seconds_to_hms(seconds):
    """Convert seconds to HH:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes:02d}:{secs:02d}"


def kom_json_to_org(kom_json_path, output_path):
    """Convert KOM JSON to org-mode and append to personal_records.org"""
    
    if not Path(kom_json_path).exists():
        print(f"Warning: KOM JSON file not found: {kom_json_path}")
        return
    
    with open(kom_json_path) as f:
        kom_data = json.load(f)
    
    # Build org-mode content
    org_lines = []
    org_lines.append("")
    org_lines.append("* Segment KOMs")
    org_lines.append("")
    
    # Sort segments by name
    for segment_name in sorted(kom_data.keys()):
        data = kom_data[segment_name]
        org_lines.append(f"** {segment_name}")
        
        # Segment information
        distance_km = data.get('distance_m', 0) / 1000.0
        ascent_m = data.get('ascent_m', 0)
        descent_m = data.get('descent_m', 0)
        org_lines.append(f"- Distance: {distance_km:.2f} km")
        org_lines.append(f"- Ascent: {ascent_m:.0f} m")
        org_lines.append(f"- Descent: {descent_m:.0f} m")
        org_lines.append(f"- Best: {data['best']} (KOM)")
        org_lines.append(f"- Matches: {data['matches']} times")
        org_lines.append("")
        
        # Top 10 times table with new columns
        org_lines.append("| Rank | Time | Avg speed | Date |")
        org_lines.append("|------|------|-----------|------|")
        
        for idx, activity in enumerate(data.get('top', [])[:10], 1):
            time_hms = seconds_to_hms(activity['duration_s'])
            date = activity['startTimeLocal'].split()[0]  # Get date only
            avg_speed = activity.get('avg_speed_kmh', 0)
            org_lines.append(f"| {idx} | {time_hms} | {avg_speed:.1f} km/h | {date} |")
        
        org_lines.append("")
    
    # Append to output file
    org_content = "\n".join(org_lines)
    
    if Path(output_path).exists():
        with open(output_path, 'a') as f:
            f.write(org_content)
    else:
        with open(output_path, 'w') as f:
            f.write(org_content)
    
    print(f"✓ Appended segment KOMs to {output_path}")


if __name__ == "__main__":
    kom_json = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kom_results.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else Path.home() / "dropbox/org/personal_records.org"
    
    kom_json_to_org(kom_json, output_file)
