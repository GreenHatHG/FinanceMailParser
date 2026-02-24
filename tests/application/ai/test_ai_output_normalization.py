from __future__ import annotations

from financemailparser.application.ai.process_beancount import (
    extract_beancount_text_from_ai_output,
)


def test_extract_beancount_text_from_ai_output_prefers_beancount_fence() -> None:
    raw = (
        "这里是结果：\n\n"
        "```text\n"
        "not beancount\n"
        "```\n\n"
        "```beancount\n"
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  12.34 CNY\n"
        "  Assets:Cash  -12.34 CNY\n"
        "```\n"
    )
    extracted, note = extract_beancount_text_from_ai_output(raw)
    assert note is not None
    assert extracted.startswith('2026-01-01 * "Coffee"')
    assert "```" not in extracted


def test_extract_beancount_text_from_ai_output_returns_original_when_no_fence() -> None:
    raw = (
        '2026-01-01 * "Coffee"\n  Expenses:Food  12.34 CNY\n  Assets:Cash  -12.34 CNY\n'
    )
    extracted, note = extract_beancount_text_from_ai_output(raw)
    assert note is None
    assert extracted == raw
