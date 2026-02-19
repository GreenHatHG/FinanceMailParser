from financemailparser.application.ai.process_beancount import (
    strip_beancount_export_comments,
)


def test_strips_known_export_header_and_source_comment_lines() -> None:
    text = (
        "; FinanceMailParser Export\n"
        "; Range: 2025-10-01 ~ 2025-10-31\n"
        "; Generated at: 2026-02-19 11:41:01\n"
        "; CC-Digital dedup: disabled\n"
        "; Refund dedup: disabled\n"
        "; Before dedup: 1, CC-Digital removed: 0, Refund pairs removed: 0, Final: 1\n"
        "; Accounts are placeholders (TODO) unless user_rules filled some Expenses accounts.\n"
        "\n"
        '2026-01-01 * "Coffee"\n'
        "  ; source: 支付宝\n"
        "  ; card_source: 工商银行信用卡\n"
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:Cash  -12.34 CNY\n"
        "\n"
        "; keep this\n"
    )

    out = strip_beancount_export_comments(text)

    assert out.startswith('2026-01-01 * "Coffee"\n')
    assert "FinanceMailParser Export" not in out
    assert "\n; Range:" not in out
    assert "\n; Generated at:" not in out
    assert "\n; CC-Digital dedup:" not in out
    assert "\n; Refund dedup:" not in out
    assert "\n; Before dedup:" not in out
    assert "Accounts are placeholders" not in out
    assert "  ; source:" not in out
    assert "  ; card_source:" not in out
    assert "; keep this\n" in out


def test_does_not_strip_other_comment_lines_or_inline_comments() -> None:
    text = (
        "\n"
        "; keep me\n"
        '2026-01-02 * "X"\n'
        "  Expenses:Food  1.00 CNY ; source: inline-comment-should-stay\n"
        "  Assets:Cash  -1.00 CNY\n"
    )

    out = strip_beancount_export_comments(text)

    assert out.startswith("\n; keep me\n")
    assert "; keep me\n" in out
    assert "inline-comment-should-stay" in out
