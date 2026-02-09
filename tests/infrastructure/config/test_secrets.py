from __future__ import annotations

import base64

import pytest

from financemailparser.infrastructure.config.secrets import (
    ENC_PREFIX,
    ENC_SUFFIX,
    ENC_VERSION,
    MASTER_PASSWORD_ENV,
    InvalidEncryptedSecretError,
    MasterPasswordNotSetError,
    SecretBox,
    SecretDecryptionError,
    is_encrypted_value,
    master_password_is_set,
    parse_encrypted_value,
)


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _enc_value(*, version: str, salt: bytes, nonce: bytes, ciphertext: bytes) -> str:
    return f"{ENC_PREFIX}{version}|{_b64e(salt)}|{_b64e(nonce)}|{_b64e(ciphertext)}{ENC_SUFFIX}"


def test_master_password_is_set_false_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MASTER_PASSWORD_ENV, raising=False)
    assert master_password_is_set() is False


def test_encrypt_requires_master_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MASTER_PASSWORD_ENV, raising=False)
    with pytest.raises(MasterPasswordNotSetError):
        SecretBox.encrypt("abc")


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    value = SecretBox.encrypt("hello", aad="config.yaml")
    assert is_encrypted_value(value) is True
    assert SecretBox.decrypt(value, aad="config.yaml") == "hello"


def test_decrypt_fails_with_wrong_master_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    value = SecretBox.encrypt("hello")

    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-2")
    with pytest.raises(SecretDecryptionError):
        SecretBox.decrypt(value)


def test_parse_encrypted_value_rejects_malformed_payload() -> None:
    with pytest.raises(InvalidEncryptedSecretError):
        parse_encrypted_value("not-enc")

    with pytest.raises(InvalidEncryptedSecretError):
        parse_encrypted_value(f"{ENC_PREFIX}{ENC_VERSION}|a|b{ENC_SUFFIX}")

    with pytest.raises(InvalidEncryptedSecretError):
        parse_encrypted_value(f"{ENC_PREFIX}v0|a|b|c{ENC_SUFFIX}")

    with pytest.raises(InvalidEncryptedSecretError):
        parse_encrypted_value(f"{ENC_PREFIX}{ENC_VERSION}|@@|@@|@@{ENC_SUFFIX}")


def test_parse_encrypted_value_validates_nonce_length() -> None:
    value = _enc_value(
        version=ENC_VERSION,
        salt=b"0" * 16,
        nonce=b"1" * 11,  # AESGCM requires 12 bytes
        ciphertext=b"2" * 16,
    )
    with pytest.raises(InvalidEncryptedSecretError):
        parse_encrypted_value(value)
