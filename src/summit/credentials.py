"""Pluggable credential system for summit.

Priority chain for get_credential(service, field):
1. SUMMIT_{SERVICE}_{FIELD} env var (direct value)
2. SUMMIT_{SERVICE}_{FIELD}_CMD env var (shell command, stdout is the value)
3. ~/.config/summit/summit.json (JSON config file)
4. CredentialError with helpful message
"""
import os
import subprocess

from summit.config import CONFIG_PATH, get_config


class CredentialError(Exception):
    """Raised when a required credential cannot be resolved."""


def get_credential(service: str, field: str) -> str:
    """Return a credential value by consulting the priority chain.

    Priority:
        1. ``SUMMIT_{SERVICE}_{FIELD}`` environment variable.
        2. ``SUMMIT_{SERVICE}_{FIELD}_CMD`` environment variable (shell
           command whose stdout is used as the value).
        3. ``~/.config/summit/summit.json`` config file.

    Args:
        service: Service name, e.g. ``"garmin"`` or ``"komoot"``.
        field: Credential field, e.g. ``"username"`` or ``"password"``.

    Returns:
        The resolved credential string.

    Raises:
        CredentialError: If no source provides the credential.
    """
    key = (
        f"SUMMIT_{service.upper().replace(' ', '_')}"
        f"_{field.upper().replace(' ', '_')}"
    )

    # 1. Direct env var
    value = os.environ.get(key)
    if value is not None:
        return value

    # 2. Command env var
    cmd = os.environ.get(f"{key}_CMD")
    if cmd is not None:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise CredentialError(
                f"Credential command for {service}/{field} failed"
                f" (exit {result.returncode}):\n  {result.stderr.strip()}"
            )
        return result.stdout.strip()

    # 3. JSON config file
    cfg = get_config()
    value = cfg.get(service.lower(), {}).get(field.lower())
    if value is not None:
        return value

    raise CredentialError(
        f"Missing credential for {service}/{field}.\n\n"
        f"Set one of:\n"
        f"  export {key}=\"your-{field}\"\n"
        f"  export {key}_CMD=\"rbw get '{service.title()}'\"\n"
        f"  export {key}_CMD=\"op item get '{service.title()}' --fields {field}\"\n"
        f"  {CONFIG_PATH}  "
        f"(JSON: {{\"{service.lower()}\": {{\"{field.lower()}\": \"value\"}}}})"
    )
