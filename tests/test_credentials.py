"""Tests for summit.credentials — pluggable credential system."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summit.config import _reset_cache
from summit.credentials import CredentialError, get_credential


class TestGetCredential:
    @pytest.fixture(autouse=True)
    def _no_config_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("summit.config.CONFIG_PATH",
                            tmp_path / "no-config.json")
        _reset_cache()
        yield
        _reset_cache()
    # ------------------------------------------------------------------
    # Direct env var
    # ------------------------------------------------------------------

    def test_direct_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD", "secret123")
        assert get_credential("garmin", "password") == "secret123"

    def test_direct_env_var_takes_priority_over_cmd(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD", "direct-value")
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD_CMD", "echo cmd-value")
        assert get_credential("garmin", "password") == "direct-value"

    def test_direct_env_var_komoot_username(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_KOMOOT_USERNAME", "user@example.com")
        assert get_credential("komoot", "username") == "user@example.com"

    # ------------------------------------------------------------------
    # Command env var
    # ------------------------------------------------------------------

    def test_command_env_var_calls_subprocess(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD_CMD",
                           "rbw get 'Garmin Connect'")
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)

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

    def test_command_stdout_stripped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_KOMOOT_USERNAME_CMD",
                           "op item get Komoot --fields username")
        monkeypatch.delenv("SUMMIT_KOMOOT_USERNAME", raising=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  user@example.com  \n"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            result = get_credential("komoot", "username")

        assert result == "user@example.com"

    def test_command_non_zero_exit_raises_credential_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD_CMD", "false")
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "entry not found"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            with pytest.raises(CredentialError) as exc_info:
                get_credential("garmin", "password")

        assert "entry not found" in str(exc_info.value)

    def test_command_non_zero_exit_includes_exit_code(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD_CMD", "false")
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)

        mock_result = MagicMock()
        mock_result.returncode = 127
        mock_result.stderr = "command not found"

        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            with pytest.raises(CredentialError) as exc_info:
                get_credential("garmin", "password")

        assert "127" in str(exc_info.value)

    # ------------------------------------------------------------------
    # Missing both → helpful error
    # ------------------------------------------------------------------

    def test_missing_both_raises_credential_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)

        with pytest.raises(CredentialError):
            get_credential("garmin", "password")

    def test_error_message_mentions_service_and_field(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SUMMIT_GARMIN_USERNAME", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_USERNAME_CMD", raising=False)

        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "username")

        msg = str(exc_info.value)
        assert "garmin" in msg
        assert "username" in msg

    def test_error_message_shows_direct_var_name(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)

        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "password")

        assert "SUMMIT_GARMIN_PASSWORD" in str(exc_info.value)

    def test_error_message_shows_cmd_var_name(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)

        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "password")

        assert "SUMMIT_GARMIN_PASSWORD_CMD" in str(exc_info.value)

    # ------------------------------------------------------------------
    # Env var name generation
    # ------------------------------------------------------------------

    def test_service_with_spaces_maps_to_underscores(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_MY_SERVICE_MY_FIELD", "value")
        assert get_credential("my service", "my field") == "value"

    def test_mixed_case_service_normalized(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_GARMIN_USERNAME", "u@host.com")
        assert get_credential("Garmin", "Username") == "u@host.com"

    def test_uppercase_service_normalized(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SUMMIT_KOMOOT_PASSWORD", "pass")
        assert get_credential("KOMOOT", "PASSWORD") == "pass"

    def test_cmd_var_name_has_cmd_suffix(self, monkeypatch: pytest.MonkeyPatch):
        """Verify CMD lookup uses correct key format."""
        monkeypatch.delenv("SUMMIT_GARMIN_USERNAME", raising=False)
        # Only set the CMD var, not the direct var
        monkeypatch.setenv("SUMMIT_GARMIN_USERNAME_CMD", "echo testuser")
        monkeypatch.delenv("SUMMIT_GARMIN_USERNAME_CMD", raising=False)

        # Without either var, should raise
        with pytest.raises(CredentialError):
            get_credential("garmin", "username")

    # ------------------------------------------------------------------
    # JSON config file (step 3)
    # ------------------------------------------------------------------

    def test_json_config_returns_value(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        cfg = tmp_path / "summit.json"
        cfg.write_text('{"garmin": {"password": "from-config"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)
        _reset_cache()
        assert get_credential("garmin", "password") == "from-config"

    def test_env_var_beats_json_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        cfg = tmp_path / "summit.json"
        cfg.write_text('{"garmin": {"password": "config-value"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD", "env-value")
        _reset_cache()
        assert get_credential("garmin", "password") == "env-value"

    def test_cmd_beats_json_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        cfg = tmp_path / "summit.json"
        cfg.write_text('{"garmin": {"password": "config-value"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.setenv("SUMMIT_GARMIN_PASSWORD_CMD", "echo cmd-value")
        _reset_cache()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "cmd-value\n"
        with patch("summit.credentials.subprocess.run", return_value=mock_result):
            assert get_credential("garmin", "password") == "cmd-value"

    def test_missing_config_file_falls_through_to_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)
        # autouse fixture already points to a non-existent file
        with pytest.raises(CredentialError):
            get_credential("garmin", "password")

    def test_json_config_missing_service_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        cfg = tmp_path / "summit.json"
        cfg.write_text('{"komoot": {"password": "x"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)
        _reset_cache()
        with pytest.raises(CredentialError):
            get_credential("garmin", "password")

    def test_json_config_mixed_case_service(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        cfg = tmp_path / "summit.json"
        cfg.write_text('{"garmin": {"password": "lower"}}')
        monkeypatch.setattr("summit.config.CONFIG_PATH", cfg)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)
        _reset_cache()
        assert get_credential("Garmin", "Password") == "lower"

    def test_error_message_mentions_config_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("SUMMIT_GARMIN_PASSWORD_CMD", raising=False)
        with pytest.raises(CredentialError) as exc_info:
            get_credential("garmin", "password")
        assert "summit.json" in str(exc_info.value)
