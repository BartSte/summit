"""Tests for summit.org — org-mode formatting of KOM JSON."""
import json
from pathlib import Path

import pytest

from summit.org import kom_json_to_org, seconds_to_hms


# ---------------------------------------------------------------------------
# seconds_to_hms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "00:00"),
    (59, "00:59"),
    (60, "01:00"),
    (90, "01:30"),
    (3600, "01:00:00"),
    (3661, "01:01:01"),
    (7322, "02:02:02"),
    (86399, "23:59:59"),
    (330, "05:30"),
])
def test_seconds_to_hms(seconds, expected):
    assert seconds_to_hms(seconds) == expected


# ---------------------------------------------------------------------------
# kom_json_to_org
# ---------------------------------------------------------------------------

class TestKomJsonToOrg:
    def test_creates_output_file_when_missing(self, tmp_path, sample_kom_data):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(sample_kom_data))

        kom_json_to_org(str(kom_file), str(out_file))

        assert out_file.exists()
        content = out_file.read_text()
        assert "* Segment KOMs" in content

    def test_appends_to_existing_file(self, tmp_path, sample_kom_data):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(sample_kom_data))
        out_file.write_text("* Existing Content\n")

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        assert "* Existing Content" in content
        assert "* Segment KOMs" in content

    def test_missing_input_file_is_skipped(self, tmp_path, capsys):
        out_file = tmp_path / "records.org"
        kom_json_to_org(str(tmp_path / "nonexistent.json"), str(out_file))
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert not out_file.exists()

    def test_segment_names_as_headings(self, tmp_path, sample_kom_data):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(sample_kom_data))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        assert "** SEG-Test Hill" in content
        assert "** SEG-Flat Sprint" in content

    def test_segments_sorted_alphabetically(self, tmp_path):
        data = {
            "SEG-Z Segment": {
                "best": "5:00", "best_seconds": 300.0,
                "activity": {"id": 1, "name": "Ride", "startTimeLocal": "2024-01-01 09:00:00", "duration_s": 300.0, "avg_speed_kmh": 10.0},
                "matches": 1,
                "top": [{"id": 1, "name": "Ride", "startTimeLocal": "2024-01-01 09:00:00", "duration_s": 300.0, "avg_speed_kmh": 10.0}],
                "distance_m": 1000.0, "ascent_m": 0.0, "descent_m": 0.0,
            },
            "SEG-A Segment": {
                "best": "4:00", "best_seconds": 240.0,
                "activity": {"id": 2, "name": "Ride2", "startTimeLocal": "2024-01-02 09:00:00", "duration_s": 240.0, "avg_speed_kmh": 12.0},
                "matches": 1,
                "top": [{"id": 2, "name": "Ride2", "startTimeLocal": "2024-01-02 09:00:00", "duration_s": 240.0, "avg_speed_kmh": 12.0}],
                "distance_m": 800.0, "ascent_m": 0.0, "descent_m": 0.0,
            },
        }
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(data))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        pos_a = content.index("SEG-A Segment")
        pos_z = content.index("SEG-Z Segment")
        assert pos_a < pos_z  # A comes before Z

    def test_org_table_structure(self, tmp_path, sample_kom_data):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(sample_kom_data))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        assert "| Rank | Time | Avg speed | Date |" in content
        assert "|------|------|-----------|------|" in content

    def test_distance_and_ascent_in_output(self, tmp_path, sample_kom_data):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(sample_kom_data))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        # SEG-Test Hill has distance_m=2350, ascent_m=50
        assert "2.35 km" in content
        assert "50 m" in content

    def test_top_times_limited_to_10(self, tmp_path):
        top = [
            {"id": i, "name": f"Ride{i}", "startTimeLocal": f"2024-01-{i:02d} 09:00:00",
             "duration_s": 300.0 + i, "avg_speed_kmh": 20.0}
            for i in range(1, 16)  # 15 entries
        ]
        data = {
            "SEG-Many": {
                "best": "5:00", "best_seconds": 300.0,
                "activity": top[0],
                "matches": 15,
                "top": top,
                "distance_m": 1000.0, "ascent_m": 0.0, "descent_m": 0.0,
            }
        }
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps(data))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        # Only first 10 should appear: row 10 "| 10 |" should be present, 11 should not
        assert "| 10 |" in content
        assert "| 11 |" not in content

    def test_empty_kom_data(self, tmp_path):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "records.org"
        kom_file.write_text(json.dumps({}))

        kom_json_to_org(str(kom_file), str(out_file))

        content = out_file.read_text()
        assert "* Segment KOMs" in content
