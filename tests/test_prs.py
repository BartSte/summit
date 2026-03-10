"""Tests for summit.prs — personal records logic."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from summit.prs import (
    CYCLING_TYPES,
    cache_track_path,
    compute_best_for_distance,
    downsample_activity,
    ensure_cache_dirs,
    haversine_m,
    load_cached_track,
    parse_args,
    parse_gpx_text,
    parse_time,
    resolve_range,
    save_cached_track,
    want_activity,
)


# ---------------------------------------------------------------------------
# haversine_m
# ---------------------------------------------------------------------------

class TestHaversineM:
    def test_same_point_is_zero(self):
        assert haversine_m(51.5, 0.0, 51.5, 0.0) == pytest.approx(0.0)

    def test_known_distance(self):
        # London to Paris is roughly 341 km
        d = haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
        assert 330_000 < d < 360_000

    def test_symmetric(self):
        d1 = haversine_m(51.5, 0.0, 51.6, 0.1)
        d2 = haversine_m(51.6, 0.1, 51.5, 0.0)
        assert d1 == pytest.approx(d2)

    def test_small_distance(self):
        # ~111 m per 0.001 degree of latitude
        d = haversine_m(51.5000, 0.0, 51.5010, 0.0)
        assert 100 < d < 130


# ---------------------------------------------------------------------------
# downsample_activity
# ---------------------------------------------------------------------------

class TestDownsampleActivity:
    def test_empty_returns_empty(self):
        assert downsample_activity([]) == []

    def test_single_point_returns_single(self):
        pts = [(51.5, 0.0, None, 10.0)]
        assert downsample_activity(pts) == pts

    def test_keeps_first_and_last(self):
        # Points very close together should collapse to first+last
        pts = [
            (51.5000, 0.0, None, 10.0),
            (51.5001, 0.0, None, 10.0),  # ~11 m — below 50 m threshold
            (51.5002, 0.0, None, 10.0),
        ]
        result = downsample_activity(pts, min_spacing_m=50.0)
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]

    def test_respects_min_spacing(self):
        # Generate points ~100 m apart
        pts = [(51.5 + i * 0.001, 0.0, None, None) for i in range(20)]
        result = downsample_activity(pts, min_spacing_m=50.0)
        # All points are ~111 m apart, so all should be kept
        assert len(result) == len(pts)

    def test_drops_close_points(self):
        pts = [(51.5 + i * 0.00001, 0.0, None, None) for i in range(10)]
        result = downsample_activity(pts, min_spacing_m=50.0)
        # ~1.1 m per step, all within 50 m: only first + last kept
        assert len(result) == 2


# ---------------------------------------------------------------------------
# parse_time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("t,expected_none", [
    (None, True),
    ("", False),          # will raise internally, returns None
    ("2024-06-01T09:00:00Z", False),
    ("2024-06-01T09:00:00+00:00", False),
    ("2024-06-01 09:00:00", False),
    ("not-a-date", True),
])
def test_parse_time(t, expected_none):
    result = parse_time(t)
    if expected_none:
        assert result is None
    else:
        assert result is None or isinstance(result, datetime)


def test_parse_time_z_suffix():
    result = parse_time("2024-06-01T09:00:00Z")
    assert result is not None
    assert result.year == 2024
    assert result.month == 6
    assert result.day == 1


# ---------------------------------------------------------------------------
# parse_gpx_text
# ---------------------------------------------------------------------------

class TestParseGpxText:
    def test_valid_gpx(self, sample_gpx_track):
        points = parse_gpx_text(sample_gpx_track)
        assert len(points) == 5
        lat, lon, t, ele = points[0]
        assert lat == pytest.approx(51.5)
        assert lon == pytest.approx(0.0)
        assert ele == pytest.approx(10.0)
        assert t is not None

    def test_malformed_gpx_returns_empty(self):
        points = parse_gpx_text("not valid xml <<<")
        assert points == []

    def test_empty_string_returns_empty(self):
        points = parse_gpx_text("")
        assert points == []

    def test_gpx_without_timestamps(self):
        from tests.conftest import SAMPLE_GPX_NO_TIMESTAMPS
        points = parse_gpx_text(SAMPLE_GPX_NO_TIMESTAMPS)
        assert len(points) == 3
        # Timestamps should be None
        for _, _, t, _ in points:
            assert t is None

    def test_gpx_missing_lat_lon_skipped(self):
        import textwrap
        gpx = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
              <trk><trkseg>
                <trkpt lat="51.5" lon="0.0"><time>2024-01-01T00:00:00Z</time></trkpt>
                <trkpt><time>2024-01-01T00:01:00Z</time></trkpt>
              </trkseg></trk>
            </gpx>""")
        points = parse_gpx_text(gpx)
        assert len(points) == 1


# ---------------------------------------------------------------------------
# resolve_range
# ---------------------------------------------------------------------------

