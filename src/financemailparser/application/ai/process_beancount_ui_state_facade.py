"""
AI Beancount UI state facade.

Goal:
- Keep Streamlit pages free from direct YAML structure handling.
- Provide UI-friendly snapshots and action results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from financemailparser.application.common.facade_common import UiActionResult
import financemailparser.infrastructure.config.ui_state as ui_state_cfg


AiProcessBeancountUiStateUiState = Literal["ok", "format_error", "load_failed"]


@dataclass(frozen=True)
class AiProcessBeancountUiStateUiSnapshot:
    state: AiProcessBeancountUiStateUiState
    history_paths: List[str]
    account_definition_path: Optional[str]
    enable_local_paths: bool
    extra_prompt: Optional[str]
    error_message: str = ""


def _parse_multiline_paths(text: str) -> List[str]:
    out: List[str] = []
    for line in (text or "").splitlines():
        normalized = line.strip()
        if normalized:
            out.append(normalized)
    return out


def get_ai_process_beancount_ui_state_ui_snapshot() -> (
    AiProcessBeancountUiStateUiSnapshot
):
    try:
        state = ui_state_cfg.get_ai_process_beancount_ui_state()
        return AiProcessBeancountUiStateUiSnapshot(
            state="ok",
            history_paths=list(state.get("history_paths") or []),
            account_definition_path=state.get("account_definition_path"),
            enable_local_paths=bool(state.get("enable_local_paths", False)),
            extra_prompt=state.get("extra_prompt"),
        )
    except ui_state_cfg.UiStateError as e:
        return AiProcessBeancountUiStateUiSnapshot(
            state="format_error",
            history_paths=[],
            account_definition_path=None,
            enable_local_paths=False,
            extra_prompt=None,
            error_message=str(e),
        )
    except Exception as e:
        return AiProcessBeancountUiStateUiSnapshot(
            state="load_failed",
            history_paths=[],
            account_definition_path=None,
            enable_local_paths=False,
            extra_prompt=None,
            error_message=str(e),
        )


def save_ai_process_beancount_history_paths_from_ui(
    *, paths_text: str
) -> UiActionResult:
    try:
        ui_state_cfg.save_ai_process_beancount_history_paths(
            _parse_multiline_paths(paths_text)
        )
        return UiActionResult(ok=True, message="✅ 已保存到 config.yaml")
    except ui_state_cfg.UiStateError as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def save_ai_process_beancount_account_definition_path_from_ui(
    *, path_text: str
) -> UiActionResult:
    try:
        ui_state_cfg.save_ai_process_beancount_account_definition_path(path_text)
        return UiActionResult(ok=True, message="✅ 已保存到 config.yaml")
    except ui_state_cfg.UiStateError as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def save_ai_process_beancount_last_inputs_from_ui(
    *, enable_local_paths: bool, extra_prompt: str
) -> UiActionResult:
    try:
        ui_state_cfg.save_ai_process_beancount_last_inputs(
            enable_local_paths=bool(enable_local_paths),
            extra_prompt=extra_prompt,
        )
        return UiActionResult(ok=True, message="✅ 已保存到 config.yaml")
    except ui_state_cfg.UiStateError as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def clear_ai_process_beancount_history_paths_from_ui() -> UiActionResult:
    try:
        ui_state_cfg.clear_ai_process_beancount_history_paths()
        return UiActionResult(ok=True, message="✅ 已清空并保存到 config.yaml")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 清空失败：{str(e)}")


def clear_ai_process_beancount_account_definition_path_from_ui() -> UiActionResult:
    try:
        ui_state_cfg.clear_ai_process_beancount_account_definition_path()
        return UiActionResult(ok=True, message="✅ 已清空并保存到 config.yaml")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 清空失败：{str(e)}")
