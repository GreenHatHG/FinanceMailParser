"""
配置敏感信息加/解密（可搬运）

设计目标：
- 敏感字段（如 API Key / 邮箱授权码）不再以明文写入 config.yaml
- 仅依赖环境变量 FINANCEMAILPARSER_MASTER_PASSWORD 作为主密码来源（不落盘）
- config.yaml 可复制到另一台机器使用：只要提供同一主密码即可解密
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_PASSWORD_ENV = "FINANCEMAILPARSER_MASTER_PASSWORD"

# Format: ENC[v1|<salt_b64>|<nonce_b64>|<ciphertext_b64>]
ENC_PREFIX = "ENC["
ENC_SUFFIX = "]"
ENC_VERSION = "v1"


class SecretError(Exception):
    """Base class for secret-related errors (user-facing message in args[0])."""


class MasterPasswordNotSetError(SecretError):
    """Raised when FINANCEMAILPARSER_MASTER_PASSWORD is missing/empty."""


class PlaintextSecretFoundError(SecretError):
    """Raised when a sensitive field is detected as plaintext in config.yaml."""


class InvalidEncryptedSecretError(SecretError):
    """Raised when ENC[...] payload is malformed or unsupported."""


class SecretDecryptionError(SecretError):
    """Raised when decryption fails (wrong password or corrupted data)."""


def master_password_is_set() -> bool:
    raw = os.getenv(MASTER_PASSWORD_ENV, "")
    return isinstance(raw, str) and bool(raw.strip())


def _get_master_password_bytes() -> bytes:
    raw = os.getenv(MASTER_PASSWORD_ENV, "")
    if not isinstance(raw, str) or not raw.strip():
        raise MasterPasswordNotSetError(
            f"未设置主密码环境变量 {MASTER_PASSWORD_ENV}，无法解密/加密配置"
        )
    return raw.encode("utf-8")


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def _derive_key(master_password: bytes, salt: bytes) -> bytes:
    # scrypt is available in Python stdlib (hashlib.scrypt).
    # Parameters are chosen to be reasonably strong while keeping UI responsive.
    return hashlib.scrypt(
        master_password,
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,  # AES-256
    )


@dataclass(frozen=True)
class EncryptedPayload:
    version: str
    salt: bytes
    nonce: bytes
    ciphertext: bytes


def is_encrypted_value(value: object) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX) and value.endswith(ENC_SUFFIX)


def parse_encrypted_value(value: str) -> EncryptedPayload:
    if not is_encrypted_value(value):
        raise InvalidEncryptedSecretError("不是合法的加密字段（缺少 ENC[...] 前缀）")

    inner = value[len(ENC_PREFIX) : -len(ENC_SUFFIX)]
    parts = inner.split("|")
    if len(parts) != 4:
        raise InvalidEncryptedSecretError("加密字段格式错误（应为 ENC[v1|salt|nonce|cipher]）")

    version, salt_b64, nonce_b64, cipher_b64 = parts
    if version != ENC_VERSION:
        raise InvalidEncryptedSecretError(f"不支持的加密版本：{version}")

    try:
        salt = _b64d(salt_b64)
        nonce = _b64d(nonce_b64)
        ciphertext = _b64d(cipher_b64)
    except Exception as e:
        raise InvalidEncryptedSecretError("加密字段 base64 解码失败") from e

    if len(salt) < 16:
        raise InvalidEncryptedSecretError("salt 长度不合法")
    if len(nonce) != 12:
        raise InvalidEncryptedSecretError("nonce 长度不合法（AESGCM 需要 12 字节）")
    if len(ciphertext) < 16:
        raise InvalidEncryptedSecretError("ciphertext 长度不合法")

    return EncryptedPayload(version=version, salt=salt, nonce=nonce, ciphertext=ciphertext)


class SecretBox:
    """
    Small helper for encrypting/decrypting secrets stored in config.yaml.

    Note: Master password is ONLY sourced from env var FINANCEMAILPARSER_MASTER_PASSWORD.
    """

    @staticmethod
    def encrypt(plaintext: str, *, aad: Optional[str] = None) -> str:
        if plaintext is None or not str(plaintext):
            raise ValueError("明文不能为空")

        master = _get_master_password_bytes()
        salt = os.urandom(16)
        key = _derive_key(master, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        aad_bytes = aad.encode("utf-8") if aad else None

        ciphertext = aesgcm.encrypt(nonce, str(plaintext).encode("utf-8"), aad_bytes)
        return (
            f"{ENC_PREFIX}{ENC_VERSION}|{_b64e(salt)}|{_b64e(nonce)}|{_b64e(ciphertext)}{ENC_SUFFIX}"
        )

    @staticmethod
    def decrypt(value: str, *, aad: Optional[str] = None) -> str:
        payload = parse_encrypted_value(value)

        master = _get_master_password_bytes()
        key = _derive_key(master, payload.salt)
        aesgcm = AESGCM(key)
        aad_bytes = aad.encode("utf-8") if aad else None

        try:
            plaintext_bytes = aesgcm.decrypt(payload.nonce, payload.ciphertext, aad_bytes)
        except Exception as e:
            raise SecretDecryptionError("主密码错误或配置已损坏，无法解密") from e

        try:
            return plaintext_bytes.decode("utf-8")
        except Exception as e:
            raise SecretDecryptionError("解密结果不是有效的 UTF-8 字符串") from e
