from __future__ import annotations

from financemailparser.infrastructure.beancount.validator import BeancountReconciler
from financemailparser.infrastructure.beancount.validator import (
    summarize_totals_by_currency,
    summarize_transaction_balances,
)


def test_parse_transactions_extracts_amounts_and_accounts() -> None:
    text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:TODO  -12.34 CNY\n"
        "\n"
        '2026-01-02 * "Book"\n'
        "  Assets:TODO  __AMT_r_000001__ CNY\n"
        "  Expenses:TODO  -__AMT_r_000001__ CNY\n"
        "\n"
    )
    r = BeancountReconciler()
    txns = r.parse_transactions(text)

    assert len(txns) == 2
    assert txns[0].date == "2026-01-01"
    assert txns[0].description == "Coffee"
    assert set(txns[0].amounts) == {"12.34 CNY", "-12.34 CNY"}
    assert set(txns[0].accounts) == {"Expenses:Food", "Assets:TODO"}

    assert txns[1].description == "Book"
    assert set(txns[1].amounts) == {
        "__AMT_r_000001__ CNY",
        "-__AMT_r_000001__ CNY",
    }


def test_reconcile_detects_missing_and_added_transactions() -> None:
    before_text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:TODO  -12.34 CNY\n"
        "\n"
        '2026-01-02 * "Book"\n'
        "  Expenses:TODO  10.00 CNY\n"
        "  Assets:TODO  -10.00 CNY\n"
        "\n"
    )
    after_text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:TODO  -12.34 CNY\n"
        "\n"
        '2026-01-03 * "Tea"\n'
        "  Expenses:TODO  1.00 CNY\n"
        "  Assets:TODO  -1.00 CNY\n"
        "\n"
    )

    r = BeancountReconciler()
    rep = r.reconcile(before_text, after_text)
    assert rep.total_before == 2
    assert rep.total_after == 2
    assert rep.is_valid is False
    assert rep.error_message is not None
    assert any(t.description == "Book" for t in rep.missing)
    assert any(t.description == "Tea" for t in rep.added)


def test_summarize_totals_by_currency_sums_postings() -> None:
    text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:Cash  -12.34 CNY\n"
        "\n"
        '2026-01-02 * "Book"\n'
        "  Expenses:Books  10.00 CNY\n"
        "  Assets:Cash  -10.00 CNY\n"
        "\n"
    )
    rep = summarize_totals_by_currency(text)
    assert rep.parse_error is None
    assert rep.transactions_total == 2
    assert rep.postings_without_units == 0
    assert "CNY" in rep.totals
    assert str(rep.totals["CNY"].positive) == "22.34"
    assert str(rep.totals["CNY"].negative) == "-22.34"
    assert str(rep.totals["CNY"].net) == "0.00"


def test_summarize_transaction_balances_detects_unbalanced_and_unknown() -> None:
    text = (
        '2026-01-01 * "Balanced"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:Cash  -12.34 CNY\n"
        "\n"
        '2026-01-02 * "Unbalanced"\n'
        "  Expenses:Food  10.00 CNY\n"
        "  Assets:Cash  -9.00 CNY\n"
        "\n"
        '2026-01-03 * "Unknown"\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash\n"
        "\n"
    )
    rep = summarize_transaction_balances(text, examples_max=10)
    assert rep.parse_error is None
    assert rep.transactions_total == 3
    assert rep.balanced == 1
    assert rep.unbalanced == 1
    assert rep.unknown == 1
    assert any(ex.description == "Unbalanced" for ex in rep.examples)
