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
from app.services.email_config import QQEmailConfigService
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

    # Raw hint (non-secret, does not require decryption).
    email_raw: str

    # Decrypted config (only when state == "ok").
    email: Optional[str] = None
    auth_code_masked: str = ""

    # Optional error message for UI.
    error_message: str = ""

    @property
    def present(self) -> bool:
        return self.state != "not_present"

    @property
    def unlocked(self) -> bool:
        return self.state == "ok"


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


def get_email_config_ui_snapshot(*, provider_key: str = "qq") -> EmailConfigUiSnapshot:
    raw = ""
    try:
        raw_email_cfg = get_config_manager().get_email_config(provider_key=provider_key)
        raw = str(raw_email_cfg.get("email", "") or "").strip()
    except Exception:
        raw = ""

    svc = QQEmailConfigService()
    has_master = bool(master_password_is_set())

    if not svc.config_present():
        return EmailConfigUiSnapshot(
            state="not_present",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
        )

    try:
        decrypted = svc.load_config_strict()
        email = str(decrypted.get("email", "") or "").strip()
        auth_code = str(decrypted.get("auth_code", "") or "")
        return EmailConfigUiSnapshot(
            state="ok",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
            email=email,
            auth_code_masked=_mask_secret(auth_code, head=2, tail=2),
        )
    except MasterPasswordNotSetError as e:
        return EmailConfigUiSnapshot(
            state="missing_master_password",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
            error_message=str(e),
        )
    except PlaintextSecretFoundError as e:
        return EmailConfigUiSnapshot(
            state="plaintext_secret",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
            error_message=str(e),
        )
    except SecretDecryptionError as e:
        return EmailConfigUiSnapshot(
            state="decrypt_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
            error_message=str(e),
        )
    except Exception as e:
        return EmailConfigUiSnapshot(
            state="load_failed",
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            email_raw=raw,
            error_message=str(e),
        )


def save_email_config_from_ui(
    *,
    email: str,
    auth_code_input: str,
    auth_code_masked_placeholder: str,
    provider_key: str = "qq",
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法保存加密配置。",
        )

    effective_auth_code = str(auth_code_input or "")
    if auth_code_masked_placeholder and auth_code_input == auth_code_masked_placeholder:
        snap = get_email_config_ui_snapshot(provider_key=provider_key)
        if snap.state == "ok" and snap.email:
            # Re-decrypt to obtain the real secret (UI should never handle plaintext).
            svc = QQEmailConfigService()
            try:
                decrypted = svc.load_config_strict()
                effective_auth_code = str(decrypted.get("auth_code", "") or "")
            except Exception:
                return UiActionResult(
                    ok=False,
                    message="❌ 无法读取已保存的授权码，请重新输入。",
                )

    try:
        QQEmailConfigService().save_config(email, effective_auth_code)
        return UiActionResult(ok=True, message="✅ 配置保存成功！")
    except ValueError as e:
        return UiActionResult(ok=False, message=f"❌ 输入错误：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def test_email_config_from_ui(
    *,
    email: str,
    auth_code_input: str,
    auth_code_masked_placeholder: str,
    provider_key: str = "qq",
) -> UiActionResult:
    if not master_password_is_set():
        return UiActionResult(
            ok=False,
            message=f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法读取加密配置。",
        )

    effective_auth_code = str(auth_code_input or "")
    if auth_code_masked_placeholder and auth_code_input == auth_code_masked_placeholder:
        svc = QQEmailConfigService()
        try:
            decrypted = svc.load_config_strict()
            effective_auth_code = str(decrypted.get("auth_code", "") or "")
        except Exception:
            return UiActionResult(
                ok=False, message="❌ 无法读取已保存的授权码，请重新输入。"
            )

    try:
        ok, msg = QQEmailConfigService().test_connection(email, effective_auth_code)
        return UiActionResult(ok=bool(ok), message=("✅ " if ok else "❌ ") + str(msg))
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 测试连接失败：{str(e)}")


def delete_email_config_from_ui(*, provider_key: str = "qq") -> UiActionResult:
    try:
        ok = QQEmailConfigService().delete_config()
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
