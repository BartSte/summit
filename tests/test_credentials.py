"""Tests for summit.credentials — config-file-only credential system."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summit.config import _reset_cache
from summit.credentials import CredentialError, get_credential


@pytest.fixture(autouse=True)
def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point CONFIG_PATH at a temp file and reset cache around each test."""
    monkeypatch.setattr("summit.config.CONFIG_PATH", tmp_path / "summit.json")
    monkeypatch.setattr("summit.credentials.CONFIG_PATH", tmp_path / "summit.json")
    _reset_cache()
    yield
    _reset_cache()


def write_cfg(tmp_path: Path, data: dict) -> Path:
    import json
    cfg = tmp_path / "summit.json"
    cfg.write_text(json.dumps(data))
    return cfg


class TestPlainValue:
    def test_plain_value_returned(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"username": "bart@example.com"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        assert get_credential("garmin", "username") == "bart@example.com"

    def test_service_and_field_lowercased(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"password": "secret"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        assert get_credential("Garmin", "Password") == "secret"

    def test_komoot_plain_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"komoot": {"username": "user@example.com"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        assert get_credential("komoot", "username") == "user@example.com"


class TestCmdValue:
    def test_cmd_key_runs_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"password_cmd": "rbw get 'Garmin Connect'"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "my-secret\n"

        with patch("summit.credentials.subprocess.run", return_value=mock_result) as mock_run:
            result = get_credential("garmin", "password")

        assert result == "my-secret"
        mock_run.assert_called_once_with(
            "rbw get 'Garmin Connect'",
            shell=True,
            capture_output=True,
            text=True,
        )

    def test_cmd_stdout_stripped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"komoot": {"username_cmd": "op item get Komoot --fields username"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  user@example.com  \n"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            assert get_credential("komoot", "username") == "user@example.com"

    def test_cmd_takes_priority_over_plain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {
            "password": "plain-value",
            "password_cmd": "echo cmd-value",
        }})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "cmd-value\n"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            assert get_credential("garmin", "password") == "cmd-value"

    def test_cmd_nonzero_exit_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"password_cmd": "false"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "entry not found"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            with pytest.raises(CredentialError) as exc_info:
                get_credential("garmin", "password")

        assert "entry not found" in str(exc_info.value)

    def test_cmd_nonzero_exit_includes_exit_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"password_cmd": "false"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()

        mock_result = MagicMock()
        mock_result.returncode = 127
        mock_result.stderr = "command not found"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            with pytest.raises(CredentialError) as exc_info:
                get_credential("garmin", "password")

        assert "127" in str(exc_info.value)


class TestMissingCredential:
    def test_missing_config_file_raises(self):
        # autouse fixture points to a non-existent file
        with pytest.raises(FileNotFoundError):
            get_credential("garmin", "password")

    def test_missing_service_raises_credential_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"komoot": {"password": "x"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        with pytest.raises(CredentialError):
            get_credential("garmin", "password")

    def test_missing_field_raises_credential_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {"username": "u"}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        with pytest.raises(CredentialError):
            get_credential("garmin", "password")

    def test_error_message_mentions_service_and_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "username")
        msg = str(exc_info.value)
        assert "garmin" in msg
        assert "username" in msg

    def test_error_message_mentions_config_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = write_cfg(tmp_path, {"garmin": {}})
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        _reset_cache()
        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "password")
        assert "summit.json" in str(exc_info.value)
