"""Convert segment KOM JSON to org-mode format."""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Union

logger = logging.getLogger(__name__)


def seconds_to_hms(seconds: Union[int, float]) -> str:
    """Convert a duration in seconds to HH:MM:SS or MM:SS format.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like ``'01:23:45'`` or ``'23:45'``.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def kom_json_to_org(kom_json_path: Any) -> str:
    """Convert a KOM JSON file to an org-mode formatted string.

    Args:
        kom_json_path: Path to the KOM JSON results file.

    Returns:
        Org-mode formatted string, or empty string if file not found.
    """
    if not Path(kom_json_path).exists():
        logger.warning("KOM JSON file not found: %s", kom_json_path)
        return ""

    with open(kom_json_path) as f:
        kom_data = json.load(f)

    return _render_org(kom_data)


def _render_org(kom_data: dict) -> str:
    """Render a KOM data dict as an org-mode formatted string.

    Args:
        kom_data: Dict mapping segment names to result dicts.

    Returns:
        Org-mode formatted string with segment sections and tables.
    """
    org_lines = []
    org_lines.append("")
    org_lines.append("* Segment KOMs")
    org_lines.append("")

    for segment_name in sorted(kom_data.keys()):
        data = kom_data[segment_name]
        org_lines.append(f"** {segment_name}")

        distance_km = data.get('distance_m', 0) / 1000.0
        ascent_m = data.get('ascent_m', 0)
        descent_m = data.get('descent_m', 0)
        org_lines.append(f"- Distance: {distance_km:.2f} km")
        org_lines.append(f"- Ascent: {ascent_m:.0f} m")
        org_lines.append(f"- Descent: {descent_m:.0f} m")
        if data.get('best'):
            org_lines.append(f"- Best: {data['best']} (KOM)")
            org_lines.append(f"- Matches: {data['matches']} times")
        org_lines.append("")

        org_lines.append("| Rank | Time | Avg speed | Normalized power | Date |")
        org_lines.append("|------|------|-----------|-----------|------|")

        for idx, activity in enumerate(data.get('top', [])[:10], 1):
            time_hms = seconds_to_hms(activity['duration_s'])
            date = activity['startTimeLocal'].split()[0]
            avg_speed = activity.get('avg_speed_kmh', 0)
            normalized_power = activity.get('normalized_power_w')
            power_str = f"{normalized_power:.0f} W" if normalized_power is not None else ""
            org_lines.append(
                f"| {idx} | {time_hms} | {avg_speed:.1f} km/h | {power_str} | {date} |")

        org_lines.append("")

    return "\n".join(org_lines)


def main() -> None:
    """Convert a KOM JSON file to org-mode format and write to output."""
    parser = argparse.ArgumentParser(
        description="Convert KOM JSON to org-mode format")
    parser.add_argument(
        "kom_json",
        nargs="?",
        default="/tmp/kom_results.json",
        help="Path to KOM JSON file (default: /tmp/kom_results.json)",
    )
    parser.add_argument(
        "--format", choices=["json", "org"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Write output to file instead of stdout",
    )
    args = parser.parse_args()

    if args.format == "json":
        if not Path(args.kom_json).exists():
            logger.error("KOM JSON file not found: %s", args.kom_json)
            sys.exit(1)
        with open(args.kom_json) as f:
            data = json.load(f)
        content = json.dumps(data, indent=2)
    else:
        content = kom_json_to_org(args.kom_json)
        if not content:
            sys.exit(1)

    if args.output:
        Path(args.output).write_text(content)
        logger.info("Written to %s", args.output)
    else:
        print(content)


if __name__ == "__main__":
    main()
