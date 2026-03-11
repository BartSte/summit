"""Tests for summit.komoot — Komoot API helpers."""
import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from summit.komoot import (bulk_prefix, download_segments, list_planned,
                           parse_date, rename_tour)

# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("s,expected_none", [
    (None, True),
    ("", True),
    ("2024-06-01T09:00:00Z", False),
    ("2024-06-01T09:00:00+00:00", False),
    ("2024-06-01", False),
    ("not-a-date", True),
])
def test_parse_date(s: Any, expected_none: bool):
    result = parse_date(s)
    if expected_none:
        assert result is None
    else:
        assert isinstance(result, datetime.datetime)


def test_parse_date_z_suffix():
    result = parse_date("2024-06-01T09:00:00Z")
    assert result is not None
    assert result.year == 2024


# ---------------------------------------------------------------------------
# list_planned
# ---------------------------------------------------------------------------

class TestListPlanned:
    def _make_api(self, tours: Any):
        api = MagicMock()
        api.get_user_tours_list.return_value = tours
        return api

    def test_empty_list(self, capsys: pytest.CaptureFixture[str]):
        api = self._make_api([])
        result = list_planned(api)
        assert result == []

    def test_returns_sorted_by_date_descending(self, capsys: pytest.CaptureFixture[str]):
        tours = [
            {"id": 1, "name": "Old Ride", "date": "2024-01-01T00:00:00Z",
                "distance": 10000, "sport": "road"},
            {"id": 2, "name": "New Ride", "date": "2024-06-01T00:00:00Z",
                "distance": 20000, "sport": "road"},
        ]
        api = self._make_api(tours)
        result = list_planned(api)
        # Sorted newest first
        assert result[0]["id"] == 2
        assert result[1]["id"] == 1

    def test_prints_tour_info(self, capsys: pytest.CaptureFixture[str]):
        tours = [
            {"id": 42, "name": "SEG-Test", "date": "2024-06-01T00:00:00Z",
                "distance": 5000, "sport": "road"},
        ]
        api = self._make_api(tours)
        list_planned(api)
        captured = capsys.readouterr()
        assert "SEG-Test" in captured.out
        assert "5.0 km" in captured.out
        assert "42" in captured.out

    def test_handles_missing_date(self, capsys: pytest.CaptureFixture[str]):
        tours = [
            {"id": 1, "name": "No Date Tour", "date": None,
                "distance": 1000, "sport": "mtb"},
        ]
        api = self._make_api(tours)
        result = list_planned(api)
        assert len(result) == 1

    def test_returns_list_of_dicts(self, capsys: pytest.CaptureFixture[str]):
        tours = [
            {"id": 1, "name": "Ride", "date": "2024-06-01T00:00:00Z",
                "distance": 10000, "sport": "road"},
        ]
        api = self._make_api(tours)
        result = list_planned(api)
        assert isinstance(result, list)
        assert isinstance(result[0], dict)


# ---------------------------------------------------------------------------
# rename_tour
# ---------------------------------------------------------------------------

class TestRenameTour:
    def _make_api(self):
        api = MagicMock()
        api.user_details = {"user_id": "user123", "token": "tok456"}
        return api

    def test_calls_patch_with_correct_url(self):
        api = self._make_api()
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            rename_tour(api, 99, "New Name")
            mock_patch.assert_called_once()
            url = mock_patch.call_args[0][0]
            assert "99" in url

    def test_sends_new_name_in_json(self):
        api = self._make_api()
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            rename_tour(api, 99, "New Name")
            _, kwargs = mock_patch.call_args
            assert kwargs.get("json") == {"name": "New Name"}

    def test_uses_auth_credentials(self):
        api = self._make_api()
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            rename_tour(api, 99, "Name")
            _, kwargs = mock_patch.call_args
            assert kwargs.get("auth") == ("user123", "tok456")

    def test_raises_on_non_200(self):
        api = self._make_api()
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(
                status_code=403, text="Forbidden")
            with pytest.raises(RuntimeError, match="Rename failed"):
                rename_tour(api, 99, "Name")


# ---------------------------------------------------------------------------
# bulk_prefix
# ---------------------------------------------------------------------------

