"""Pluggable credential system for summit.

Credentials are read exclusively from ~/.config/summit/summit.json.

For each field, the lookup order is:
1. ``<field>_cmd`` key  — run as a shell command; stdout is the value.
2. ``<field>``          — plain string value.

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
import subprocess
from pathlib import Path

from summit.config import CONFIG_PATH, get_config

GARMIN_TOKEN_DIR = Path.home() / ".cache" / "garmin" / "tokens"


class CredentialError(Exception):
    """Raised when a required credential cannot be resolved."""


def get_credential(service: str, field: str) -> str:
    """Return a credential value from the JSON config file.

    Lookup order within the service block:
        1. ``<field>_cmd`` — shell command whose stdout is used as the value.
        2. ``<field>``     — plain string value.

    Args:
        service: Service name, e.g. ``"garmin"`` or ``"komoot"``.
        field: Credential field, e.g. ``"username"`` or ``"password"``.

    Returns:
        The resolved credential string.

    Raises:
        CredentialError: If the credential cannot be resolved.
    """
    svc = service.lower()
    fld = field.lower()

    cfg = get_config()
    svc_cfg = cfg.get(svc, {})

    # 1. Command key
    cmd = svc_cfg.get(f"{fld}_cmd")
    if cmd is not None:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise CredentialError(
                f"Credential command for {service}/{field} failed"
                f" (exit {result.returncode}):\n  {result.stderr.strip()}"
            )
        return result.stdout.strip()

    # 2. Plain value
    value = svc_cfg.get(fld)
    if value is not None:
        return value

    raise CredentialError(
        f"Missing credential '{field}' for service '{service}'.\n\n"
        f"Add it to {CONFIG_PATH}:\n"
        f'{{\n'
        f'    "{svc}": {{\n'
        f'        "{fld}": "your-{fld}",\n'
        f'        "  or use a command:": "",\n'
        f'        "{fld}_cmd": "rbw get --field {fld} \'{service.title()}\'"\n'
        f'    }}\n'
        f'}}'
    )


def get_garmin_client() -> "Garmin":
    """Return an authenticated Garmin client using cached OAuth tokens.

    On first use, performs a full SSO login and saves tokens to
    ``~/.cache/garmin/tokens``. On subsequent calls the tokens are loaded
    from disk and the SSO flow is skipped entirely, preventing Garmin from
    sending password-reset security emails.

    Returns:
        Authenticated :class:`garminconnect.Garmin` instance.

    Raises:
        CredentialError: If credentials are missing.
        ImportError: If garminconnect is not installed.
    """
    try:
        from garminconnect import Garmin
    except ImportError as e:
        raise ImportError(
            "garminconnect not installed. Run: pipx inject summit garminconnect"
        ) from e

    user = get_credential("garmin", "username")
    passwd = get_credential("garmin", "password")

    GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client = Garmin(user, passwd)
    client.login(tokenstore=str(GARMIN_TOKEN_DIR))
    return client
