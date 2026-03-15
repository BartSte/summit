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

from summit.config import CONFIG_PATH, get_config


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