class TestBulkPrefix:
    def _make_api(self, tours: Any):
        api = MagicMock()
        api.user_details = {"user_id": "user123", "token": "tok456"}
        api.get_user_tours_list.return_value = tours
        return api

    def test_renames_matching_tours(self):
        tours = [
            {"id": 1, "name": "OLD-Alpha"},
            {"id": 2, "name": "OLD-Beta"},
            {"id": 3, "name": "OTHER-Gamma"},
        ]
        api = self._make_api(tours)
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            renamed = bulk_prefix(api, "OLD-", "NEW-")
        assert len(renamed) == 2
        assert ("1" not in [str(r[0]) for r in renamed]
                or any(r[2] == "NEW-Alpha" for r in renamed))

    def test_skips_non_matching_tours(self):
        tours = [{"id": 1, "name": "OTHER-Tour"}]
        api = self._make_api(tours)
        with patch("summit.komoot.requests.patch") as mock_patch:
            renamed = bulk_prefix(api, "SEG-", "NEWSEG-")
        assert renamed == []
        mock_patch.assert_not_called()

    def test_raises_on_patch_failure(self):
        tours = [{"id": 1, "name": "SEG-Hill"}]
        api = self._make_api(tours)
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(
                status_code=500, text="Server Error")
            with pytest.raises(RuntimeError, match="Rename failed"):
                bulk_prefix(api, "SEG-", "NEW-")

    def test_new_name_constructed_correctly(self):
        tours = [{"id": 1, "name": "SEG-Alpe d'Huez"}]
        api = self._make_api(tours)
        with patch("summit.komoot.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            renamed = bulk_prefix(api, "SEG-", "SEGMENT-")
        assert renamed[0][2] == "SEGMENT-Alpe d'Huez"

    def test_empty_tours_list(self):
        api = self._make_api([])
        with patch("summit.komoot.requests.patch") as mock_patch:
            renamed = bulk_prefix(api, "SEG-", "NEW-")
        assert renamed == []


# ---------------------------------------------------------------------------
# download_segments
# ---------------------------------------------------------------------------

class TestDownloadSegments:
    def _make_api(self, tours: Any):
        api = MagicMock()
        api.get_user_tours_list.return_value = tours
        api.download_tour_gpx.return_value = None
        return api

    def test_downloads_matching_tours(self, tmp_path: Path):
        tours = [
            {"id": 10, "name": "SEG-Climb"},
            {"id": 11, "name": "SEG-Sprint"},
            {"id": 12, "name": "Other-Tour"},
        ]
        api = self._make_api(tours)
        downloaded = download_segments(
            api, prefix="SEG-", cache_dir=str(tmp_path))
        assert len(downloaded) == 2
        # Should have downloaded ids 10 and 11
        downloaded_ids = [d[0] for d in downloaded]
        assert 10 in downloaded_ids
        assert 11 in downloaded_ids

    def test_skips_non_matching_tours(self, tmp_path: Path):
        tours = [{"id": 1, "name": "NoPrefix-Tour"}]
        api = self._make_api(tours)
        downloaded = download_segments(
            api, prefix="SEG-", cache_dir=str(tmp_path))
        assert downloaded == []

    def test_handles_download_exception(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        import logging
        tours = [{"id": 10, "name": "SEG-Fail"}]
        api = self._make_api(tours)
        api.download_tour_gpx.side_effect = Exception("download failed")
        with caplog.at_level(logging.ERROR, logger="summit.komoot"):
            downloaded = download_segments(
                api, prefix="SEG-", cache_dir=str(tmp_path))
        assert downloaded == []
        assert any(
            "SEG-Fail" in r.message and "download failed" in r.message for r in caplog.records)

    def test_creates_cache_dir(self, tmp_path: Path):
        new_dir = tmp_path / "newsegments"
        api = self._make_api([])
        download_segments(api, prefix="SEG-", cache_dir=str(new_dir))
        assert new_dir.exists()

    def test_mixed_success_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        tours = [
            {"id": 1, "name": "SEG-Good"},
            {"id": 2, "name": "SEG-Bad"},
        ]
        api = MagicMock()
        api.get_user_tours_list.return_value = tours

        def side_effect(tour_id: Any, cache_dir: Any):
            if tour_id == 2:
                raise Exception("timeout")

        api.download_tour_gpx.side_effect = side_effect

        downloaded = download_segments(
            api, prefix="SEG-", cache_dir=str(tmp_path))
        assert len(downloaded) == 1
        assert downloaded[0][0] == 1


# ---------------------------------------------------------------------------
# login (rbw_get integration)
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_success(self, monkeypatch: pytest.MonkeyPatch):
        from summit.komoot import login

        monkeypatch.setattr(
            "summit.komoot.get_credential",
            lambda service, field: "test@email.com" if field == "username" else "testpass",
        )
        mock_api = MagicMock()
        mock_api.login.return_value = True
        monkeypatch.setattr("summit.komoot.API", lambda: mock_api)

        api = login()
        assert api is mock_api
        mock_api.login.assert_called_once_with("test@email.com", "testpass")

    def test_login_failure_raises(self, monkeypatch: pytest.MonkeyPatch):
        from summit.komoot import login

        monkeypatch.setattr(
            "summit.komoot.get_credential",
            lambda service, field: "test@email.com" if field == "username" else "testpass",
        )
        mock_api = MagicMock()
        mock_api.login.return_value = False
        monkeypatch.setattr("summit.komoot.API", lambda: mock_api)

        with pytest.raises(RuntimeError, match="Komoot login failed"):
            login()
