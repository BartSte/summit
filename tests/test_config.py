"""Tests for summit.config — JSON config loading."""
import json
from pathlib import Path

import pytest

from summit.config import _reset_cache, get_config


class TestGetConfig:
    def setup_method(self):
        _reset_cache()

    def teardown_method(self):
        _reset_cache()

    def test_missing_file_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("summit.config.CONFIG_PATH", tmp_path / "no.json")
        with pytest.raises(FileNotFoundError):
            get_config()

    def test_valid_file_returned_as_dict(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        f = tmp_path / "summit.json"
        f.write_text('{"garmin": {"username": "a@b.com"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", f)
        assert get_config() == {"garmin": {"username": "a@b.com"}}

    def test_file_read_only_once(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        f = tmp_path / "summit.json"
        f.write_text('{"key": "first"}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", f)
        first = get_config()
        f.write_text('{"key": "second"}')
        assert get_config() is first  # same cached object

    def test_invalid_json_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        f = tmp_path / "summit.json"
        f.write_text("not valid json {{{")
        monkeypatch.setattr("summit.config.CONFIG_PATH", f)
        with pytest.raises(json.JSONDecodeError):
            get_config()

    def test_empty_file_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        f = tmp_path / "summit.json"
        f.write_text("")
        monkeypatch.setattr("summit.config.CONFIG_PATH", f)
        with pytest.raises(json.JSONDecodeError):
            get_config()
