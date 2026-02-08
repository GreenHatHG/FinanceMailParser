from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, TypedDict, cast

from constants import MASK_MAP_DIR
from ai.config import AIConfigManager
from ai.service import AIService, CallStats
from utils.amount_masking import AmountMasker, MaskingStats
from utils.beancount_validator import (
    AccountFillingReport,
    BeancountReconciler,
    ReconcileReport,
    reconcile_beancount,
)
from utils.prompt_builder_v2 import PromptStats, build_smart_ai_prompt


class AmountMaskingSessionState(TypedDict):
    run_id: str
    tokens_total: int
    mapping: dict[str, str]
    saved_path: Optional[str]


@dataclass(frozen=True)
class MaskMapPersistResult:
    saved_path: Optional[str]
    error_message: Optional[str] = None


@dataclass(frozen=True)
class AmountMaskingResult:
    masked_latest_content: str
    masked_reference_files: list[tuple[str, str]]
    stats: MaskingStats
    mapping: dict[str, str]


@dataclass(frozen=True)
class PromptPreparationResult:
    prompt_masked: str
    prompt_real: str
    prompt_stats_v2: PromptStats
    amount_masking: AmountMaskingSessionState
    masked_latest_content: str
    mask_map_save_error: Optional[str] = None


def compute_ai_process_run_id(
    *,
    latest_name: str,
    latest_fingerprint: str,
    reference_fingerprints: list[str],
) -> str:
    signature_payload = {
        "latest": {"name": str(latest_name), "fingerprint": str(latest_fingerprint)},
        "refs": sorted(reference_fingerprints or []),
    }
    signature = json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]


def mask_amounts_for_ai_process(
    *,
    run_id: str,
    latest_content: str,
    reference_files: list[tuple[str, str]],
) -> AmountMaskingResult:
    masker = AmountMasker(run_id=run_id)
    masked_latest_content = masker.mask_text(latest_content) or ""

    masked_reference_files: list[tuple[str, str]] = []
    for filename, content in reference_files or []:
        masked_reference_files.append((filename, masker.mask_text(content) or ""))

    stats = masker.stats()
    mapping = dict(masker.mapping)
    return AmountMaskingResult(
        masked_latest_content=masked_latest_content,
        masked_reference_files=masked_reference_files,
        stats=stats,
        mapping=mapping,
    )


def persist_mask_map_json(
    *,
    run_id: str,
    mapping: dict[str, str],
    mask_map_dir: Path = MASK_MAP_DIR,
) -> MaskMapPersistResult:
    if not mapping:
        return MaskMapPersistResult(saved_path=None, error_message=None)

    try:
        mask_map_dir.mkdir(parents=True, exist_ok=True)
        path = mask_map_dir / f"{run_id}.json"
        payload = {"run_id": run_id, "mapping": mapping}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return MaskMapPersistResult(saved_path=str(path), error_message=None)
    except Exception as e:
        return MaskMapPersistResult(saved_path=None, error_message=str(e))


def prepare_ai_process_prompts(
    *,
    latest_name: str,
    latest_content: str,
    latest_fingerprint: str,
    reference_files: list[tuple[str, str]],
    reference_fingerprints: list[str],
    examples_per_transaction: int,
    account_definition_content: Optional[str],
    extra_prompt: Optional[str],
    persist_map: bool,
    mask_map_dir: Path = MASK_MAP_DIR,
) -> PromptPreparationResult:
    run_id = compute_ai_process_run_id(
        latest_name=latest_name,
        latest_fingerprint=latest_fingerprint,
        reference_fingerprints=reference_fingerprints,
    )

    masking = mask_amounts_for_ai_process(
        run_id=run_id,
        latest_content=latest_content or "",
        reference_files=reference_files or [],
    )

    persist_result = (
        persist_mask_map_json(
            run_id=masking.stats.run_id,
            mapping=masking.mapping,
            mask_map_dir=mask_map_dir,
        )
        if persist_map and masking.stats.tokens_total > 0
        else MaskMapPersistResult(saved_path=None, error_message=None)
    )

    amount_masking: AmountMaskingSessionState = {
        "run_id": masking.stats.run_id,
        "tokens_total": masking.stats.tokens_total,
        "mapping": dict(masking.mapping),
        "saved_path": persist_result.saved_path,
    }
    mask_map_save_error = persist_result.error_message

    prompt_masked, prompt_stats_v2 = build_smart_ai_prompt(
        latest_file_name=str(latest_name),
        latest_file_content=masking.masked_latest_content,
        reference_files=masking.masked_reference_files,
        examples_per_transaction=examples_per_transaction,
        account_definition_text=account_definition_content,
        extra_prompt=extra_prompt.strip() if extra_prompt else None,
    )

    prompt_real, _ = build_smart_ai_prompt(
        latest_file_name=str(latest_name),
        latest_file_content=latest_content or "",
        reference_files=reference_files or [],
        examples_per_transaction=examples_per_transaction,
        account_definition_text=account_definition_content,
        extra_prompt=extra_prompt.strip() if extra_prompt else None,
    )

    return PromptPreparationResult(
        prompt_masked=prompt_masked,
        prompt_real=prompt_real,
        prompt_stats_v2=prompt_stats_v2,
        amount_masking=amount_masking,
        masked_latest_content=masking.masked_latest_content,
        mask_map_save_error=mask_map_save_error,
    )


