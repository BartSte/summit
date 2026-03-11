"""Load and cache the summit JSON config file.

Config path: ~/.config/summit/summit.json

Read at most once per process. Missing file → empty dict (no error).
Invalid JSON → json.JSONDecodeError is raised.
"""
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "summit" / "summit.json"

_cache: dict | None = None


def _load() -> dict:
    """Read the config file from disk and return the parsed JSON dict.

    Returns:
        Parsed config dict, or empty dict if the file does not exist.

    Raises:
        json.JSONDecodeError: If the file exists but contains invalid JSON.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return json.loads(text)


def get_config() -> dict:
    """Return parsed config dict (loaded once, then cached)."""
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def _reset_cache() -> None:
    """Reset the module-level cache. For use in tests only."""
    global _cache
    _cache = None
