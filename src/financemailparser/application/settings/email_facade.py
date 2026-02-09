"""
Email configuration facade (use-case / app layer).

Goal:
- Keep `ui/pages/*.py` free from direct imports of `config/*` and `data_source/*`.
- Centralize "config present / locked / plaintext / decrypt failed" branching.
- Provide UI-friendly snapshots and action helpers (save/test/delete).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from financemailparser.application.settings.email_service import (
    EmailConfigService,
    EmailProviderSpec,
)
from financemailparser.application.common.facade_common import (
    UiActionResult,
    map_secret_load_error_to_ui_state,
    mask_secret,
)
from financemailparser.infrastructure.config.config_manager import get_config_manager
from financemailparser.infrastructure.config.secrets import (
    MASTER_PASSWORD_ENV,
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
                secret_masked[field.key] = mask_secret(
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
    except Exception as e:
        state, error_message = map_secret_load_error_to_ui_state(e)
        return EmailConfigUiSnapshot(
            state=state,
            master_password_env=MASTER_PASSWORD_ENV,
            master_password_is_set=has_master,
            provider_key=provider_key,
            raw_values=raw_values,
            error_message=error_message,
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