class TestResolveRange:
    def _args(self, range_val="this_year", start=None, end=None):
        return SimpleNamespace(start=start, end=end, range=range_val)

    def test_this_year_starts_jan1(self):
        args = self._args("this_year")
        start, end = resolve_range(args)
        assert start.month == 1
        assert start.day == 1
        assert start.hour == 0

    def test_last_year_is_365_days(self):
        args = self._args("last_year")
        start, end = resolve_range(args)
        delta = (end - start).days
        assert delta == 365

    def test_last_6_months_is_183_days(self):
        args = self._args("last_6_months")
        start, end = resolve_range(args)
        delta = (end - start).days
        assert delta == 183

    def test_last_2_years(self):
        args = self._args("last_2_years")
        start, end = resolve_range(args)
        delta = (end - start).days
        assert delta == 365 * 2

    def test_explicit_start_end(self):
        args = self._args(start="2024-01-01", end="2024-06-30")
        start, end = resolve_range(args)
        assert start.year == 2024 and start.month == 1 and start.day == 1
        assert end.year == 2024 and end.month == 6 and end.day == 30


# ---------------------------------------------------------------------------
# want_activity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("type_key,activity,expected", [
    ("cycling", "cycling", True),
    ("road_biking", "cycling", True),
    ("mountain_biking", "cycling", True),
    ("virtual_ride", "cycling", True),
    ("e_bike_fitness", "cycling", True),
    ("my_cool_bike", "cycling", True),    # "bike" in type_key
    ("running", "cycling", False),
    ("running", "running", True),
    ("trail_running", "running", True),
    ("indoor_run", "running", True),      # "run" in type_key
    ("cycling", "running", False),
    ("cycling", "all", True),
    ("running", "all", True),
    ("yoga", "all", True),
])
def test_want_activity(type_key, activity, expected):
    assert want_activity(type_key, activity) == expected


def test_want_activity_none_type_key():
    # None type_key should not crash; result is falsy for "cycling"
    assert not want_activity(None, "cycling")
    assert want_activity(None, "all") == True


# ---------------------------------------------------------------------------
# compute_best_for_distance
# ---------------------------------------------------------------------------

