import unittest

from utils.prompt_redaction_check import check_prompt_redaction


class TestPromptRedactionCheck(unittest.TestCase):
    def test_ok_when_only_amt_tokens(self):
        prompt = (
            "Some text\n\n"
            "```beancount\n"
            '2026-01-01 * "Coffee"\n'
            "  Expenses:Food  -__AMT_r_000001__ USD\n"
            "  Assets:Cash\n"
            "```\n"
        )
        result = check_prompt_redaction(prompt)
        self.assertTrue(result.ok)
        self.assertEqual(result.total_issues, 0)
        self.assertEqual(result.code_blocks_scanned, 1)

    def test_detects_unmasked_amount(self):
        prompt = (
            "```beancount\n"
            '2026-01-01 * "Coffee"\n'
            "  Expenses:Food  -12.34 USD\n"
            "  Assets:Cash\n"
            "```\n"
        )
        result = check_prompt_redaction(prompt)
        self.assertFalse(result.ok)
        self.assertEqual(result.total_issues, 1)
        self.assertTrue(any("USD" in line for line in result.sample_lines))

    def test_ignores_non_beancount_blocks_and_plain_text(self):
        prompt = (
            "12.34 USD\n"
            "```python\n"
            "x = 12.34\n"
            "```\n"
        )
        result = check_prompt_redaction(prompt)
        self.assertTrue(result.ok)
        self.assertEqual(result.total_issues, 0)
        self.assertEqual(result.code_blocks_scanned, 0)


if __name__ == "__main__":
    unittest.main()

