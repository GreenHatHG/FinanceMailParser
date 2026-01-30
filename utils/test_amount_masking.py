import unittest

from utils.amount_masking import AmountMasker, restore_beancount_amounts


class TestAmountMasking(unittest.TestCase):
    def test_masks_posting_amount_only(self):
        text = (
            '2026-01-01 * "Coffee"\n'
            "  Expenses:Food  -12.34 USD ; comment 99 USD\n"
            "  Assets:Cash\n"
        )
        masker = AmountMasker(run_id="r", start_seq=1)
        masked = masker.mask_text(text)

        self.assertIn("-__AMT_r_000001__ USD", masked)
        self.assertIn("comment 99 USD", masked)  # 注释内容应保持原样（不脱敏）
        self.assertEqual(len(masker.mapping), 1)  # 只应脱敏 posting 金额
        self.assertEqual(masker.mapping.get("__AMT_r_000001__"), "12.34")

        restored, rep = restore_beancount_amounts(masked, masker.mapping)
        self.assertEqual(restored, text)
        self.assertEqual(rep.tokens_replaced, 1)

    def test_masks_price_directive_without_touching_date(self):
        text = "2026-01-02 price BTC 42,000 USD ; 1 USD\n"
        masker = AmountMasker(run_id="r", start_seq=1)
        masked = masker.mask_text(text)

        self.assertTrue(masked.startswith("2026-01-02 price BTC "))
        self.assertIn("__AMT_r_000001__ USD", masked)
        self.assertNotIn("2026-01-__AMT_", masked)
        self.assertEqual(masker.mapping.get("__AMT_r_000001__"), "42,000")

        restored, _rep = restore_beancount_amounts(masked, masker.mapping)
        self.assertEqual(restored, text)

    def test_masks_multiple_amounts_same_line(self):
        text = '2026-01-03 * "X"\n  Assets:Broker  0.5 BTC @ 42000 USD\n'
        masker = AmountMasker(run_id="r", start_seq=1)
        masked = masker.mask_text(text)

        self.assertIn("__AMT_r_000001__ BTC @ __AMT_r_000002__ USD", masked)
        self.assertEqual(masker.mapping.get("__AMT_r_000001__"), "0.5")
        self.assertEqual(masker.mapping.get("__AMT_r_000002__"), "42000")

        restored, _rep = restore_beancount_amounts(masked, masker.mapping)
        self.assertEqual(restored, text)

    def test_masks_scientific_notation_when_lexer_marks_exponent_error(self):
        text = '2026-01-04 * "Y"\n  Expenses:Fees  1.2e-3 USD\n'
        masker = AmountMasker(run_id="r", start_seq=1)
        masked = masker.mask_text(text)

        self.assertIn("__AMT_r_000001__ USD", masked)
        self.assertEqual(masker.mapping.get("__AMT_r_000001__"), "1.2e-3")

        restored, _rep = restore_beancount_amounts(masked, masker.mapping)
        self.assertEqual(restored, text)


if __name__ == "__main__":
    unittest.main()
