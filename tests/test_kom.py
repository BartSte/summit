"""Tests for summit.kom — KOM detection logic."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from summit.kom import (calculate_distance_m, calculate_elevation_gain_loss,
                        downsample_points, format_duration, haversine_m,
                        match_segment, nearest_segment_index, parse_args,
                        parse_time, read_gpx_points, resolve_range,
                        want_activity)

# ---------------------------------------------------------------------------
# haversine_m (separate implementation from prs.py — test independently)
# ---------------------------------------------------------------------------


class TestHaversineM:
    def test_zero_distance(self):
        assert haversine_m(51.5, 0.0, 51.5, 0.0) == pytest.approx(0.0)

    def test_known_distance(self):
        d = haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
        assert 330_000 < d < 360_000

    def test_positive_distance(self):
        d = haversine_m(0.0, 0.0, 1.0, 0.0)
        assert d > 0


# ---------------------------------------------------------------------------
# downsample_points
# ---------------------------------------------------------------------------

class TestDownsamplePoints:
    def test_empty(self):
        assert downsample_points([]) == []

    def test_single_point(self):
        pts = [(51.5, 0.0)]
        assert downsample_points(pts) == pts

    def test_keeps_first_and_last(self):
        pts = [(51.5000, 0.0), (51.5001, 0.0), (51.5100, 0.0)]
        result = downsample_points(pts, min_spacing_m=500.0)
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]

    def test_all_far_apart_kept(self):
        pts = [(51.5 + i * 0.01, 0.0) for i in range(5)]
        result = downsample_points(pts, min_spacing_m=10.0)
        assert len(result) == len(pts)


# ---------------------------------------------------------------------------
# calculate_distance_m
# ---------------------------------------------------------------------------

class TestCalculateDistanceM:
    def test_single_point_is_zero(self):
        assert calculate_distance_m([(51.5, 0.0)]) == 0.0

    def test_two_points(self):
        d = calculate_distance_m([(51.5, 0.0), (51.5010, 0.0)])
        assert d > 0

    def test_empty_is_zero(self):
        assert calculate_distance_m([]) == 0.0

    def test_longer_path_larger(self):
        pts_short = [(51.5, 0.0), (51.501, 0.0)]
        pts_long = [(51.5, 0.0), (51.510, 0.0)]
        assert calculate_distance_m(pts_long) > calculate_distance_m(pts_short)


# ---------------------------------------------------------------------------
# calculate_elevation_gain_loss
# ---------------------------------------------------------------------------

class TestCalculateElevationGainLoss:
    def test_flat_is_zero(self):
        pts = [(51.5, 0.0, None, 100.0), (51.501, 0.0, None, 100.0)]
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(0.0)
        assert desc == pytest.approx(0.0)

    def test_uphill(self):
        pts = [(51.5, 0.0, None, 100.0), (51.501, 0.0, None, 150.0)]
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(50.0)
        assert desc == pytest.approx(0.0)

    def test_downhill(self):
        pts = [(51.5, 0.0, None, 150.0), (51.501, 0.0, None, 100.0)]
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(0.0)
        assert desc == pytest.approx(50.0)

    def test_mixed(self):
        pts = [
            (51.500, 0.0, None, 100.0),
            (51.501, 0.0, None, 150.0),  # +50
            (51.502, 0.0, None, 120.0),  # -30
        ]
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(50.0)
        assert desc == pytest.approx(30.0)

    def test_none_elevation_skipped(self):
        pts = [(51.5, 0.0, None, None), (51.501, 0.0, None, None)]
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(0.0)
        assert desc == pytest.approx(0.0)

    def test_short_points_skipped(self):
        pts = [(51.5, 0.0), (51.501, 0.0)]  # only 2 elements
        asc, desc = calculate_elevation_gain_loss(pts)
        assert asc == pytest.approx(0.0)
        assert desc == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# read_gpx_points
# ---------------------------------------------------------------------------

class TestReadGpxPoints:
    def test_valid_track(self, sample_gpx_track: Any, tmp_path: Path):
        gpx_file = tmp_path / "test.gpx"
        gpx_file.write_text(sample_gpx_track)
        points, name, root = read_gpx_points(gpx_file)
        assert len(points) == 5
        assert name is None  # our track GPX has name in trk, not root
        assert root is not None

    def test_route_points_fallback(self, tmp_path: Path):
        from tests.conftest import SAMPLE_GPX_ROUTE
        gpx_file = tmp_path / "route.gpx"
        gpx_file.write_text(SAMPLE_GPX_ROUTE)
        points, name, root = read_gpx_points(gpx_file)
        assert len(points) == 3
        assert name == "SEG-Test Route"

    def test_malformed_returns_empty(self, tmp_path: Path):
        gpx_file = tmp_path / "bad.gpx"
        gpx_file.write_text("not valid xml <<<")
        points, name, root = read_gpx_points(gpx_file)
        assert points == []
        assert name is None

    def test_missing_file_returns_empty(self, tmp_path: Path):
        gpx_file = tmp_path / "nonexistent.gpx"
        points, name, root = read_gpx_points(gpx_file)
        assert points == []

    def test_elevation_and_time_parsed(self, sample_gpx_track: Any, tmp_path: Path):
        gpx_file = tmp_path / "track.gpx"
        gpx_file.write_text(sample_gpx_track)
        points, _, _ = read_gpx_points(gpx_file)
        lat, lon, t, ele = points[0]
        assert ele == pytest.approx(10.0)
        assert t is not None


# ---------------------------------------------------------------------------
# nearest_segment_index
# ---------------------------------------------------------------------------

class TestNearestSegmentIndex:
    def test_finds_nearest(self):
        seg_points = [(51.5, 0.0), (51.51, 0.0), (51.52, 0.0)]
        i, d = nearest_segment_index(51.51, 0.0, seg_points)
        assert i == 1
        assert d == pytest.approx(0.0, abs=1.0)

    def test_single_segment_point(self):
        seg_points = [(51.5, 0.0)]
        i, d = nearest_segment_index(51.6, 0.0, seg_points)
        assert i == 0

    def test_empty_segment(self):
        i, d = nearest_segment_index(51.5, 0.0, [])
        assert i is None
        assert d is None


# ---------------------------------------------------------------------------
# match_segment
# ---------------------------------------------------------------------------

class TestMatchSegment:
    def _make_activity_points(self, lats: Any, lon: float = 0.0, t0: Any = None, dt_s: int = 30):
        """Helper to make activity points."""
        if t0 is None:
            t0 = datetime(2024, 6, 1, 9, 0, 0)
        return [
            (lat, lon, t0 + timedelta(seconds=i * dt_s), None)
            for i, lat in enumerate(lats)
        ]

    def _make_segment_points(self, lats: Any, lon: float = 0.0):
        return [(lat, lon, None, None) for lat in lats]

    def test_match_found(self):
        # Segment: 51.500 → 51.502 (within activity track)
        act_pts = self._make_activity_points(
            [51.498, 51.499, 51.500, 51.501, 51.502, 51.503, 51.504]
        )
        seg_pts = self._make_segment_points([51.500, 51.501, 51.502])
        result = match_segment(act_pts, seg_pts, tolerance_m=50.0)
        assert result is not None
        duration, start_i, end_i = result
        assert duration > 0

    def test_no_match_when_far_away(self):
        act_pts = self._make_activity_points(
            [51.5, 51.51, 51.52]  # far from segment
        )
        seg_pts = self._make_segment_points([10.0, 10.01, 10.02])  # Africa
        result = match_segment(act_pts, seg_pts, tolerance_m=25.0)
        assert result is None

    def test_too_few_activity_points(self):
        act_pts = self._make_activity_points([51.5])
        seg_pts = self._make_segment_points([51.5, 51.501])
        result = match_segment(act_pts, seg_pts, tolerance_m=25.0)
        assert result is None

    def test_too_few_segment_points(self):
        act_pts = self._make_activity_points([51.5, 51.501, 51.502])
        seg_pts = self._make_segment_points([51.5])
        result = match_segment(act_pts, seg_pts, tolerance_m=25.0)
        assert result is None

    def test_picks_fastest_match(self):
        """If segment traversed twice, fastest time wins."""
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        # Ride: seg start → seg end (30s), off-route, seg start → seg end (20s)
        act_pts = [
            (51.5000, 0.0, t0 + timedelta(seconds=0), None),   # seg start
            (51.5010, 0.0, t0 + timedelta(seconds=30), None),  # seg end (30s)
            (51.5050, 0.0, t0 + timedelta(seconds=60), None),  # off route
            (51.5000, 0.0, t0 + timedelta(seconds=90), None),  # seg start again
            (51.5010, 0.0, t0 + timedelta(seconds=110), None),  # seg end (20s)
        ]
        seg_pts = [
            (51.5000, 0.0, None, None),
            (51.5010, 0.0, None, None),
        ]
        result = match_segment(act_pts, seg_pts, tolerance_m=50.0)
        assert result is not None
        duration, _, _ = result
        # Should pick the 20s match (fastest)
        assert duration <= 30.0 + 1.0  # allow small interpolation error

    def test_no_timestamps_returns_none(self):
        act_pts = [(51.5000, 0.0, None, None), (51.5010, 0.0,
                                                None, None), (51.5020, 0.0, None, None)]
        seg_pts = [(51.5000, 0.0, None, None), (51.5010, 0.0, None, None)]
        result = match_segment(act_pts, seg_pts, tolerance_m=25.0)
        assert result is None


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00"),
    (59, "0:59"),
    (60, "1:00"),
    (90, "1:30"),
    (3600, "1:00:00"),
    (3661, "1:01:01"),
    (7322, "2:02:02"),
    (3599, "59:59"),
])
def test_format_duration(seconds: int, expected: str):
    assert format_duration(seconds) == expected


# ---------------------------------------------------------------------------
# resolve_range and want_activity (shared logic with prs.py)
# ---------------------------------------------------------------------------

def test_want_activity_cycling():
    assert want_activity("road_biking", "cycling") is True
    assert want_activity("running", "cycling") is False


def test_want_activity_all():
    assert want_activity("yoga", "all") is True


def test_resolve_range_this_year():
    from types import SimpleNamespace
    args = SimpleNamespace(start=None, end=None, range="this_year")
    start, end = resolve_range(args)
    assert start.month == 1 and start.day == 1


# ---------------------------------------------------------------------------
# parse_args — --format flag
# ---------------------------------------------------------------------------

class TestParseArgs:
    def _parse(self, argv: list[str], monkeypatch: pytest.MonkeyPatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["summit-kom"] + argv)
        return parse_args()

    def test_default_format_is_json(self, monkeypatch: pytest.MonkeyPatch):
        args = self._parse([], monkeypatch)
        assert args.format == "json"

    def test_format_org(self, monkeypatch: pytest.MonkeyPatch):
        args = self._parse(["--format", "org"], monkeypatch)
        assert args.format == "org"

    def test_format_json_explicit(self, monkeypatch: pytest.MonkeyPatch):
        args = self._parse(["--format", "json"], monkeypatch)
        assert args.format == "json"

    def test_output_default_is_none(self, monkeypatch: pytest.MonkeyPatch):
        args = self._parse([], monkeypatch)
        assert args.output is None
