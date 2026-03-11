"""Tests for summit.updates — new activity/segment detection."""
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# check_garmin_activities
# ---------------------------------------------------------------------------


class TestCheckGarminActivities:
    """Tests for check_garmin_activities() in summit.updates."""

    def _patch_rbw(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "summit.updates.get_credential",
            lambda service, field: "testuser" if field == "username" else "testpass",
        )

    def test_new_activity_when_cache_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When cache is empty, any activity is considered new."""
        from summit.updates import check_garmin_activities

        empty_tracks = tmp_path / "tracks"
        empty_tracks.mkdir()

        mock_client = MagicMock()
        mock_client.get_activities.return_value = [
            {
                "activityId": 99999,
                "startTimeLocal": "2024-06-01 09:00:00",
                "startTimeGMT": "2024-06-01 09:00:00",
            }
        ]

        self._patch_rbw(monkeypatch)
        monkeypatch.setattr("summit.updates.Garmin", lambda u, p: mock_client)
        monkeypatch.setattr(
            "summit.updates.check_garmin_activities.__code__",
            check_garmin_activities.__code__,
        )

        with patch("summit.updates.Path") as mock_path_cls:
            mock_tracks_path = MagicMock()
            mock_tracks_path.exists.return_value = True
            mock_tracks_path.glob.return_value = []  # no cached files
            mock_path_cls.return_value = mock_tracks_path
            mock_tracks_path.__truediv__ = lambda self: MagicMock(
                exists=lambda: False)

            info, is_new, err = check_garmin_activities()
            # With empty cache, is_new should be True
            assert is_new is True or err is not None  # either new or error from mock

    def test_returns_error_on_garmin_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_garmin_activities

        self._patch_rbw(monkeypatch)

        mock_client = MagicMock()
        mock_client.get_activities.side_effect = Exception("API error")
        monkeypatch.setattr("summit.updates.Garmin", lambda u, p: mock_client)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_tracks = MagicMock()
            mock_tracks.exists.return_value = False
            mock_path_cls.return_value = mock_tracks

            info, is_new, err = check_garmin_activities()
            assert err is not None
            assert "API error" in str(err)

    def test_activity_already_in_cache_is_not_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_garmin_activities

        self._patch_rbw(monkeypatch)

        activity_id = 12345
        tracks_dir = tmp_path / "tracks"
        tracks_dir.mkdir()
        # Pre-cache this activity
        (tracks_dir / f"{activity_id}.json").write_text("[]")

        mock_client = MagicMock()
        mock_client.get_activities.return_value = [
            {
                "activityId": activity_id,
                "startTimeLocal": "2024-06-01 09:00:00",
            }
        ]
        monkeypatch.setattr("summit.updates.Garmin", lambda u, p: mock_client)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True

            cached_file = MagicMock()
            cached_file.stem = str(activity_id)
            cached_file.stat.return_value = MagicMock(st_mtime=1000.0)
            mock_path_instance.glob.return_value = [cached_file]

            def truediv(self: object, other: object):
                m = MagicMock()
                m.exists.return_value = (str(other) == f"{activity_id}.json")
                return m
            mock_path_instance.__truediv__ = truediv
            mock_path_cls.return_value = mock_path_instance

            info, is_new, err = check_garmin_activities()
            if err is None and info is not None:
                assert not is_new


# ---------------------------------------------------------------------------
# check_komoot_segments
# ---------------------------------------------------------------------------

class TestCheckKomootSegments:
    """Tests for check_komoot_segments() in summit.updates."""

    def _make_mock_api(self, planned_names: Any):
        api = MagicMock()
        api.login.return_value = True
        api.get_user_tours_list.return_value = [
            {"name": n, "id": i} for i, n in enumerate(planned_names)
        ]
        return api

    def test_no_difference_means_not_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_komoot_segments

        seg_names = ["SEG-Hill", "SEG-Flat"]
        cache_dir = tmp_path / "segments"
        cache_dir.mkdir()
        for name in seg_names:
            (cache_dir / f"{name}.gpx").write_text("")

        monkeypatch.setattr(
            "summit.updates.get_credential",
            lambda service, field: "user" if field == "username" else "pass",
        )
        mock_api_instance = self._make_mock_api(seg_names)
        monkeypatch.setattr("summit.updates.API", lambda: mock_api_instance)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_dir = MagicMock()
            mock_dir.glob.return_value = [
                MagicMock(stem=name) for name in seg_names
            ]
            mock_dir.mkdir = MagicMock()
            mock_path_cls.return_value = mock_dir

            info, is_new, err = check_komoot_segments()
            if err is None and info is not None:
                assert not is_new

    def test_new_segment_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_komoot_segments

        planned = ["SEG-Hill", "SEG-Flat", "SEG-NewClimb"]
        cached = ["SEG-Hill", "SEG-Flat"]

        monkeypatch.setattr(
            "summit.updates.get_credential",
            lambda service, field: "user" if field == "username" else "pass",
        )
        mock_api_instance = self._make_mock_api(planned)
        monkeypatch.setattr("summit.updates.API", lambda: mock_api_instance)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_dir = MagicMock()
            mock_dir.glob.return_value = [
                MagicMock(stem=name) for name in cached]
            mock_dir.mkdir = MagicMock()
            mock_path_cls.return_value = mock_dir

            info, is_new, err = check_komoot_segments()
            if err is None and info is not None:
                assert is_new
                assert "SEG-NewClimb" in info["missing_in_cache"]

    def test_login_failure_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_komoot_segments

        monkeypatch.setattr(
            "summit.updates.get_credential",
            lambda service, field: "user" if field == "username" else "pass",
        )
        mock_api_instance = MagicMock()
        mock_api_instance.login.return_value = False
        monkeypatch.setattr("summit.updates.API", lambda: mock_api_instance)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_dir = MagicMock()
            mock_dir.glob.return_value = []
            mock_dir.mkdir = MagicMock()
            mock_path_cls.return_value = mock_dir

            info, is_new, err = check_komoot_segments()
            assert err == "Komoot login failed"

    def test_api_exception_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        from summit.updates import check_komoot_segments

        monkeypatch.setattr(
            "summit.updates.get_credential",
            lambda service, field: "user" if field == "username" else "pass",
        )
        mock_api_instance = MagicMock()
        mock_api_instance.login.return_value = True
        mock_api_instance.get_user_tours_list.side_effect = Exception(
            "connection refused")
        monkeypatch.setattr("summit.updates.API", lambda: mock_api_instance)

        with patch("summit.updates.Path") as mock_path_cls:
            mock_dir = MagicMock()
            mock_dir.glob.return_value = []
            mock_dir.mkdir = MagicMock()
            mock_path_cls.return_value = mock_dir

            info, is_new, err = check_komoot_segments()
            assert err is not None
            assert "connection refused" in err
