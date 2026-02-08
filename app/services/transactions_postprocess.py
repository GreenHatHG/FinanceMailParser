from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from app.services.user_rules_service import (
    get_expenses_account_rules_ui_snapshot,
    get_transaction_filters_ui_snapshot,
)
from config.user_rules import (
    AmountRange,
    amount_in_ranges,
    match_expenses_account,
    match_skip_keyword,
)
from models.txn import DigitalPaymentTransaction, Transaction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionFilterStats:
    skipped_by_keyword: int
    skipped_by_amount: int
    before_total: int
    after_total: int


def load_transaction_filters_safe() -> Tuple[List[str], List[AmountRange]]:
    """
    Load user-configurable transaction filters, with safe fallbacks.

    Returns:
        (skip_keywords, amount_ranges)
    """
    snap = get_transaction_filters_ui_snapshot()
    if snap.state == "format_error":
        logger.warning(
            "用户过滤规则格式错误，将使用默认过滤规则：%s", snap.error_message
        )
    elif snap.state == "load_failed":
        logger.warning(
            "用户过滤规则加载失败，将使用默认过滤规则：%s", snap.error_message
        )

    filters = dict(snap.filters or {})
    skip_keywords = list(filters.get("skip_keywords") or [])
    amount_ranges = list(filters.get("amount_ranges") or [])
    return skip_keywords, amount_ranges


def make_should_skip_transaction(skip_keywords: List[str]) -> Callable[[str], bool]:
    def should_skip_transaction(description: str) -> bool:
        return match_skip_keyword(str(description or ""), skip_keywords) is not None

    return should_skip_transaction


def merge_transaction_descriptions(
    credit_card_transactions: List[Transaction],
    digital_payment_transactions: List[Transaction],
) -> List[Transaction]:
    """Merge credit-card and digital-payment descriptions and dedupe matched digital txns."""
    logger.info("开始合并交易描述...")

    dp_txns_index: Dict[Tuple[Any, Any, Any], List[Transaction]] = {}
    for dp_txn in digital_payment_transactions:
        if isinstance(dp_txn, DigitalPaymentTransaction) and dp_txn.card_source:
            key = (dp_txn.date, dp_txn.amount, dp_txn.card_source)
            dp_txns_index.setdefault(key, []).append(dp_txn)

    matched_count = 0
    matched_dp_txns = set()

    for cc_txn in credit_card_transactions:
        key = (cc_txn.date, cc_txn.amount, cc_txn.source)

        if key in dp_txns_index:
            for dp_txn in dp_txns_index[key]:
                if dp_txn in matched_dp_txns:
                    continue

                logger.debug("\n找到匹配的交易:")
                try:
                    logger.debug(
                        "  信用卡: %s | %s | ¥%.2f | %s",
                        cc_txn.date,
                        cc_txn.description,
                        cc_txn.amount,
                        getattr(cc_txn.source, "value", cc_txn.source),
                    )
                    card_source_str = getattr(dp_txn, "card_source", "N/A")
                    logger.debug(
                        "  %s: %s | %s | ¥%.2f | 支付方式: %s",
                        dp_txn.source,
                        dp_txn.date,
                        dp_txn.description,
                        dp_txn.amount,
                        card_source_str,
                    )
                except Exception:
                    pass

                cc_desc_len = len(str(cc_txn.description or "").strip())
                dp_desc_len = len(str(dp_txn.description or "").strip())

                final_desc = (
                    cc_txn.description
                    if cc_desc_len >= dp_desc_len
                    else dp_txn.description
                )
                cc_txn.description = final_desc

                matched_dp_txns.add(dp_txn)
                matched_count += 1
                break

    unmatched_dp_txns = [
        txn for txn in digital_payment_transactions if txn not in matched_dp_txns
    ]
    all_transactions = credit_card_transactions + unmatched_dp_txns

    logger.info("\n合并完成:")
    logger.info("  - 成功匹配并合并: %s 条交易", matched_count)
    logger.info("  - 已移除的重复数字支付交易: %s 条", len(matched_dp_txns))
    logger.info("  - 未匹配的数字支付交易: %s 条", len(unmatched_dp_txns))
    logger.info("  - 最终交易总数: %s 条", len(all_transactions))

    return all_transactions


def filter_transactions_by_rules(
    transactions: List[Transaction],
    *,
    skip_keywords: List[str],
    amount_ranges: List[AmountRange],
) -> Tuple[List[Transaction], TransactionFilterStats]:
    before_filter_total = len(transactions)
    skipped_by_keyword = 0
    skipped_by_amount = 0
    filtered_transactions: List[Transaction] = []

    for txn in transactions:
        desc = str(getattr(txn, "description", "") or "")
        amt = float(getattr(txn, "amount", 0.0) or 0.0)

        if match_skip_keyword(desc, skip_keywords) is not None:
            skipped_by_keyword += 1
            continue

        if amount_in_ranges(amt, amount_ranges):
            skipped_by_amount += 1
            continue

        filtered_transactions.append(txn)

    stats = TransactionFilterStats(
        skipped_by_keyword=skipped_by_keyword,
        skipped_by_amount=skipped_by_amount,
        before_total=before_filter_total,
        after_total=len(filtered_transactions),
    )
    return filtered_transactions, stats


def load_expenses_account_rules_safe() -> List[Dict[str, Any]]:
    snap = get_expenses_account_rules_ui_snapshot()
    if snap.state == "format_error":
        logger.warning(
            "用户规则加载失败，将忽略消费账户关键词映射：%s", snap.error_message
        )
    elif snap.state == "load_failed":
        logger.warning(
            "用户规则加载失败，将忽略消费账户关键词映射：%s", snap.error_message
        )
    return list(snap.rules or [])


def apply_expenses_account_rules(
    transactions: List[Transaction],
    *,
    expenses_rules: List[Dict[str, Any]],
) -> int:
    matched_accounts = 0
    if not expenses_rules:
        return 0

    for txn in transactions:
        try:
            amount = float(getattr(txn, "amount", 0.0) or 0.0)
            if amount < 0:
                continue

            desc = str(getattr(txn, "description", "") or "")
            matched = match_expenses_account(desc, expenses_rules)
            if matched:
                setattr(txn, "beancount_expenses_account", matched)
                matched_accounts += 1
        except Exception:
            continue

    return matched_accounts
