from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple

from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.date_filter import parse_date_safe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefundPair:
    purchase: Transaction
    refund: Transaction


def find_matching_refund_pairs(transactions: List[Transaction]) -> List[RefundPair]:
    """
    Find matched refund pairs according to filter_matching_refunds rules.

    Returns:
        List[RefundPair] where both purchase and refund should be removed.
    """
    # 按来源分组
    transaction_groups: Dict[object, List[Transaction]] = {}
    for transaction in transactions:
        key = transaction.source
        if key not in transaction_groups:
            transaction_groups[key] = []
        transaction_groups[key].append(transaction)

    pairs: List[RefundPair] = []

    # 处理每个分组
    for txns in transaction_groups.values():
        positive_txns: List[Tuple[float, Transaction]] = []
        negative_txns: List[Tuple[float, Transaction]] = []

        for txn in txns:
            if txn.amount > 0:
                positive_txns.append((txn.amount, txn))
            else:
                negative_txns.append((abs(txn.amount), txn))

        matched_positive = set()
        matched_negative = set()

        for i, (pos_amount, pos_txn) in enumerate(positive_txns):
            pos_dt = parse_date_safe(getattr(pos_txn, "date", ""))
            if not pos_dt:
                continue

            for j, (neg_amount, neg_txn) in enumerate(negative_txns):
                if j in matched_negative or i in matched_positive:
                    continue

                neg_dt = parse_date_safe(getattr(neg_txn, "date", ""))
                if not neg_dt:
                    continue
                if neg_dt.date() < pos_dt.date():
                    continue

                if pos_amount == neg_amount:
                    matched_positive.add(i)
                    matched_negative.add(j)
                    pairs.append(RefundPair(purchase=pos_txn, refund=neg_txn))
                    break

    return pairs


def filter_matching_refunds(transactions: List[Transaction]) -> List[Transaction]:
    """
    过滤掉具有匹配退款的交易。
    对于同一来源（source）的交易，将正数金额与负数金额一一配对，
    未配对的交易将被保留。

    匹配条件：
    - 同一来源（source）：如都在微信，或都在同一张信用卡
    - 金额相等（正负相反）
    - 退款日期必须等于或晚于消费日期；若日期无法解析则不配对（偏保守，避免误删）

    Args:
        transactions: Transaction对象列表

    Returns:
        过滤后的Transaction对象列表
    """
    pairs = find_matching_refund_pairs(transactions)
    to_remove = {p.purchase for p in pairs} | {p.refund for p in pairs}

    for p in pairs:
        logger.info(
            "跳过匹配退款的交易: %s - 日期: %s - 来源: %s - 金额: %s",
            p.purchase.description,
            p.purchase.date,
            p.purchase.source,
            p.purchase.amount,
        )
        logger.info(
            "跳过匹配退款的交易: %s - 日期: %s - 来源: %s - 金额: %s",
            p.refund.description,
            p.refund.date,
            p.refund.source,
            p.refund.amount,
        )

    return [t for t in transactions if t not in to_remove]