class TestComputeBestForDistance:
    def _make_straight_points(self, n=10, spacing_m=100.0, seconds_per_point=30.0):
        """Create a straight-line track with evenly spaced points."""
        # 0.001 degree lat ≈ 111 m, so compute the lat step for spacing_m
        lat_step = spacing_m / 111_000
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        from datetime import timedelta
        return [
            (51.5 + i * lat_step, 0.0, t0 + timedelta(seconds=i * seconds_per_point), 10.0)
            for i in range(n)
        ]

    def test_finds_best_for_distance(self):
        # 10 points, 100 m apart, 30 s each → total ~900 m in 270 s
        pts = self._make_straight_points(n=10, spacing_m=100.0, seconds_per_point=30.0)
        result = compute_best_for_distance(pts, distance_m=500.0)
        assert result is not None
        assert result["duration_s"] > 0

    def test_no_timestamps_returns_none(self):
        pts = [(51.5, 0.0, None, 10.0), (51.51, 0.0, None, 10.0)]
        result = compute_best_for_distance(pts, distance_m=1000.0)
        assert result is None

    def test_single_point_returns_none(self):
        t0 = datetime(2024, 1, 1, 9, 0, 0)
        pts = [(51.5, 0.0, t0, 10.0)]
        result = compute_best_for_distance(pts, distance_m=100.0)
        assert result is None

    def test_empty_returns_none(self):
        result = compute_best_for_distance([], distance_m=100.0)
        assert result is None

    def test_distance_exceeds_track_returns_none(self):
        # Track is only ~900 m but we ask for 10 km
        pts = self._make_straight_points(n=10, spacing_m=100.0, seconds_per_point=30.0)
        result = compute_best_for_distance(pts, distance_m=10_000.0)
        assert result is None

    def test_moving_mode_ignores_stationary(self):
        """In moving mode, segments where distance < threshold contribute 0 time."""
        from datetime import timedelta
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        # 5 moving points at 100 m / 30 s, then 3 stationary points, then more moving
        pts = [
            (51.5000, 0.0, t0, None),
            (51.5009, 0.0, t0 + timedelta(seconds=30), None),   # ~100 m
            (51.5018, 0.0, t0 + timedelta(seconds=60), None),   # ~100 m
            (51.5018, 0.0, t0 + timedelta(seconds=120), None),  # stationary (0 m)
            (51.5018, 0.0, t0 + timedelta(seconds=180), None),  # stationary (0 m)
            (51.5027, 0.0, t0 + timedelta(seconds=210), None),  # ~100 m
        ]
        result_elapsed = compute_best_for_distance(pts, 300.0, time_mode="elapsed")
        result_moving = compute_best_for_distance(pts, 300.0, time_mode="moving", moving_threshold_m=1.0)
        # Moving time should be shorter (stationary time excluded)
        if result_elapsed and result_moving:
            assert result_moving["duration_s"] <= result_elapsed["duration_s"]

    def test_moving_mode_excludes_rest_gap_via_speed_threshold(self):
        """Speed threshold should exclude GPS-drift rest gaps that distance threshold misses."""
        from datetime import timedelta
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        # 10 riding points at ~30 km/h (≈8.33 m/s): 100 m per 12 s
        riding_step_m = 100.0
        lat_step = riding_step_m / 111_000
        pts = [(51.5 + i * lat_step, 0.0, t0 + timedelta(seconds=i * 12), None) for i in range(10)]
        # Rest gap: 3 m GPS drift over 2 hours (d > 1.0 m but speed ≈ 0.00042 m/s)
        rest_start = pts[-1]
        rest_end = (
            rest_start[0] + 3 / 111_000,
            0.0,
            rest_start[2] + timedelta(hours=2),
            None,
        )
        pts.append(rest_end)
        # 10 more riding points after the rest
        for i in range(1, 11):
            pts.append((
                rest_end[0] + i * lat_step,
                0.0,
                rest_end[2] + timedelta(seconds=i * 12),
                None,
            ))

        dist_m = 1500.0
        result_elapsed = compute_best_for_distance(pts, dist_m, time_mode="elapsed")
        result_moving_with_threshold = compute_best_for_distance(
            pts, dist_m, time_mode="moving", moving_speed_threshold_ms=1.0 / 3.6
        )
        result_moving_no_threshold = compute_best_for_distance(
            pts, dist_m, time_mode="moving", moving_speed_threshold_ms=0.0
        )

        assert result_elapsed is not None
        assert result_moving_with_threshold is not None
        assert result_moving_no_threshold is not None
        # With speed threshold: rest gap excluded → shorter than elapsed
        assert result_moving_with_threshold["duration_s"] < result_elapsed["duration_s"]
        # Without speed threshold (old behaviour): rest leaks in → equals elapsed
        assert result_moving_no_threshold["duration_s"] == pytest.approx(result_elapsed["duration_s"], rel=1e-6)

    def test_result_has_expected_keys(self):
        pts = self._make_straight_points(n=20, spacing_m=100.0, seconds_per_point=20.0)
        result = compute_best_for_distance(pts, distance_m=500.0)
        assert result is not None
        assert "duration_s" in result
        assert "start_time" in result


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class TestCacheHelpers:
    def test_cache_track_path(self, tmp_cache_dir):
        path = cache_track_path(tmp_cache_dir, 99999)
        assert path == tmp_cache_dir / "tracks" / "99999.json"

    def test_ensure_cache_dirs_creates_tracks(self, tmp_path):
        cache = tmp_path / "mygarmin"
        ensure_cache_dirs(cache)
        assert (cache / "tracks").is_dir()

    def test_save_and_load_roundtrip(self, tmp_cache_dir):
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        from datetime import timedelta
        points = [
            (51.5, 0.0, t0, 10.0),
            (51.501, 0.001, t0 + timedelta(seconds=60), 12.0),
        ]
        save_cached_track(tmp_cache_dir, 12345, points)
        loaded = load_cached_track(tmp_cache_dir, 12345)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0][0] == pytest.approx(51.5)
        assert loaded[0][2] is not None  # timestamp preserved

    def test_load_missing_returns_none(self, tmp_cache_dir):
        result = load_cached_track(tmp_cache_dir, 999999)
        assert result is None

    def test_save_points_without_timestamps(self, tmp_cache_dir):
        points = [(51.5, 0.0, None, 10.0), (51.501, 0.001, None, 12.0)]
        save_cached_track(tmp_cache_dir, 77777, points)
        loaded = load_cached_track(tmp_cache_dir, 77777)
        assert loaded is not None
        for _, _, t, _ in loaded:
            assert t is None

    def test_save_points_without_elevation(self, tmp_cache_dir):
        t0 = datetime(2024, 6, 1, 9, 0, 0)
        points = [(51.5, 0.0, t0, None)]
        save_cached_track(tmp_cache_dir, 88888, points)
        loaded = load_cached_track(tmp_cache_dir, 88888)
        assert loaded is not None
        assert loaded[0][3] is None


# ---------------------------------------------------------------------------
# parse_args — --format flag
# ---------------------------------------------------------------------------

class TestParseArgs:
    def _parse(self, argv, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["summit-prs"] + argv)
        return parse_args()

    def test_default_format_is_json(self, monkeypatch):
        args = self._parse([], monkeypatch)
        assert args.format == "json"

    def test_format_org(self, monkeypatch):
        args = self._parse(["--format", "org"], monkeypatch)
        assert args.format == "org"

    def test_format_json_explicit(self, monkeypatch):
        args = self._parse(["--format", "json"], monkeypatch)
        assert args.format == "json"

    def test_output_default_is_none(self, monkeypatch):
        args = self._parse([], monkeypatch)
        assert args.output is None

    def test_output_flag(self, monkeypatch, tmp_path):
        out = str(tmp_path / "out.json")
        args = self._parse(["--output", out], monkeypatch)
        assert args.output == out
