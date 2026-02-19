from __future__ import annotations

from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.transactions_filter import (
    filter_matching_refunds,
)


def _txn(
    date: str,
    description: str,
    amount: float,
    source: TransactionSource = TransactionSource.CCB,
) -> Transaction:
    return Transaction(source.value, date, description, amount)


def test_filters_exact_refund_pair_same_date_source() -> None:
    """同一来源、金额相等的正负交易应该被配对移除（退款日期可以晚于消费日期）"""
    txns = [
        _txn("2026-01-01", "Coffee", 12.34),
        _txn("2026-01-05", "Coffee Refund", -12.34),  # 5天后退款
    ]
    assert filter_matching_refunds(txns) == []


def test_partially_matches_multiple_transactions_in_same_group() -> None:
    """同一来源的多笔交易，部分配对（按描述更相似者优先）"""
    txns = [
        _txn("2026-01-01", "Starbucks", 10.0),
        _txn("2026-01-02", "McDonalds", 10.0),
        _txn("2026-01-05", "Starbucks Refund", -10.0),
    ]
    out = filter_matching_refunds(txns)
    assert [(t.date, t.description, t.amount) for t in out] == [
        ("2026-01-02", "McDonalds", 10.0),
    ]


def test_keeps_unmatched_when_amount_differs() -> None:
    """金额不同的交易不应该配对"""
    txns = [
        _txn("2026-01-01", "Coffee", 10.0),
        _txn("2026-01-05", "Refund", -9.0),
    ]
    out = filter_matching_refunds(txns)
    assert sorted((t.date, t.description, t.amount) for t in out) == sorted(
        [
            ("2026-01-01", "Coffee", 10.0),
            ("2026-01-05", "Refund", -9.0),
        ]
    )


def test_does_not_match_across_sources() -> None:
    """不同来源的交易不应该配对"""
    txns = [
        _txn("2026-01-01", "Coffee", 10.0, TransactionSource.CCB),
        _txn(
            "2026-01-05", "Refund", -10.0, TransactionSource.WECHAT
        ),  # 不同来源，不配对
    ]
    out = filter_matching_refunds(txns)
    assert sorted((t.date, t.description, t.amount) for t in out) == sorted(
        [
            ("2026-01-01", "Coffee", 10.0),
            ("2026-01-05", "Refund", -10.0),
        ]
    )


def test_matches_across_dates_same_source() -> None:
    """同一来源、金额相等的交易应该配对，只要退款日期晚于消费日期"""
    txns = [
        _txn("2026-01-01", "Coffee", 10.0, TransactionSource.CCB),
        _txn("2026-01-10", "Coffee Refund", -10.0, TransactionSource.CCB),  # 9天后退款
    ]
    out = filter_matching_refunds(txns)
    assert out == []


def test_does_not_match_when_descriptions_are_obviously_unrelated() -> None:
    """同一来源、金额相等但描述明显无关的交易不应该配对（避免误删）"""
    txns = [
        _txn("2026-01-01", "隆阳区段从勇餐馆-消费", 10.0, TransactionSource.ALIPAY),
        _txn(
            "2026-01-31",
            "支付宝转账小额打款-关联订单号：2966596791050371688",
            -10.0,
            TransactionSource.ALIPAY,
        ),
    ]
    out = filter_matching_refunds(txns)
    assert sorted((t.date, t.description, t.amount) for t in out) == sorted(
        [
            ("2026-01-01", "隆阳区段从勇餐馆-消费", 10.0),
            ("2026-01-31", "支付宝转账小额打款-关联订单号：2966596791050371688", -10.0),
        ]
    )


def test_does_not_match_when_refund_is_earlier_than_purchase() -> None:
    """退款日期早于消费日期时，不应该配对移除（偏保守，避免误删）"""
    txns = [
        _txn("2026-01-10", "Coffee", 10.0, TransactionSource.CCB),
        _txn("2026-01-01", "Refund", -10.0, TransactionSource.CCB),
    ]
    out = filter_matching_refunds(txns)
    assert [(t.date, t.description, t.amount) for t in out] == [
        ("2026-01-10", "Coffee", 10.0),
        ("2026-01-01", "Refund", -10.0),
    ]
