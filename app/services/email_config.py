"""
Email configuration application service (use-case layer).

This module provides a provider-aware facade for UI/app use-cases so they don't
import `data_source/*` directly.

Design goals:
- Support multiple email providers (QQ / others).
- Allow providers to have different fields (e.g. auth_code vs OAuth tokens).
- Keep UI calling stable, provider-keyed methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple

from data_source.qq_email.config import QQEmailConfigManager


EmailFieldInputType = str  # "text" | "password" (keep lightweight for Streamlit)


@dataclass(frozen=True, slots=True)
class EmailProviderFieldSpec:
    """
    Field spec for a provider-specific email config form.

    Notes:
    - `secret=True` means the field is stored encrypted and should be masked in UI.
    - `input_type` is intentionally simple to map to Streamlit widgets.
    """

    key: str
    label: str
    help: str = ""
    required: bool = True
    secret: bool = False
    input_type: EmailFieldInputType = "text"
    mask_head: int = 2
    mask_tail: int = 2


@dataclass(frozen=True, slots=True)
class EmailProviderSpec:
    provider_key: str
    display_name: str
    fields: tuple[EmailProviderFieldSpec, ...]

    def field_keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)

    def secret_field_keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields if f.secret)

    def public_field_keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields if not f.secret)


class EmailConfigProviderAdapter(Protocol):
    provider_key: str

    def config_present(self) -> bool: ...

    def load_config_strict(self) -> Dict[str, str]: ...

    def save_config(self, values: Dict[str, str]) -> None: ...

    def test_connection(self, values: Dict[str, str]) -> Tuple[bool, str]: ...

    def delete_config(self) -> bool: ...


class _QQEmailConfigAdapter:
    provider_key = "qq"

    def __init__(self, manager: Optional[QQEmailConfigManager] = None) -> None:
        self._manager = manager or QQEmailConfigManager()

    def config_present(self) -> bool:
        return self._manager.config_present()

    def load_config_strict(self) -> Dict[str, str]:
        return self._manager.load_config_strict()

    def save_config(self, values: Dict[str, str]) -> None:
        email = str(values.get("email", "") or "")
        auth_code = str(values.get("auth_code", "") or "")
        self._manager.save_config(email=email, auth_code=auth_code)

    def test_connection(self, values: Dict[str, str]) -> Tuple[bool, str]:
        email = str(values.get("email", "") or "")
        auth_code = str(values.get("auth_code", "") or "")
        return self._manager.test_connection(email=email, auth_code=auth_code)

    def delete_config(self) -> bool:
        return self._manager.delete_config()


def build_builtin_provider_specs() -> dict[str, EmailProviderSpec]:
    """
    Return builtin provider specs.

    Notes:
    - Returns a new dict each time to avoid runtime global mutation.
    - Specs are immutable dataclasses and safe to share.
    """
    return {
        "qq": EmailProviderSpec(
            provider_key="qq",
            display_name="QQ邮箱",
            fields=(
                EmailProviderFieldSpec(
                    key="email",
                    label="邮箱地址",
                    help="请输入您的 QQ 邮箱地址",
                    required=True,
                    secret=False,
                    input_type="text",
                ),
                EmailProviderFieldSpec(
                    key="auth_code",
                    label="授权码",
                    help="请输入 QQ 邮箱的 IMAP 授权码（不是 QQ 密码）。",
                    required=True,
                    secret=True,
                    input_type="password",
                    mask_head=2,
                    mask_tail=2,
                ),
            ),
        )
    }


def build_builtin_provider_adapters() -> dict[str, EmailConfigProviderAdapter]:
    """
    Return builtin provider adapters.

    Notes:
    - Returns a new dict each time to avoid runtime global mutation.
    - Adapters may hold state/resources, so we create new instances by default.
    """
    return {"qq": _QQEmailConfigAdapter()}


class EmailConfigService:
    """
    Provider-aware email config service.

    This is the stable entry point used by UI/app layer:
    - `provider_key` selects which adapter/spec is used.
    - Providers can define their own fields via `EmailProviderSpec`.
    """

    def __init__(
        self,
        *,
        provider_specs: Optional[dict[str, EmailProviderSpec]] = None,
        provider_adapters: Optional[dict[str, EmailConfigProviderAdapter]] = None,
    ) -> None:
        self._specs = (
            dict(provider_specs)
            if provider_specs is not None
            else build_builtin_provider_specs()
        )
        self._adapters = (
            dict(provider_adapters)
            if provider_adapters is not None
            else build_builtin_provider_adapters()
        )

    def list_provider_keys(self) -> tuple[str, ...]:
        keys = set(self._specs.keys()) | set(self._adapters.keys())
        return tuple(sorted(keys))

    def get_provider_spec(self, provider_key: str) -> EmailProviderSpec:
        key = str(provider_key or "").strip()
        if not key:
            raise ValueError("provider_key 不能为空")
        spec = self._specs.get(key)
        if not spec:
            raise KeyError(f"未知邮箱 provider：{key}")
        return spec

    def _get_adapter(self, provider_key: str) -> EmailConfigProviderAdapter:
        key = str(provider_key or "").strip()
        if not key:
            raise ValueError("provider_key 不能为空")
        adapter = self._adapters.get(key)
        if not adapter:
            raise KeyError(f"未注册邮箱 provider adapter：{key}")
        return adapter

    def config_present(self, *, provider_key: str) -> bool:
        return bool(self._get_adapter(provider_key).config_present())

    def load_config_strict(self, *, provider_key: str) -> Dict[str, str]:
        return self._get_adapter(provider_key).load_config_strict()

    def save_config(self, *, provider_key: str, values: Dict[str, str]) -> None:
        self._get_adapter(provider_key).save_config(values)

    def test_connection(
        self, *, provider_key: str, values: Dict[str, str]
    ) -> Tuple[bool, str]:
        return self._get_adapter(provider_key).test_connection(values)

    def delete_config(self, *, provider_key: str) -> bool:
        return bool(self._get_adapter(provider_key).delete_config())
