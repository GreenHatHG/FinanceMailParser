"""
UI configuration facade (use-case / app layer).

Goal:
- Keep `ui/pages/*.py` free from direct imports of `config/*` and `ai/config.py`.
- Centralize "config present / locked / plaintext / decrypt failed" branching.
- Provide UI-friendly snapshots and action helpers (save/test/delete).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from ai.config import AIConfig, AIConfigManager
from ai.providers import AI_PROVIDER_CHOICES
from app.services.email_config import EmailConfigService, EmailProviderSpec
from config.config_manager import get_config_manager
from config.secrets import (
    MASTER_PASSWORD_ENV,
    MasterPasswordNotSetError,
    PlaintextSecretFoundError,
    SecretDecryptionError,
    master_password_is_set,
)


EmailConfigUiState = Literal[
    "not_present",
    "ok",
    "missing_master_password",
    "plaintext_secret",
    "decrypt_failed",
    "load_failed",
]

AiConfigUiState = Literal[
    "not_present",
    "ok",
    "missing_master_password",
    "plaintext_secret",
    "decrypt_failed",
    "load_failed",
]


@dataclass(frozen=True)
class EmailConfigUiSnapshot:
    state: EmailConfigUiState
    master_password_env: str
    master_password_is_set: bool

    provider_key: str

    # Raw hints (non-secret, do not require decryption).
    raw_values: dict[str, str]

    # Decrypted config (only when state == "ok").
    ok_public_values: dict[str, str] | None = None
    secret_masked: dict[str, str] | None = None

    # Optional error message for UI.
    error_message: str = ""

    @property
    def present(self) -> bool:
        return self.state != "not_present"

    @property
    def unlocked(self) -> bool:
        return self.state == "ok"

    @property
    def email_raw(self) -> str:
        return str((self.raw_values or {}).get("email", "") or "")

    @property
    def email(self) -> Optional[str]:
        if self.ok_public_values is None:
            return None
        value = str(self.ok_public_values.get("email", "") or "").strip()
        return value or None

    @property
    def auth_code_masked(self) -> str:
        if not self.secret_masked:
            return ""
        return str(self.secret_masked.get("auth_code", "") or "")


@dataclass(frozen=True)
class AiConfigUiSnapshot:
    state: AiConfigUiState
    master_password_env: str
    master_password_is_set: bool

    # Non-secret defaults (read directly from config.yaml, no decryption required).
    provider_default: str
    model_default: str
    base_url_default: str
    timeout_default: int
    max_retries_default: int
    retry_interval_default: int

    # Decrypted fields (only when state == "ok").
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key_masked: str = ""

    error_message: str = ""

    @property
    def present(self) -> bool:
        return self.state != "not_present"

    @property
    def unlocked(self) -> bool:
        return self.state == "ok"


@dataclass(frozen=True)
class UiActionResult:
    ok: bool
    message: str


def _mask_secret(value: str, *, head: int, tail: int) -> str:
    if not value:
        return ""

    raw = str(value)
    if len(raw) <= head + tail:
        return "*" * len(raw)
    return f"{raw[:head]}***{raw[-tail:]}"


def get_email_provider_spec(*, provider_key: str = "qq") -> EmailProviderSpec:
    return EmailConfigService().get_provider_spec(provider_key)


def get_email_config_ui_snapshot(*, provider_key: str = "qq") -> EmailConfigUiSnapshot:
    provider_key = str(provider_key or "").strip() or "qq"
    svc = EmailConfigService()
    spec = svc.get_provider_spec(provider_key)

    raw_values: dict[str, str] = {}
    try:
        raw_email_cfg = get_config_manager().get_email_config(provider_key=provider_key)
        for field in spec.fields:
            if field.secret:
                continue
            raw_values[field.key] = str(raw_email_cfg.get(field.key, "") or "").strip()
    except Exception:
        raw_values = {}
    has_master = bool(master_password_is_set())

    if not svc.config_present(provider_key=provider_key):
        return EmailConfigUiSnapshot(
            state="not_present",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
        )

    try:
        decrypted = svc.load_config_strict(provider_key=provider_key)
        ok_public_values: dict[str, str] = {}
        secret_masked: dict[str, str] = {}
        for field in spec.fields:
            raw_val = str(decrypted.get(field.key, "") or "")
            if field.secret:
                secret_masked[field.key] = _mask_secret(
                    raw_val, head=field.mask_head, tail=field.mask_tail
                )
            else:
                ok_public_values[field.key] = raw_val.strip()

        return EmailConfigUiSnapshot(
            state="ok",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            ok_public_values=ok_public_values,
            secret_masked=secret_masked,
        )
    except MasterPasswordNotSetError as e:
        return EmailConfigUiSnapshot(
            state="missing_master_password",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            error_message=str(e),
        )
    except PlaintextSecretFoundError as e:
        return EmailConfigUiSnapshot(
            state="plaintext_secret",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            error_message=str(e),
        )
    except SecretDecryptionError as e:
        return EmailConfigUiSnapshot(
            state="decrypt_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            error_message=str(e),
        )
    except Exception as e:
        return EmailConfigUiSnapshot(
            state="load_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            error_message=str(e),
        )


def _build_effective_email_config_values(
    *,
    provider_key: str,
    values: dict[str, str],
    masked_placeholders: dict[str, str],
) -> dict[str, str] | UiActionResult:
    svc = EmailConfigService()
    spec = svc.get_provider_spec(provider_key)

    raw_values: dict[str, str] = {k: str(v or "") for k, v in (values or {}).items()}
    placeholders = {k: str(v or "") for k, v in (masked_placeholders or {}).items()}

    needs_decrypt = False
    for field in spec.fields:
        if not field.secret:
            continue
        placeholder = placeholders.get(field.key, "")
        if placeholder and raw_values.get(field.key, "") == placeholder:
            needs_decrypt = True
            break

    decrypted_existing: dict[str, str] = {}
    if needs_decrypt:
        try:
            decrypted_existing = svc.load_config_strict(provider_key=provider_key)
        except Exception:
            return UiActionResult(
                ok=False, message="❌ 无法读取已保存的密钥字段，请重新输入。"
            )

    effective: dict[str, str] = {}
    for field in spec.fields:
        incoming = str(raw_values.get(field.key, "") or "")
        if field.secret:
            placeholder = placeholders.get(field.key, "")
            if placeholder and incoming == placeholder:
                incoming = str(decrypted_existing.get(field.key, "") or "")
        effective[field.key] = incoming

    missing_labels: list[str] = []
    for field in spec.fields:
        if not field.required:
            continue
        if not str(effective.get(field.key, "") or "").strip():
            missing_labels.append(field.label)
    if missing_labels:
        return UiActionResult(
            ok=False, message=f"❌ 请填写完整信息：{', '.join(missing_labels)}"
        )

    return effective


def save_email_config_from_ui(
    *,
    provider_key: str = "qq",
    values: dict[str, str],
    masked_placeholders: dict[str, str],
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法保存加密配置。",
        )

    provider_key = str(provider_key or "").strip() or "qq"
    effective = _build_effective_email_config_values(
        provider_key=provider_key,
        values=values,
        masked_placeholders=masked_placeholders,
    )
    if isinstance(effective, UiActionResult):
        return effective

    try:
        EmailConfigService().save_config(provider_key=provider_key, values=effective)
        return UiActionResult(ok=True, message="✅ 配置保存成功！")
    except ValueError as e:
        return UiActionResult(ok=False, message=f"❌ 输入错误：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def test_email_config_from_ui(
    *,
    provider_key: str = "qq",
    values: dict[str, str],
    masked_placeholders: dict[str, str],
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法读取加密配置。",
        )

    provider_key = str(provider_key or "").strip() or "qq"
    effective = _build_effective_email_config_values(
        provider_key=provider_key,
        values=values,
        masked_placeholders=masked_placeholders,
    )
    if isinstance(effective, UiActionResult):
        return effective

    try:
        ok, msg = EmailConfigService().test_connection(
            provider_key=provider_key, values=effective
        )
        return UiActionResult(ok=bool(ok), message=("✅ " if ok else "❌ ") + str(msg))
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 测试连接失败：{str(e)}")


def delete_email_config_from_ui(*, provider_key: str = "qq") -> UiActionResult:
    try:
        provider_key = str(provider_key or "").strip() or "qq"
        ok = EmailConfigService().delete_config(provider_key=provider_key)
        return UiActionResult(
            ok=bool(ok), message="✅ 配置已删除" if ok else "❌ 删除失败"
        )
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 删除失败：{str(e)}")


def get_ai_config_ui_snapshot() -> AiConfigUiSnapshot:
    raw_ai: dict[str, Any] = {}
    try:
        raw_ai = get_config_manager().get_ai_config()
    except Exception:
        raw_ai = {}

    provider_default = str(raw_ai.get("provider", "openai") or "openai").strip()
    model_default = str(raw_ai.get("model", "") or "").strip()
    base_url_default = str(raw_ai.get("base_url", "") or "").strip()

    timeout_default = AIConfigManager.DEFAULT_TIMEOUT
    max_retries_default = AIConfigManager.DEFAULT_MAX_RETRIES
    retry_interval_default = AIConfigManager.DEFAULT_RETRY_INTERVAL
    try:
        timeout_default = int(raw_ai.get("timeout", timeout_default) or timeout_default)
        max_retries_default = int(
            raw_ai.get("max_retries", max_retries_default) or max_retries_default
        )
        retry_interval_default = int(
            raw_ai.get("retry_interval", retry_interval_default)
            or retry_interval_default
        )
    except Exception:
        pass

    mgr = AIConfigManager()
    has_master = bool(master_password_is_set())

    if not mgr.config_present():
        return AiConfigUiSnapshot(
            state="not_present",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or "openai",
            model_default=model_default,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
        )

    try:
        decrypted = mgr.load_config_strict()
        provider = str(decrypted.provider or "").strip()
        model = str(decrypted.model or "").strip()
        api_key = str(decrypted.api_key or "")
        return AiConfigUiSnapshot(
            state="ok",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or provider or "openai",
            model_default=model_default or model,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
            provider=provider,
            model=model,
            api_key_masked=_mask_secret(api_key, head=4, tail=4),
        )
    except MasterPasswordNotSetError as e:
        return AiConfigUiSnapshot(
            state="missing_master_password",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or "openai",
            model_default=model_default,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
            error_message=str(e),
        )
    except PlaintextSecretFoundError as e:
        return AiConfigUiSnapshot(
            state="plaintext_secret",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or "openai",
            model_default=model_default,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
            error_message=str(e),
        )
    except SecretDecryptionError as e:
        return AiConfigUiSnapshot(
            state="decrypt_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or "openai",
            model_default=model_default,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
            error_message=str(e),
        )
    except Exception as e:
        return AiConfigUiSnapshot(
            state="load_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_default=provider_default or "openai",
            model_default=model_default,
            base_url_default=base_url_default,
            timeout_default=timeout_default,
            max_retries_default=max_retries_default,
            retry_interval_default=retry_interval_default,
            error_message=str(e),
        )


def save_ai_config_from_ui(
    *,
    provider: str,
    model: str,
    api_key_input: str,
    api_key_masked_placeholder: str,
    base_url: str,
    timeout: int,
    max_retries: int,
    retry_interval: int,
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法保存加密配置。",
        )

    effective_api_key = str(api_key_input or "")
    if api_key_masked_placeholder and api_key_input == api_key_masked_placeholder:
        try:
            decrypted = AIConfigManager().load_config_strict()
            effective_api_key = str(decrypted.api_key or "")
        except Exception:
            return UiActionResult(
                ok=False, message="❌ 无法读取已保存的 API Key，请重新输入。"
            )

    try:
        AIConfigManager().save_config(
            AIConfig(
                provider=provider,
                model=model,
                api_key=effective_api_key,
                base_url=base_url,
                timeout=int(timeout),
                max_retries=int(max_retries),
                retry_interval=int(retry_interval),
            )
        )
        return UiActionResult(ok=True, message="✅ 配置保存成功！")
    except ValueError as e:
        return UiActionResult(ok=False, message=f"❌ 输入错误：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def test_ai_config_from_ui(
    *,
    provider: str,
    model: str,
    api_key_input: str,
    api_key_masked_placeholder: str,
    base_url: str,
    timeout: int,
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法读取加密配置。",
        )

    effective_api_key = str(api_key_input or "")
    if api_key_masked_placeholder and api_key_input == api_key_masked_placeholder:
        try:
            decrypted = AIConfigManager().load_config_strict()
            effective_api_key = str(decrypted.api_key or "")
        except Exception:
            return UiActionResult(
                ok=False, message="❌ 无法读取已保存的 API Key，请重新输入。"
            )

    try:
        ok, msg = AIConfigManager().test_connection(
            AIConfig(
                provider=provider,
                model=model,
                api_key=effective_api_key,
                base_url=base_url,
                timeout=int(timeout),
            )
        )
        return UiActionResult(ok=bool(ok), message=("✅ " if ok else "❌ ") + str(msg))
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 测试连接失败：{str(e)}")


def delete_ai_config_from_ui() -> UiActionResult:
    try:
        ok = AIConfigManager().delete_config()
        return UiActionResult(
            ok=bool(ok), message="✅ 配置已删除" if ok else "❌ 删除失败"
        )
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 删除失败：{str(e)}")


def estimate_prompt_tokens_from_ui(prompt: str) -> Optional[int]:
    """
    Best-effort token estimation for UI preview.

    Notes:
    - Requires decryptable AI config (provider/model) to select a token counter model.
    - Returns None on any failure; caller should treat it as "unknown".
    """
    try:
        import litellm
        from ai.providers import strip_litellm_model_prefix

        cfg = AIConfigManager().load_config()
        if not cfg:
            return None

        token_count_model = strip_litellm_model_prefix(cfg.provider, cfg.model)
        if not token_count_model:
            return None

        return int(
            litellm.token_counter(
                model=token_count_model,
                messages=[{"role": "user", "content": str(prompt or "")}],
            )
        )
    except Exception:
        return None


def get_ai_config_manager_for_ui() -> AIConfigManager:
    """
    Provide an AIConfigManager instance for UI -> app service calls.

    UI should not import `ai.config` directly.
    """
    return AIConfigManager()


def get_ai_provider_choices_for_ui() -> tuple[str, ...]:
    """
    Provide AI provider choices for UI.

    UI should not import `ai.providers` directly.
    """
    return AI_PROVIDER_CHOICES
