"""Load and cache the summit JSON config file.

Config path: ~/.config/summit/summit.json

The file is required. Missing file → CredentialError with setup instructions.
Invalid JSON → json.JSONDecodeError is raised.

Example config:
    {
        "garmin": {
            "username": "bart@example.com",
            "password_cmd": "rbw get --field password 'Garmin Connect'"
        },
        "komoot": {
            "username_cmd": "rbw get --field username 'Komoot'",
            "password_cmd": "rbw get --field password 'Komoot'"
        }
    }
"""
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "summit" / "summit.json"

_cache: dict | None = None


def _load() -> dict:
    """Read the config file from disk and return the parsed JSON dict.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def get_config() -> dict:
    """Return parsed config dict (loaded once, then cached).

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def _reset_cache() -> None:
    """Reset the module-level cache. For use in tests only."""
    global _cache
    _cache = None
