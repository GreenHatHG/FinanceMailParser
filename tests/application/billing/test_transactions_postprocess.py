from __future__ import annotations

from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import DigitalPaymentTransaction, Transaction
from financemailparser.application.billing.transactions_postprocess import (
    apply_expenses_account_rules,
    filter_transactions_by_rules,
    merge_transaction_descriptions,
)


def _cc(
    date: str, description: str, amount: float, source: TransactionSource
) -> Transaction:
    return Transaction(source.value, date, description, amount)


def _dp(
    date: str,
    description: str,
    amount: float,
    *,
    source: TransactionSource = TransactionSource.ALIPAY,
    card_source: TransactionSource | None = None,
) -> DigitalPaymentTransaction:
    txn = DigitalPaymentTransaction(source.value, date, description, amount)
    txn.card_source = card_source
    return txn


def test_merge_transaction_descriptions_merges_longer_description_and_dedupes_dp() -> (
    None
):
    cc = _cc("2026-01-01", "短", 12.34, TransactionSource.CCB)
    dp_match = _dp(
        "2026-01-01",
        "更长的描述",
        12.34,
        card_source=TransactionSource.CCB,
    )
    dp_unmatched = _dp("2026-01-02", "Other", 1.0, card_source=TransactionSource.CCB)

    out = merge_transaction_descriptions([cc], [dp_match, dp_unmatched])

    assert cc.description == "更长的描述"
    assert out[0] is cc
    assert dp_match not in out
    assert dp_unmatched in out


def test_merge_transaction_descriptions_keeps_cc_description_when_not_shorter() -> None:
    cc = _cc("2026-01-01", "same_len", 10.0, TransactionSource.CCB)
    dp_match = _dp(
        "2026-01-01",
        "same_len",
        10.0,
        card_source=TransactionSource.CCB,
    )
    out = merge_transaction_descriptions([cc], [dp_match])
    assert cc.description == "same_len"
    assert out == [cc]


def test_filter_transactions_by_rules_counts_stats_and_applies_priority() -> None:
    txns = [
        _cc("2026-01-01", "含关键字-跳过", 1.0, TransactionSource.CCB),
        _cc("2026-01-01", "金额命中区间", 9.0, TransactionSource.CCB),
        _cc("2026-01-01", "保留", 100.0, TransactionSource.CCB),
    ]

    filtered, stats = filter_transactions_by_rules(
        txns,
        skip_keywords=["关键字"],
        amount_ranges=[{"gte": 0.0, "lte": 10.0}],
    )

    assert [t.description for t in filtered] == ["保留"]
    assert stats.before_total == 3
    assert stats.after_total == 1
    assert stats.skipped_by_keyword == 1
    assert stats.skipped_by_amount == 1


def test_apply_expenses_account_rules_only_applies_to_expenses_and_returns_count() -> (
    None
):
    t1 = _cc("2026-01-01", "星巴克", 12.34, TransactionSource.CCB)
    t2 = _cc("2026-01-01", "不匹配", 5.0, TransactionSource.CCB)
    income = _cc("2026-01-01", "星巴克", -12.34, TransactionSource.CCB)

    rules = [{"account": "Expenses:Food:Cafe", "keywords": ["星巴克"]}]
    matched = apply_expenses_account_rules([t1, t2, income], expenses_rules=rules)

    assert matched == 1
    assert getattr(t1, "beancount_expenses_account") == "Expenses:Food:Cafe"
    assert getattr(t2, "beancount_expenses_account", None) is None
    assert getattr(income, "beancount_expenses_account", None) is None
