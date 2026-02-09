from __future__ import annotations

from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.transactions_filter import (
    filter_matching_refunds,
)


def _txn(date: str, description: str, amount: float) -> Transaction:
    return Transaction(TransactionSource.CCB.value, date, description, amount)


def test_filters_exact_refund_pair_same_date_description() -> None:
    txns = [
        _txn("2026-01-01", "Coffee", 12.34),
        _txn("2026-01-01", "Coffee", -12.34),
    ]
    assert filter_matching_refunds(txns) == []


def test_partially_matches_multiple_transactions_in_same_group() -> None:
    txns = [
        _txn("2026-01-01", "Coffee", 10.0),
        _txn("2026-01-01", "Coffee", 10.0),
        _txn("2026-01-01", "Coffee", -10.0),
    ]
    out = filter_matching_refunds(txns)
    assert [(t.date, t.description, t.amount) for t in out] == [
        ("2026-01-01", "Coffee", 10.0),
    ]


def test_keeps_unmatched_when_amount_differs() -> None:
    txns = [
        _txn("2026-01-01", "Coffee", 10.0),
        _txn("2026-01-01", "Coffee", -9.0),
    ]
    out = filter_matching_refunds(txns)
    assert sorted((t.date, t.description, t.amount) for t in out) == sorted(
        [
            ("2026-01-01", "Coffee", 10.0),
            ("2026-01-01", "Coffee", -9.0),
        ]
    )


def test_does_not_match_across_descriptions_or_dates() -> None:
    txns = [
        _txn("2026-01-01", "Coffee", 10.0),
        _txn("2026-01-01", "Tea", -10.0),
        _txn("2026-01-02", "Coffee", -10.0),
    ]
    out = filter_matching_refunds(txns)
    assert sorted((t.date, t.description, t.amount) for t in out) == sorted(
        [
            ("2026-01-01", "Coffee", 10.0),
            ("2026-01-01", "Tea", -10.0),
            ("2026-01-02", "Coffee", -10.0),
        ]
    )
