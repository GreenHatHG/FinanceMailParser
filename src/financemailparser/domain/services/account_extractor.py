"""
账户字典提取工具（ui_plan.md 2.7.5）

功能：
- 从 Beancount 账户定义文件中提取账户（推荐）
- 从历史 Beancount 交易文件中提取账户（备选）
- 按一级分类分组（Expenses:Food -> Food）
- 过滤掉 TODO 和 Assets 账户
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Set

from financemailparser.domain.beancount_constants import BEANCOUNT_TODO_TOKEN

# 账户名正则：匹配 Expenses:Food:Restaurant 等格式
_ACCOUNT_RE = re.compile(r"\b(Expenses:[A-Za-z][A-Za-z0-9:_-]*)\b")

# open 指令正则：匹配 "2024-01-01 open Expenses:Food:Restaurant"
_OPEN_DIRECTIVE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+open\s+(Expenses:[A-Za-z][A-Za-z0-9:_-]*)", re.MULTILINE
)


def extract_accounts_from_open_directives(account_definition_text: str) -> Set[str]:
    """
    从 Beancount 账户定义文件中提取账户（通过 open 指令）。

    Args:
        account_definition_text: 包含 open 指令的 Beancount 文件内容

    Returns:
        账户集合

    Example:
        >>> text = '''
        ... 2024-01-01 open Expenses:Food:Restaurant
        ... 2024-01-01 open Expenses:Transport:Taxi
        ... '''
        >>> accounts = extract_accounts_from_open_directives(text)
        >>> sorted(accounts)
        ['Expenses:Food:Restaurant', 'Expenses:Transport:Taxi']
    """
    if not account_definition_text:
        return set()

    matches = _OPEN_DIRECTIVE_RE.findall(account_definition_text)
    return set(matches)


def extract_accounts_from_transactions(beancount_texts: List[str]) -> Set[str]:
    """
    从 Beancount 交易文件中提取账户（备选方案）。

    Args:
        beancount_texts: Beancount 交易文件内容列表

    Returns:
        账户集合
    """
    all_accounts: Set[str] = set()

    for text in beancount_texts:
        if not text:
            continue

        matches = _ACCOUNT_RE.findall(text)
        for account in matches:
            if BEANCOUNT_TODO_TOKEN not in account.upper():
                all_accounts.add(account)

    return all_accounts


def extract_account_dict(
    beancount_texts: List[str],
    account_definition_text: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    从 Beancount 文件中提取账户字典。

    优先级：
    1. 如果提供了 account_definition_text，从 open 指令中提取（推荐）
    2. 否则从交易文件中提取（备选）

    Args:
        beancount_texts: Beancount 交易文件内容列表
        account_definition_text: 可选的账户定义文件内容（包含 open 指令）

    Returns:
        账户字典，格式：
        {
            "Food": ["Expenses:Food:Restaurant", "Expenses:Food:Grocery"],
            "Transport": ["Expenses:Transport:Taxi", "Expenses:Transport:Subway"],
            ...
        }
    """
    if account_definition_text:
        all_accounts = extract_accounts_from_open_directives(account_definition_text)
    else:
        all_accounts = extract_accounts_from_transactions(beancount_texts)

    grouped: Dict[str, Set[str]] = defaultdict(set)
    for account in all_accounts:
        parts = account.split(":")
        if len(parts) >= 2:
            category = parts[1]  # Expenses:Food -> Food
            grouped[category].add(account)

    result: Dict[str, List[str]] = {}
    for category, accounts in grouped.items():
        result[category] = sorted(accounts)
    return result


def format_account_dict_for_prompt(account_dict: Dict[str, List[str]]) -> str:
    """
    将账户字典格式化为 Prompt 文本。

    Args:
        account_dict: 账户字典

    Returns:
        格式化后的文本，例如：
        ## Food
        - Expenses:Food:Restaurant
        - Expenses:Food:Grocery

        ## Transport
        - Expenses:Transport:Taxi
    """
    if not account_dict:
        return "（暂无可用账户）"

    lines: List[str] = []
    for category in sorted(account_dict.keys()):
        accounts = account_dict[category]
        lines.append(f"## {category}")
        for account in accounts:
            lines.append(f"- {account}")
        lines.append("")

    return "\n".join(lines).rstrip()
