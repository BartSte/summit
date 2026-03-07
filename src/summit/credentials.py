"""Pluggable credential system for summit.

Priority chain for get_credential(service, field):
1. SUMMIT_{SERVICE}_{FIELD} env var (direct value)
2. SUMMIT_{SERVICE}_{FIELD}_CMD env var (shell command, stdout is the value)
3. CredentialError with helpful message
"""
import os
import subprocess


class CredentialError(Exception):
    pass


def get_credential(service: str, field: str) -> str:
    """Return a credential value, consulting env vars in priority order."""
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
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise CredentialError(
                f"Credential command for {service}/{field} failed"
                f" (exit {result.returncode}):\n  {result.stderr.strip()}"
            )
        return result.stdout.strip()

    raise CredentialError(
        f"Missing credential for {service}/{field}.\n\n"
        f"Set one of:\n"
        f"  export {key}=\"your-{field}\"\n"
        f"  export {key}_CMD=\"rbw get '{service.title()}'\"\n"
        f"  export {key}_CMD=\"op item get '{service.title()}' --fields {field}\""
    )
