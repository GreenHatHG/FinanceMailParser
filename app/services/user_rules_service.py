"""
User rules service (UI-facing app/service layer).

This module exists to keep `ui/pages/*.py` free from direct imports of `config.*`,
and to provide UI-friendly helpers (safe snapshots, save results).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, cast

import config.user_rules as user_rules
from app.services.ui_facade_common import UiActionResult

TransactionFiltersUiState = Literal[
    "ok", "using_defaults", "format_error", "load_failed"
]
ExpensesAccountRulesUiState = Literal[
    "ok", "using_defaults", "format_error", "load_failed"
]


@dataclass(frozen=True)
class TransactionFiltersUiSnapshot:
    state: TransactionFiltersUiState
    filters: Mapping[str, Any]
    error_message: str = ""

    @property
    def used_defaults(self) -> bool:
        return self.state != "ok"


@dataclass(frozen=True)
class ExpensesAccountRulesUiSnapshot:
    state: ExpensesAccountRulesUiState
    rules: List[Dict[str, Any]]
    error_message: str = ""

    @property
    def used_defaults(self) -> bool:
        return self.state != "ok"


def get_transaction_filters_ui_snapshot(
    *, use_defaults: bool = False
) -> TransactionFiltersUiSnapshot:
    """
    Load transaction filters for UI rendering, with safe fallbacks.

    When `use_defaults=True`, it does not read config.yaml.
    """
    try:
        defaults_raw = user_rules.get_transaction_filter_defaults()
        defaults: dict[str, Any] = {
            "skip_keywords": list(defaults_raw["skip_keywords"]),
            "amount_ranges": [
                {"gte": float(r["gte"]), "lte": float(r["lte"])}
                for r in defaults_raw["amount_ranges"]
            ],
        }
    except user_rules.UserRulesError as e:
        return TransactionFiltersUiSnapshot(
            state="format_error",
            filters={"skip_keywords": [], "amount_ranges": []},
            error_message=str(e),
        )
    except Exception as e:
        return TransactionFiltersUiSnapshot(
            state="load_failed",
            filters={"skip_keywords": [], "amount_ranges": []},
            error_message=str(e),
        )

    if use_defaults:
        return TransactionFiltersUiSnapshot(state="using_defaults", filters=defaults)

    try:
        filters = user_rules.get_transaction_filters()
        return TransactionFiltersUiSnapshot(state="ok", filters=filters)
    except user_rules.UserRulesError as e:
        return TransactionFiltersUiSnapshot(
            state="format_error", filters=defaults, error_message=str(e)
        )
    except Exception as e:
        return TransactionFiltersUiSnapshot(
            state="load_failed", filters=defaults, error_message=str(e)
        )


def get_expenses_account_rules_ui_snapshot(
    *, use_defaults: bool = False
) -> ExpensesAccountRulesUiSnapshot:
    """
    Load expenses-account keyword mapping rules for UI rendering, with safe fallbacks.

    When `use_defaults=True`, it does not read config.yaml.
    """
    if use_defaults:
        return ExpensesAccountRulesUiSnapshot(state="using_defaults", rules=[])

    try:
        rules = user_rules.get_expenses_account_rules()
        return ExpensesAccountRulesUiSnapshot(state="ok", rules=list(rules or []))
    except user_rules.UserRulesError as e:
        return ExpensesAccountRulesUiSnapshot(
            state="format_error", rules=[], error_message=str(e)
        )
    except Exception as e:
        return ExpensesAccountRulesUiSnapshot(
            state="load_failed", rules=[], error_message=str(e)
        )


def save_transaction_filters_from_ui(
    *, skip_keywords: List[str], amount_ranges: List[Dict[str, Any]]
) -> UiActionResult:
    """Save transaction filters and return a UI-friendly result instead of raising."""
    try:
        user_rules.save_transaction_filters(
            skip_keywords=skip_keywords, amount_ranges=amount_ranges
        )
        return UiActionResult(ok=True, message="✅ 已保存到 config.yaml")
    except user_rules.UserRulesError as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def save_expenses_account_rules_from_ui(rules: List[Dict[str, Any]]) -> UiActionResult:
    """Save expenses-account rules and return a UI-friendly result instead of raising."""
    try:
        user_rules.save_expenses_account_rules(rules)
        return UiActionResult(ok=True, message="✅ 已保存到 config.yaml")
    except user_rules.UserRulesError as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")
    except Exception as e:
        return UiActionResult(ok=False, message=f"❌ 保存失败：{str(e)}")


def eval_transaction_filter(
    *,
    description: str,
    amount: float,
    skip_keywords: Sequence[str],
    amount_ranges: Sequence[Dict[str, Any]],
) -> Tuple[Optional[str], bool]:
    """
    UI helper to preview whether a transaction will be filtered.

    Returns:
        (matched_keyword, matched_amount_range)
    """
    matched_keyword = user_rules.match_skip_keyword(description, skip_keywords)
    matched_amount = bool(
        user_rules.amount_in_ranges(
            amount, cast(Sequence[user_rules.AmountRange], amount_ranges)
        )
    )
    return matched_keyword, matched_amount


def eval_expenses_account(
    *, description: str, rules: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """UI helper to preview which Expenses account rule will match (first-hit wins)."""
    return user_rules.match_expenses_account(description, list(rules or []))
