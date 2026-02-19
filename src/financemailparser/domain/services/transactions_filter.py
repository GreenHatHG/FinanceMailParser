from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.text_similarity import bigram_jaccard_similarity
from financemailparser.domain.services.date_filter import parse_date_safe

logger = logging.getLogger(__name__)

# A low threshold that only blocks "obviously unrelated" matches.
# Similarity is computed on normalized char-bigram Jaccard in [0, 1].
REFUND_PAIR_DESC_SIMILARITY_MIN: float = 0.05


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
        # Index by absolute amount to reduce O(n^2) scans.
        positive_by_amount: Dict[float, List[Tuple[int, Transaction]]] = {}
        negative_by_amount: Dict[float, List[Tuple[int, Transaction]]] = {}

        for idx, txn in enumerate(txns):
            if txn.amount > 0:
                positive_by_amount.setdefault(txn.amount, []).append((idx, txn))
            else:
                negative_by_amount.setdefault(abs(txn.amount), []).append((idx, txn))

        matched_positive: set[int] = set()
        matched_negative: set[int] = set()

        def _days_delta_safe(
            *, purchase: Transaction, refund: Transaction
        ) -> Optional[int]:
            pos_dt = parse_date_safe(getattr(purchase, "date", ""))
            neg_dt = parse_date_safe(getattr(refund, "date", ""))
            if not pos_dt or not neg_dt:
                return None
            delta = (neg_dt.date() - pos_dt.date()).days
            return delta if delta >= 0 else None

        # Prefer deterministic ordering: process negative transactions in their
        # original order within the group.
        for amount_abs in sorted(negative_by_amount.keys()):
            if amount_abs not in positive_by_amount:
                continue

            for neg_idx, neg_txn in sorted(
                negative_by_amount[amount_abs], key=lambda x: x[0]
            ):
                if neg_idx in matched_negative:
                    continue

                best_pos_idx: Optional[int] = None
                best_pos_txn: Optional[Transaction] = None
                best_similarity: float = -1.0
                best_days_delta: int = 10**9

                for pos_idx, pos_txn in positive_by_amount.get(amount_abs, []):
                    if pos_idx in matched_positive:
                        continue

                    days_delta = _days_delta_safe(purchase=pos_txn, refund=neg_txn)
                    if days_delta is None:
                        continue

                    similarity = bigram_jaccard_similarity(
                        str(getattr(pos_txn, "description", "") or ""),
                        str(getattr(neg_txn, "description", "") or ""),
                    )
                    if similarity < REFUND_PAIR_DESC_SIMILARITY_MIN:
                        continue

                    # Choose best by:
                    # 1) higher similarity
                    # 2) closer date (smaller delta days)
                    # 3) stable order (smaller original index)
                    if (
                        (similarity > best_similarity)
                        or (
                            similarity == best_similarity
                            and days_delta < best_days_delta
                        )
                        or (
                            similarity == best_similarity
                            and days_delta == best_days_delta
                            and (best_pos_idx is None or pos_idx < best_pos_idx)
                        )
                    ):
                        best_similarity = similarity
                        best_days_delta = days_delta
                        best_pos_idx = pos_idx
                        best_pos_txn = pos_txn

                if best_pos_idx is not None and best_pos_txn is not None:
                    matched_positive.add(best_pos_idx)
                    matched_negative.add(neg_idx)
                    pairs.append(RefundPair(purchase=best_pos_txn, refund=neg_txn))

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
    - 描述相似度必须达到阈值（仅过滤“明显不像”的配对候选）

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
