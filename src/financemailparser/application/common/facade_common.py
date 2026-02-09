from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from financemailparser.infrastructure.config.secrets import (
    MasterPasswordNotSetError,
    PlaintextSecretFoundError,
    SecretDecryptionError,
)


@dataclass(frozen=True)
class UiActionResult:
    ok: bool
    message: str


SecretLoadUiState = Literal[
    "missing_master_password",
    "plaintext_secret",
    "decrypt_failed",
    "load_failed",
]


def map_secret_load_error_to_ui_state(
    error: Exception,
) -> tuple[SecretLoadUiState, str]:
    if isinstance(error, MasterPasswordNotSetError):
        return "missing_master_password", str(error)
    if isinstance(error, PlaintextSecretFoundError):
        return "plaintext_secret", str(error)
    if isinstance(error, SecretDecryptionError):
        return "decrypt_failed", str(error)
    return "load_failed", str(error)


def mask_secret(value: str, *, head: int, tail: int) -> str:
    """
    Mask secret for UI placeholders.

    Example:
    - head=2, tail=2: "abcdef" -> "ab***ef"
    """
    if not value:
        return ""

    raw = str(value)
    if len(raw) <= head + tail:
        return "*" * len(raw)
    prefix = raw[:head] if head > 0 else ""
    suffix = raw[-tail:] if tail > 0 else ""
    return f"{prefix}***{suffix}"
