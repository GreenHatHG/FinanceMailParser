from __future__ import annotations

from financemailparser.infrastructure.beancount.validator import BeancountReconciler


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