def call_ai_completion(
    *, prompt_masked: str, ai_config_manager: AIConfigManager
) -> CallStats:
    """
    Call AI completion using existing AIService. No Streamlit dependency.
    """
    service = AIService(ai_config_manager)
    return service.call_completion(prompt_masked)


def reconcile_masked_beancount(
    *, before_masked: str, after_masked: str
) -> ReconcileReport:
    """
    Reconcile masked Beancount text before/after AI call.
    """
    return reconcile_beancount(before_text=before_masked, after_text=after_masked)


def _coerce_amount_masking_state(info: Mapping[str, Any]) -> AmountMaskingSessionState:
    run_id = info.get("run_id")
    tokens_total = info.get("tokens_total")
    mapping = info.get("mapping")
    saved_path = info.get("saved_path")

    if not isinstance(run_id, str) or not run_id:
        raise ValueError("未找到脱敏 run_id")
    if not isinstance(tokens_total, int):
        raise ValueError("脱敏统计信息格式错误（tokens_total）")
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError("未找到脱敏映射，无法恢复金额")
    if saved_path is not None and not isinstance(saved_path, str):
        raise ValueError("脱敏映射路径格式错误（saved_path）")

    return cast(
        AmountMaskingSessionState,
        {
            "run_id": run_id,
            "tokens_total": tokens_total,
            "mapping": cast(dict[str, str], mapping),
            "saved_path": cast(Optional[str], saved_path),
        },
    )


def restore_amounts_and_reconcile_accounts(
    *,
    amount_masking: Mapping[str, Any],
    masked_ai_response: str,
    original_beancount_text: str,
) -> tuple[str, AccountFillingReport]:
    """
    Restore real amounts from masked AI response, then reconcile account filling.

    Returns:
        (restored_text, filling_report)
    """
    info = _coerce_amount_masking_state(amount_masking)

    restore_masker = AmountMasker(run_id=info["run_id"])
    restore_masker.mapping = info["mapping"]
    restored_text = restore_masker.unmask_text(masked_ai_response or "")

    reconciler = BeancountReconciler()
    filling_report = reconciler.reconcile_account_filling(
        original_text=original_beancount_text or "",
        restored_text=restored_text,
    )
    return restored_text, filling_report


def get_amount_masking_from_session(
    state: Mapping[str, Any],
) -> Optional[AmountMaskingSessionState]:
    """
    Small helper for callers that want a typed-ish access pattern.
    Kept here to avoid UI re-implementing dict shape checks.
    """
    info = (state or {}).get("amount_masking")
    if not isinstance(info, dict):
        return None

    run_id = info.get("run_id")
    tokens_total = info.get("tokens_total")
    mapping = info.get("mapping")
    saved_path = info.get("saved_path")

    if not isinstance(run_id, str):
        return None
    if not isinstance(tokens_total, int):
        return None
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        return None
    if saved_path is not None and not isinstance(saved_path, str):
        return None

    return {
        "run_id": run_id,
        "tokens_total": tokens_total,
        "mapping": mapping,
        "saved_path": saved_path,
    }
