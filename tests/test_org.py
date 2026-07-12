"""Tests for summit.org — org-mode formatting of KOM JSON."""
import json
from pathlib import Path
from typing import Any

import pytest

from summit.org import _render_org, kom_json_to_org, seconds_to_hms

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
def test_seconds_to_hms(seconds: int, expected: str):
    assert seconds_to_hms(seconds) == expected


# ---------------------------------------------------------------------------
# kom_json_to_org (returns a string now)
# ---------------------------------------------------------------------------

class TestKomJsonToOrg:
    def test_returns_org_string(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        assert isinstance(result, str)
        assert "* Segment KOMs" in result

    def test_missing_input_file_returns_empty(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        import logging
        with caplog.at_level(logging.WARNING, logger="summit.org"):
            result = kom_json_to_org(str(tmp_path / "nonexistent.json"))
        assert result == ""
        assert any("not found" in r.message for r in caplog.records)

    def test_segment_names_as_headings(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        assert "** SEG-Test Hill" in result
        assert "** SEG-Flat Sprint" in result

    def test_segments_sorted_alphabetically(self, tmp_path: Path):
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
        kom_file.write_text(json.dumps(data))

        result = kom_json_to_org(str(kom_file))

        pos_a = result.index("SEG-A Segment")
        pos_z = result.index("SEG-Z Segment")
        assert pos_a < pos_z

    def test_org_table_structure(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        assert "| Rank | Time | Avg speed | Avg power | Normalized power | Date |" in result
        assert "|------|------|-----------|-----------|------|" in result

    def test_distance_and_ascent_in_output(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        assert "2.35 km" in result
        assert "50 m" in result

    def test_power_column_shown_when_present(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        assert "215 W" in result

    def test_power_column_empty_when_none(self, tmp_path: Path, sample_kom_data: Any):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        result = kom_json_to_org(str(kom_file))

        # The second entry has normalized_power_w=None → empty power cell
        # The row should contain an empty cell between speed and date: "| ... |  | ..."
        assert "|  |" in result

    def test_top_times_limited_to_10(self, tmp_path: Path):
        top = [
            {"id": i, "name": f"Ride{i}", "startTimeLocal": f"2024-01-{i:02d} 09:00:00",
             "duration_s": 300.0 + i, "avg_speed_kmh": 20.0}
            for i in range(1, 16)
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
        kom_file.write_text(json.dumps(data))

        result = kom_json_to_org(str(kom_file))

        assert "| 10 |" in result
        assert "| 11 |" not in result

    def test_empty_kom_data(self, tmp_path: Path):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps({}))

        result = kom_json_to_org(str(kom_file))

        assert "* Segment KOMs" in result


# ---------------------------------------------------------------------------
# --format flag via main()
# ---------------------------------------------------------------------------

class TestOrgMain:
    def _run(self, argv: list[str], monkeypatch: pytest.MonkeyPatch):
        import sys

        from summit.org import main
        monkeypatch.setattr(sys, "argv", ["summit-org"] + argv)
        main()

    def test_format_json_prints_json(self, tmp_path: Path, sample_kom_data: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        self._run(["--format", "json", str(kom_file)], monkeypatch)

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "SEG-Test Hill" in parsed

    def test_format_org_prints_org(self, tmp_path: Path, sample_kom_data: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        kom_file = tmp_path / "kom.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        self._run(["--format", "org", str(kom_file)], monkeypatch)

        out = capsys.readouterr().out
        assert "* Segment KOMs" in out
        assert "** SEG-Test Hill" in out

    def test_output_file_written(self, tmp_path: Path, sample_kom_data: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "out.org"
        kom_file.write_text(json.dumps(sample_kom_data))

        self._run(["--format", "org", "--output",
                  str(out_file), str(kom_file)], monkeypatch)

        assert out_file.exists()
        assert "* Segment KOMs" in out_file.read_text()

    def test_output_file_json(self, tmp_path: Path, sample_kom_data: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        kom_file = tmp_path / "kom.json"
        out_file = tmp_path / "out.json"
        kom_file.write_text(json.dumps(sample_kom_data))

        self._run(["--format", "json", "--output",
                  str(out_file), str(kom_file)], monkeypatch)

        assert out_file.exists()
        parsed = json.loads(out_file.read_text())
        assert "SEG-Test Hill" in parsed
