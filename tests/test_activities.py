"""Tests for summit.activities — YTD summary generation."""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summit.activities import (
    TYPE_LABELS,
    current_iso_week,
    extract_meta,
    fmt_distance,
    fmt_duration,
    generate_org,
    intensity_line,
    iso_week_date_range,
    load_cache,
    org_table,
    parse_args,
    save_cache,
    summary_table,
    type_label,
    week_month_label,
)


# ---------------------------------------------------------------------------
# fmt_duration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00:00"),
    (3600, "1:00:00"),
    (3661, "1:01:01"),
    (7322, "2:02:02"),
    (90, "0:01:30"),
    (59, "0:00:59"),
])
def test_fmt_duration(seconds, expected):
    assert fmt_duration(seconds) == expected


def test_fmt_duration_rounds():
    # 3600.6 → rounds to 3601 → 1:00:01
    assert fmt_duration(3600.6) == "1:00:01"


# ---------------------------------------------------------------------------
# fmt_distance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("km,expected", [
    (0.0, "-"),
    (0.05, "-"),     # below 0.1 threshold
    (0.1, "0.1"),
    (10.5, "10.5"),
    (100.0, "100.0"),
])
def test_fmt_distance(km, expected):
    assert fmt_distance(km) == expected


# ---------------------------------------------------------------------------
# type_label
# ---------------------------------------------------------------------------

def test_type_label_known():
    assert type_label("road_biking") == "Road Biking"
    assert type_label("running") == "Running"
    assert type_label("hiking") == "Hiking"

def test_type_label_unknown_snake_case():
    assert type_label("some_unknown_type") == "Some Unknown Type"

def test_type_label_all_known_types():
    for key, label in TYPE_LABELS.items():
        assert type_label(key) == label


# ---------------------------------------------------------------------------
# extract_meta
# ---------------------------------------------------------------------------

