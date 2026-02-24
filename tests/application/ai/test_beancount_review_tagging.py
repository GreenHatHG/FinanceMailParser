from financemailparser.application.ai.process_beancount import (
    BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW,
    add_review_tag_to_beancount_transactions,
)


def test_adds_review_tag_to_each_transaction_header_line() -> None:
    text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash  -1.00 CNY\n"
        "\n"
        '2026-01-02 ! "Tea"\n'
        "  Expenses:Food  2.00 CNY\n"
        "  Assets:Cash  -2.00 CNY\n"
        "\n"
    )

    out = add_review_tag_to_beancount_transactions(text)

    assert f'2026-01-01 * "Coffee" {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}\n' in out
    assert f'2026-01-02 ! "Tea" {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}\n' in out
    assert "  Expenses:Food  1.00 CNY\n" in out
    assert "  Assets:Cash  -2.00 CNY\n" in out


def test_is_idempotent_when_tag_already_exists() -> None:
    text = (
        f'2026-01-01 * "Coffee" {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash  -1.00 CNY\n"
        "\n"
    )

    assert add_review_tag_to_beancount_transactions(text) == text


def test_preserves_existing_tags_and_appends_review_tag() -> None:
    text = (
        '2026-01-01 * "Coffee" #foo\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash  -1.00 CNY\n"
        "\n"
    )

    out = add_review_tag_to_beancount_transactions(text)

    assert f'2026-01-01 * "Coffee" #foo {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}\n' in out


def test_handles_two_quoted_strings_header() -> None:
    text = (
        '2026-01-01 * "Payee" "Narration"\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash  -1.00 CNY\n"
        "\n"
    )

    out = add_review_tag_to_beancount_transactions(text)

    assert (
        f'2026-01-01 * "Payee" "Narration" {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}\n' in out
    )


def test_inserts_tag_before_inline_comment() -> None:
    text = (
        '2026-01-01 * "Coffee" ; note\n'
        "  Expenses:Food  1.00 CNY\n"
        "  Assets:Cash  -1.00 CNY\n"
        "\n"
    )

    out = add_review_tag_to_beancount_transactions(text)

    assert f'2026-01-01 * "Coffee" {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW} ; note\n' in out


def test_does_not_touch_non_transaction_date_lines() -> None:
    text = (
        "2026-01-01 open Assets:Cash\n"
        "2026-01-01 balance Assets:Cash  0 CNY\n"
        "\n"
        "; comment\n"
    )

    assert add_review_tag_to_beancount_transactions(text) == text
