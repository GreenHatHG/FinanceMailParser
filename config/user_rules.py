"""
用户规则（用户偏好）

说明：
- `config.yaml` 保存用户输入/用户偏好（AI、邮箱、以及本文件定义的用户规则）
- 阶段 4.1：消费账户（Expenses:*）关键词映射
- 阶段 4.2：交易过滤规则（对所有来源统一生效）
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, TypedDict
import re

from constants import BEANCOUNT_TODO_TOKEN
from config.config_manager import get_config_manager


class UserRulesError(Exception):
    """User rules error with user-facing message in args[0]."""


_ACCOUNT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9:_-]*$")


class AmountRange(TypedDict):
    gte: float
    lte: float


class TransactionFilters(TypedDict):
    skip_keywords: List[str]
    amount_ranges: List[AmountRange]


DEFAULT_TRANSACTION_SKIP_KEYWORDS: List[str] = [
    # Credit card parsers (previous hardcode in statement_parsers/__init__.py)
    "还款",
    "银联入账",
    "转入",
    "入账",
    # WeChat parser (previous hardcode in statement_parsers/wechat.py)
    "零钱提现",
    "微信红包",
    # Alipay parser (previous regex in statement_parsers/alipay.py)
    "收益发放",
    "余额",
    # CMB parser (previous hardcode in statement_parsers/cmb.py)
    "消费分期-京东支付-网银在线",
]

# Amount filter ranges are closed intervals: [gte, lte]
DEFAULT_TRANSACTION_AMOUNT_RANGES: List[AmountRange] = [
    {"gte": 0.0, "lte": 1.0},
]


@lru_cache(maxsize=1)
def _get_user_rules_section() -> Dict[str, Any]:
    raw = get_config_manager().get_section("user_rules")
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise UserRulesError("user_rules 类型错误（应为 dict）")

    version = raw.get("version")
    if version not in (None, 1):
        raise UserRulesError(f"user_rules.version 不支持：{version!r}（仅支持 1）")

    return raw


def _clear_user_rules_cache() -> None:
    _get_user_rules_section.cache_clear()


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


def _validate_float(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise UserRulesError(f"{label} 必须是数字（不能是 bool）")

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError as e:
            raise UserRulesError(f"{label} 不是合法数字：{value!r}") from e

    raise UserRulesError(f"{label} 必须是数字")


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


def _normalize_expenses_account_rules(rules: object) -> List[Dict[str, Any]]:
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
    raw = _get_user_rules_section()
    group = raw.get("expenses_account_rules")
    if group is None:
        return []

    if not isinstance(group, dict):
        raise UserRulesError("user_rules.expenses_account_rules 类型错误（应为 dict）")

    return _normalize_expenses_account_rules(group.get("rules"))


def save_expenses_account_rules(rules: List[Dict[str, Any]]) -> None:
    """
    保存消费账户关键词映射规则到 config.yaml（user_rules 节）。

    Args:
        rules: 规则列表（未必已归一化；本函数会做校验与归一化）
    """
    normalized_rules = _normalize_expenses_account_rules(rules)

    cm = get_config_manager()
    raw = cm.get_section("user_rules")
    if not isinstance(raw, dict):
        raw = {}

    raw["version"] = 1
    raw["expenses_account_rules"] = {"rules": normalized_rules}
    cm.set_section("user_rules", raw)
    _clear_user_rules_cache()


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


def _normalize_amount_ranges(
    ranges: object, *, label: str, allow_empty: bool = False
) -> List[AmountRange]:
    if ranges is None:
        return []

    if not isinstance(ranges, list):
        raise UserRulesError(f"{label} 类型错误（应为 list）")

    normalized: List[AmountRange] = []
    for idx, item in enumerate(ranges):
        if not isinstance(item, dict):
            raise UserRulesError(f"{label}[{idx}] 类型错误（应为 dict）")

        gte = _validate_float(item.get("gte"), label=f"{label}[{idx}].gte")
        lte = _validate_float(item.get("lte"), label=f"{label}[{idx}].lte")

        if gte > lte:
            raise UserRulesError(f"{label}[{idx}] 非法区间：gte({gte}) > lte({lte})")

        normalized.append({"gte": gte, "lte": lte})

    if not normalized and not allow_empty:
        raise UserRulesError(f"{label} 不能为空")

    return normalized


def get_transaction_filters() -> TransactionFilters:
    """
    获取交易过滤规则（对所有来源统一生效）。

    Returns:
        TransactionFilters:
        - skip_keywords: list[str]
        - amount_ranges: list[{"gte": float, "lte": float}]
    """
    raw = _get_user_rules_section()
    group = raw.get("transaction_filters")
    if group is None:
        return {
            "skip_keywords": list(DEFAULT_TRANSACTION_SKIP_KEYWORDS),
            "amount_ranges": list(DEFAULT_TRANSACTION_AMOUNT_RANGES),
        }

    if not isinstance(group, dict):
        raise UserRulesError("user_rules.transaction_filters 类型错误（应为 dict）")

    skip_keywords_raw = group.get("skip_keywords")
    if skip_keywords_raw is None:
        skip_keywords: List[str] = list(DEFAULT_TRANSACTION_SKIP_KEYWORDS)
    else:
        skip_keywords = _validate_str_list(
            skip_keywords_raw,
            label="user_rules.transaction_filters.skip_keywords",
            allow_empty=True,
        )

    amount_filters = group.get("amount_filters")
    ranges_raw = None
    if isinstance(amount_filters, dict):
        ranges_raw = amount_filters.get("ranges")

    if ranges_raw is None:
        amount_ranges: List[AmountRange] = list(DEFAULT_TRANSACTION_AMOUNT_RANGES)
    else:
        amount_ranges = _normalize_amount_ranges(
            ranges_raw,
            label="user_rules.transaction_filters.amount_filters.ranges",
            allow_empty=True,
        )

    return {"skip_keywords": skip_keywords, "amount_ranges": amount_ranges}


def save_transaction_filters(
    *, skip_keywords: List[str], amount_ranges: List[Dict[str, Any]]
) -> None:
    """
    保存交易过滤规则到 config.yaml（user_rules 节）。

    Args:
        skip_keywords: 描述关键词过滤列表（包含子串匹配）
        amount_ranges: 金额过滤区间列表（闭区间 [gte, lte]）
    """
    normalized_skip_keywords = _validate_str_list(
        skip_keywords,
        label="user_rules.transaction_filters.skip_keywords",
        allow_empty=True,
    )
    normalized_amount_ranges = _normalize_amount_ranges(
        amount_ranges,
        label="user_rules.transaction_filters.amount_filters.ranges",
        allow_empty=True,
    )

    cm = get_config_manager()
    raw = cm.get_section("user_rules")
    if not isinstance(raw, dict):
        raw = {}

    raw["version"] = 1
    raw["transaction_filters"] = {
        "skip_keywords": normalized_skip_keywords,
        "amount_filters": {"ranges": normalized_amount_ranges},
    }
    cm.set_section("user_rules", raw)
    _clear_user_rules_cache()


def match_skip_keyword(description: str, skip_keywords: Sequence[str]) -> Optional[str]:
    desc = str(description or "")
    for keyword in skip_keywords or []:
        if str(keyword) and str(keyword) in desc:
            return str(keyword)
    return None


def amount_in_ranges(amount: float, ranges: Sequence[AmountRange]) -> bool:
    try:
        value = float(amount)
    except Exception:
        return False

    for r in ranges:
        try:
            gte = float(r["gte"])
            lte = float(r["lte"])
        except Exception:
            continue
        if gte <= value <= lte:
            return True
    return False
