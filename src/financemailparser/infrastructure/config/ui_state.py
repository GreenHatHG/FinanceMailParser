"""
UI 状态持久化（用于改善交互体验）

说明：
- 持久化位置：config.yaml 的 ui_state 节
- 该模块只保存“UI 便利信息”，不参与核心业务规则计算
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, TypedDict

from financemailparser.infrastructure.config.config_manager import get_config_manager


UI_STATE_SECTION = "ui_state"
AI_PROCESS_BEANCOUNT_KEY = "ai_process_beancount"
AI_PROCESS_BEANCOUNT_VERSION = 1

_KEY_VERSION = "version"
_KEY_HISTORY_PATHS = "history_paths"
_KEY_ACCOUNT_DEFINITION_PATH = "account_definition_path"
_KEY_ENABLE_LOCAL_PATHS = "enable_local_paths"
_KEY_EXTRA_PROMPT = "extra_prompt"


class UiStateError(Exception):
    """UI state error with user-facing message in args[0]."""


class AiProcessBeancountUiState(TypedDict):
    version: int
    history_paths: List[str]
    account_definition_path: Optional[str]
    enable_local_paths: bool
    extra_prompt: Optional[str]


def _as_dict(value: object, *, label: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UiStateError(f"{label} 类型错误（应为 dict）")
    return dict(value)


def _normalize_str(value: object, *, label: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UiStateError(f"{label} 类型错误（应为 str）")
    out = value.strip()
    return out or None


def _normalize_str_list(value: object, *, label: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise UiStateError(f"{label} 类型错误（应为 list[str]）")
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise UiStateError(f"{label} 包含非法项：{item!r}")
        normalized = item.strip()
        if normalized:
            out.append(normalized)
    return out


def _normalize_bool(value: object, *, label: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise UiStateError(f"{label} 类型错误（应为 bool）")
    return bool(value)


def get_ai_process_beancount_ui_state() -> AiProcessBeancountUiState:
    """
    Load UI state for AI Beancount processing.

    Returns empty defaults when missing.
    """
    raw_root = get_config_manager().get_section(UI_STATE_SECTION)
    root = _as_dict(raw_root, label=UI_STATE_SECTION)

    raw = root.get(AI_PROCESS_BEANCOUNT_KEY)
    if raw is None:
        return {
            "version": AI_PROCESS_BEANCOUNT_VERSION,
            "history_paths": [],
            "account_definition_path": None,
            "enable_local_paths": False,
            "extra_prompt": None,
        }

    section = _as_dict(raw, label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}")
    version = section.get(_KEY_VERSION)
    if version not in (None, AI_PROCESS_BEANCOUNT_VERSION):
        raise UiStateError(
            f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.version 不支持：{version!r}（仅支持 {AI_PROCESS_BEANCOUNT_VERSION}）"
        )

    history_paths = _normalize_str_list(
        section.get(_KEY_HISTORY_PATHS),
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_HISTORY_PATHS}",
    )
    account_definition_path = _normalize_str(
        section.get(_KEY_ACCOUNT_DEFINITION_PATH),
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_ACCOUNT_DEFINITION_PATH}",
    )
    enable_local_paths = _normalize_bool(
        section.get(_KEY_ENABLE_LOCAL_PATHS),
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_ENABLE_LOCAL_PATHS}",
    )
    extra_prompt = _normalize_str(
        section.get(_KEY_EXTRA_PROMPT),
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_EXTRA_PROMPT}",
    )

    return {
        "version": AI_PROCESS_BEANCOUNT_VERSION,
        "history_paths": history_paths,
        "account_definition_path": account_definition_path,
        "enable_local_paths": enable_local_paths,
        "extra_prompt": extra_prompt,
    }


def _save_ai_process_beancount_ui_state(*, state: AiProcessBeancountUiState) -> None:
    cm = get_config_manager()
    raw_root = cm.get_section(UI_STATE_SECTION)
    root = raw_root if isinstance(raw_root, dict) else {}

    payload: Dict[str, Any] = {_KEY_VERSION: AI_PROCESS_BEANCOUNT_VERSION}
    if state.get("history_paths"):
        payload[_KEY_HISTORY_PATHS] = list(state["history_paths"])
    if state.get("account_definition_path"):
        payload[_KEY_ACCOUNT_DEFINITION_PATH] = str(state["account_definition_path"])
    payload[_KEY_ENABLE_LOCAL_PATHS] = bool(state.get("enable_local_paths", False))
    if state.get("extra_prompt"):
        payload[_KEY_EXTRA_PROMPT] = str(state["extra_prompt"])

    root[AI_PROCESS_BEANCOUNT_KEY] = payload
    cm.set_section(UI_STATE_SECTION, dict(root))


def save_ai_process_beancount_history_paths(paths: Sequence[str]) -> None:
    current = get_ai_process_beancount_ui_state()
    current["history_paths"] = _normalize_str_list(
        list(paths),
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_HISTORY_PATHS}",
    )
    _save_ai_process_beancount_ui_state(state=current)


def save_ai_process_beancount_account_definition_path(path: str | None) -> None:
    current = get_ai_process_beancount_ui_state()
    current["account_definition_path"] = _normalize_str(
        path,
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_ACCOUNT_DEFINITION_PATH}",
    )
    _save_ai_process_beancount_ui_state(state=current)


def save_ai_process_beancount_last_inputs(
    *, enable_local_paths: bool, extra_prompt: str | None
) -> None:
    current = get_ai_process_beancount_ui_state()
    current["enable_local_paths"] = bool(enable_local_paths)
    current["extra_prompt"] = _normalize_str(
        extra_prompt,
        label=f"{UI_STATE_SECTION}.{AI_PROCESS_BEANCOUNT_KEY}.{_KEY_EXTRA_PROMPT}",
    )
    _save_ai_process_beancount_ui_state(state=current)


def clear_ai_process_beancount_history_paths() -> None:
    current = get_ai_process_beancount_ui_state()
    current["history_paths"] = []
    _save_ai_process_beancount_ui_state(state=current)


def clear_ai_process_beancount_account_definition_path() -> None:
    current = get_ai_process_beancount_ui_state()
    current["account_definition_path"] = None
    _save_ai_process_beancount_ui_state(state=current)
