"""
用户规则（用户偏好）

说明：
- `config.yaml` 保存用户输入/用户偏好（AI、邮箱、以及本文件定义的用户规则）
- 本阶段（Plan.md 阶段 4.1）仅实现：消费账户（Expenses:*）关键词映射
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from constants import BEANCOUNT_TODO_TOKEN
from config.config_manager import get_config_manager


class UserRulesError(Exception):
    """User rules error with user-facing message in args[0]."""


_ACCOUNT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9:_-]*$")


def _validate_str_list(
    value: object, *, label: str, allow_empty: bool = False
) -> List[str]:
    if not isinstance(value, list):
        raise UserRulesError(f"{label} 必须是字符串列表")

    normalized: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise UserRulesError(f"{label} 包含非法项：{item!r}")
        normalized.append(item.strip())

    if not normalized and not allow_empty:
        raise UserRulesError(f"{label} 不能为空")

    return normalized


def _validate_expenses_account(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserRulesError(f"{label} 必须是非空字符串")

    account = value.strip()
    if not account.startswith("Expenses:"):
        raise UserRulesError(f"{label} 必须以 'Expenses:' 开头：{account!r}")

    if not _ACCOUNT_RE.match(account):
        raise UserRulesError(f"{label} 包含非法字符：{account!r}")

    if BEANCOUNT_TODO_TOKEN.upper() in account.upper():
        raise UserRulesError(
            f"{label} 不允许包含 {BEANCOUNT_TODO_TOKEN}（{BEANCOUNT_TODO_TOKEN} 用于占位与 AI 流程识别）：{account!r}"
        )

    return account


def _normalize_rules(rules: object) -> List[Dict[str, Any]]:
    if rules is None:
        return []

    if not isinstance(rules, list):
        raise UserRulesError(
            "user_rules.expenses_account_rules.rules 类型错误（应为 list）"
        )

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(rules):
        if not isinstance(item, dict):
            raise UserRulesError(
                f"user_rules.expenses_account_rules.rules[{idx}] 类型错误（应为 dict）"
            )

        account = _validate_expenses_account(
            item.get("account"),
            label=f"user_rules.expenses_account_rules.rules[{idx}].account",
        )
        keywords = _validate_str_list(
            item.get("keywords"),
            label=f"user_rules.expenses_account_rules.rules[{idx}].keywords",
        )
        normalized.append({"account": account, "keywords": keywords})

    return normalized


def get_expenses_account_rules() -> List[Dict[str, Any]]:
    """
    读取并校验用户配置的“消费账户关键词映射”规则。

    Returns:
        规则列表（已做最小归一化），形如：
        [{"account": "Expenses:Food:Cafe", "keywords": ["星巴克", "瑞幸"]}, ...]
    """
    raw = get_config_manager().get_section("user_rules")
    if raw is None:
        return []

    if not isinstance(raw, dict):
        raise UserRulesError("user_rules 类型错误（应为 dict）")

    version = raw.get("version")
    if version not in (None, 1):
        raise UserRulesError(f"user_rules.version 不支持：{version!r}（仅支持 1）")

    group = raw.get("expenses_account_rules")
    if group is None:
        return []

    if not isinstance(group, dict):
        raise UserRulesError("user_rules.expenses_account_rules 类型错误（应为 dict）")

    return _normalize_rules(group.get("rules"))


def save_expenses_account_rules(rules: List[Dict[str, Any]]) -> None:
    """
    保存消费账户关键词映射规则到 config.yaml（user_rules 节）。

    Args:
        rules: 规则列表（未必已归一化；本函数会做校验与归一化）
    """
    normalized_rules = _normalize_rules(rules)

    cm = get_config_manager()
    raw = cm.get_section("user_rules")
    if not isinstance(raw, dict):
        raw = {}

    raw["version"] = 1
    raw["expenses_account_rules"] = {"rules": normalized_rules}
    cm.set_section("user_rules", raw)


def match_expenses_account(
    description: str, rules: List[Dict[str, Any]]
) -> Optional[str]:
    """
    根据交易描述匹配消费账户（第一个命中生效）。

    Args:
        description: 交易描述
        rules: 规则列表（建议传入 get_expenses_account_rules() 的返回值）

    Returns:
        命中的 Expenses 账户；如未命中返回 None
    """
    desc = str(description or "")
    for rule in rules or []:
        account = rule.get("account")
        keywords = rule.get("keywords") or []
        if not isinstance(account, str) or not isinstance(keywords, list):
            continue
        if any(str(keyword) in desc for keyword in keywords):
            return account
    return None