class TestExtractMeta:
    def test_basic_activity(self):
        act = {
            "activityId": 123,
            "activityName": "Morning Ride",
            "activityType": {"typeKey": "road_biking"},
            "startTimeLocal": "2024-06-01 09:00:00",
            "duration": 3600.0,
            "distance": 40000.0,
        }
        meta = extract_meta(act)
        assert meta["activityId"] == 123
        assert meta["activityName"] == "Morning Ride"
        assert meta["typeKey"] == "road_biking"
        assert meta["startTimeLocal"] == "2024-06-01 09:00:00"
        assert meta["duration"] == pytest.approx(3600.0)
        assert meta["distance_km"] == pytest.approx(40.0)

    def test_missing_fields_have_defaults(self):
        meta = extract_meta({})
        assert meta["activityName"] == ""
        assert meta["typeKey"] == ""
        assert meta["duration"] == pytest.approx(0.0)
        assert meta["distance_km"] == pytest.approx(0.0)

    def test_falls_back_to_gmt(self):
        act = {"activityId": 1, "startTimeGMT": "2024-06-01 09:00:00"}
        meta = extract_meta(act)
        assert meta["startTimeLocal"] == "2024-06-01 09:00:00"

    def test_distance_converted_to_km(self):
        act = {"distance": 5000.0}
        meta = extract_meta(act)
        assert meta["distance_km"] == pytest.approx(5.0)

    def test_zero_distance_gives_zero(self):
        act = {"distance": 0}
        meta = extract_meta(act)
        assert meta["distance_km"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# iso_week_date_range
# ---------------------------------------------------------------------------

class TestIsoWeekDateRange:
    def test_week_1_of_2024(self):
        monday, sunday = iso_week_date_range(2024, 1)
        assert monday.weekday() == 0  # Monday
        assert sunday.weekday() == 6  # Sunday
        assert (sunday - monday).days == 6

    def test_week_spans_one_week(self):
        monday, sunday = iso_week_date_range(2024, 20)
        assert (sunday - monday).days == 6

    def test_known_week(self):
        # 2024-W01 starts on Monday 2024-01-01
        monday, sunday = iso_week_date_range(2024, 1)
        assert str(monday) == "2024-01-01"
        assert str(sunday) == "2024-01-07"


# ---------------------------------------------------------------------------
# week_month_label
# ---------------------------------------------------------------------------

class TestWeekMonthLabel:
    def test_single_month_full(self):
        # A week entirely within January
        label = week_month_label(2024, 2, abbrev=False)
        assert "January" in label
        assert "2024" in label

    def test_cross_month_full(self):
        # Week that spans Jan/Feb boundary (week 5 of 2024: Jan 29 - Feb 4)
        label = week_month_label(2024, 5, abbrev=False)
        assert "January" in label
        assert "February" in label

    def test_single_month_abbrev(self):
        label = week_month_label(2024, 2, abbrev=True)
        assert "Jan" in label
        assert len(label) < 10  # short

    def test_cross_month_abbrev(self):
        label = week_month_label(2024, 5, abbrev=True)
        assert "/" in label

    def test_cross_year_boundary(self):
        # Week 1 of 2026 starts Dec 29 2025 (crosses year)
        monday, sunday = iso_week_date_range(2026, 1)
        if monday.year != sunday.year:
            label = week_month_label(2026, 1, abbrev=False)
            assert str(monday.year) in label
            assert str(sunday.year) in label


# ---------------------------------------------------------------------------
# current_iso_week
# ---------------------------------------------------------------------------

def test_current_iso_week_for_past_year():
    # Past year should return last ISO week (52 or 53)
    w = current_iso_week(2020)
    assert 52 <= w <= 53

def test_current_iso_week_for_current_year():
    year = datetime.now().year
    w = current_iso_week(year)
    expected = datetime.now().isocalendar()[1]
    assert w == expected


# ---------------------------------------------------------------------------
# org_table
# ---------------------------------------------------------------------------

class TestOrgTable:
    def test_empty_activities(self):
        result = org_table([])
        assert "no activities" in result

    def test_header_present(self):
        acts = [
            {"activityId": 1, "startTimeLocal": "2024-06-01 09:00:00",
             "activityName": "Ride", "typeKey": "road_biking",
             "duration": 3600.0, "distance_km": 40.0}
        ]
        result = org_table(acts)
        assert "| Date" in result
        assert "Activity" in result
        assert "Duration" in result

    def test_separator_line(self):
        acts = [
            {"activityId": 1, "startTimeLocal": "2024-06-01 09:00:00",
             "activityName": "Ride", "typeKey": "cycling",
             "duration": 3600.0, "distance_km": 40.0}
        ]
        result = org_table(acts)
        assert "-----" in result

    def test_total_row(self):
        acts = [
            {"activityId": 1, "startTimeLocal": "2024-06-01 09:00:00",
             "activityName": "Ride 1", "typeKey": "cycling",
             "duration": 3600.0, "distance_km": 40.0},
            {"activityId": 2, "startTimeLocal": "2024-06-02 09:00:00",
             "activityName": "Ride 2", "typeKey": "cycling",
             "duration": 1800.0, "distance_km": 20.0},
        ]
        result = org_table(acts)
        assert "Total" in result
        # Total duration: 5400 s = 1:30:00
        assert "1:30:00" in result

    def test_activities_sorted_by_date(self):
        acts = [
            {"activityId": 2, "startTimeLocal": "2024-06-02 09:00:00",
             "activityName": "Second Ride", "typeKey": "cycling",
             "duration": 1800.0, "distance_km": 20.0},
            {"activityId": 1, "startTimeLocal": "2024-06-01 09:00:00",
             "activityName": "First Ride", "typeKey": "cycling",
             "duration": 3600.0, "distance_km": 40.0},
        ]
        result = org_table(acts)
        pos_first = result.index("First Ride")
        pos_second = result.index("Second Ride")
        assert pos_first < pos_second

    def test_activity_name_truncated_to_37_chars(self):
        long_name = "A" * 50
        acts = [
            {"activityId": 1, "startTimeLocal": "2024-06-01 09:00:00",
             "activityName": long_name, "typeKey": "cycling",
             "duration": 3600.0, "distance_km": 40.0}
        ]
        result = org_table(acts)
        # Name truncated to 37 chars
        assert "A" * 37 in result
        assert "A" * 38 not in result


# ---------------------------------------------------------------------------
# intensity_line
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mod,vig,expected_effective", [
    (30, 0, 30),
    (0, 30, 60),
    (20, 10, 40),
    (0, 0, 0),
])
def test_intensity_line(mod, vig, expected_effective):
    data = {"moderateValue": mod, "vigorousValue": vig}
    line = intensity_line(data)
    assert str(mod) in line
    assert str(vig) in line
    assert str(expected_effective) in line


