from financemailparser.application.ai.prompt_redaction_check import (
    check_prompt_redaction,
)


def test_ok_when_only_amt_tokens():
    prompt = (
        "Some text\n\n"
        "```beancount\n"
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  -__AMT_r_000001__ USD\n"
        "  Assets:Cash\n"
        "```\n"
    )
    result = check_prompt_redaction(prompt)
    assert result.ok is True
    assert result.total_issues == 0
    assert result.code_blocks_scanned == 1


def test_detects_unmasked_amount():
    prompt = (
        "```beancount\n"
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  -12.34 USD\n"
        "  Assets:Cash\n"
        "```\n"
    )
    result = check_prompt_redaction(prompt)
    assert result.ok is False
    assert result.total_issues == 1
    assert any("USD" in line for line in result.sample_lines)


def test_ignores_non_beancount_blocks_and_plain_text():
    prompt = "12.34 USD\n```python\nx = 12.34\n```\n"
    result = check_prompt_redaction(prompt)
    assert result.ok is True
    assert result.total_issues == 0
    assert result.code_blocks_scanned == 0