def test_intensity_line_none_values():
    data = {"moderateValue": None, "vigorousValue": None}
    line = intensity_line(data)
    assert "0" in line


# ---------------------------------------------------------------------------
# summary_table
# ---------------------------------------------------------------------------

class TestSummaryTable:
    def test_header_present(self):
        result = summary_table({}, {}, 2024)
        assert "| Week |" in result
        assert "| Month" in result

    def test_rows_generated_for_each_week(self):
        result = summary_table({}, {}, 2024)
        # 2024 has 52 weeks; check at least a few week numbers appear
        assert "| " in result
        lines = result.strip().splitlines()
        # header + separator + ≥1 data rows
        assert len(lines) >= 3

    def test_week_with_activities(self):
        by_week = {
            "2024-W10": [
                {"duration": 3600.0, "distance_km": 40.0},
            ]
        }
        result = summary_table(by_week, {}, 2024)
        assert "1:00:00" in result
        assert "40.0" in result

    def test_intensity_shown_when_present(self):
        intensity = {10: {"moderateValue": 20, "vigorousValue": 10}}
        result = summary_table({}, intensity, 2024)
        # effective = 20 + 10*2 = 40
        assert "40" in result


# ---------------------------------------------------------------------------
# generate_org
# ---------------------------------------------------------------------------

class TestGenerateOrg:
    def test_title_present(self):
        result = generate_org({}, {}, 2024)
        assert "#+TITLE: Garmin Activities 2024" in result

    def test_generated_timestamp_present(self):
        result = generate_org({}, {}, 2024)
        assert "#+GENERATED:" in result

    def test_summary_section_present(self):
        result = generate_org({}, {}, 2024)
        assert "* Summary" in result

    def test_week_sections_present(self):
        result = generate_org({}, {}, 2024)
        assert "* Week 01" in result

    def test_week_with_activities_rendered(self):
        by_week = {
            "2024-W05": [
                {"activityId": 1, "startTimeLocal": "2024-01-30 09:00:00",
                 "activityName": "Long Ride", "typeKey": "cycling",
                 "duration": 7200.0, "distance_km": 80.0}
            ]
        }
        result = generate_org(by_week, {}, 2024)
        assert "Long Ride" in result

    def test_intensity_included(self):
        intensity = {3: {"moderateValue": 15, "vigorousValue": 5}}
        result = generate_org({}, intensity, 2024)
        assert "15 mod" in result


# ---------------------------------------------------------------------------
# load_cache / save_cache
# ---------------------------------------------------------------------------

class TestCacheFunctions:
    def test_load_missing_year_returns_empty(self, tmp_path, monkeypatch):
        import summit.activities as act_module
        monkeypatch.setattr(act_module, "CACHE_DIR", tmp_path)
        result = load_cache(2099)
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        import summit.activities as act_module
        monkeypatch.setattr(act_module, "CACHE_DIR", tmp_path)

        data = {
            "111": {"activityId": 111, "startTimeLocal": "2024-06-01 09:00:00",
                    "activityName": "Test", "typeKey": "cycling",
                    "duration": 3600.0, "distance_km": 40.0}
        }
        save_cache(2024, data)
        loaded = load_cache(2024)
        assert "111" in loaded
        assert loaded["111"]["activityName"] == "Test"

    def test_corrupt_cache_returns_empty(self, tmp_path, monkeypatch):
        import summit.activities as act_module
        monkeypatch.setattr(act_module, "CACHE_DIR", tmp_path)
        cache_file = tmp_path / "2024.json"
        cache_file.write_text("not valid json {{{")
        result = load_cache(2024)
        assert result == {}


# ---------------------------------------------------------------------------
# parse_args — --format and --output flags
# ---------------------------------------------------------------------------

class TestActivitiesParseArgs:
    def _parse(self, argv, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["summit-activities"] + argv)
        return parse_args()

    def test_default_format_is_json(self, monkeypatch):
        args = self._parse([], monkeypatch)
        assert args.format == "json"

    def test_format_org(self, monkeypatch):
        args = self._parse(["--format", "org"], monkeypatch)
        assert args.format == "org"

    def test_output_default_is_none(self, monkeypatch):
        args = self._parse([], monkeypatch)
        assert args.output is None

    def test_output_flag(self, monkeypatch, tmp_path):
        out = str(tmp_path / "activities.org")
        args = self._parse(["--output", out], monkeypatch)
        assert args.output == out
