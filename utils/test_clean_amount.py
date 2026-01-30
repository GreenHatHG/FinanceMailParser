import unittest
from utils.clean_amount import clean_amount


class TestCleanAmount(unittest.TestCase):
    def test_valid_amount(self):
        self.assertEqual(clean_amount("¥1,234.56"), 1234.56)
        self.assertEqual(clean_amount("存入¥1,000"), -1000.0)
        self.assertEqual(clean_amount("1000.00"), 1000.00)
        self.assertEqual(clean_amount("1,234,567.89"), 1234567.89)
        self.assertEqual(clean_amount("¥0.99"), 0.99)
        self.assertEqual(clean_amount("存入¥0"), 0.0)
        self.assertEqual(clean_amount("¥1,000,000.00"), 1000000.00)
        self.assertEqual(clean_amount("1,234.00元"), 1234.00)

    def test_invalid_amount(self):
        with self.assertRaises(ValueError):
            clean_amount("无效金额")
        with self.assertRaises(ValueError):
            clean_amount("存入无效金额")
        with self.assertRaises(ValueError):
            clean_amount("¥abc")
        with self.assertRaises(ValueError):
            clean_amount("123,456.78.90")  # 两个小数点的情况

    def test_edge_cases(self):
        self.assertEqual(clean_amount("存入¥-1,000"), 1000.0)
        self.assertEqual(clean_amount("¥-1,234.56"), -1234.56)
        self.assertEqual(clean_amount("¥1,234,567.00"), 1234567.00)
        self.assertEqual(clean_amount("¥0"), 0.0)

    def test_basic_amount(self):
        self.assertEqual(clean_amount("1234.56"), 1234.56)

    def test_amount_with_comma(self):
        self.assertEqual(clean_amount("1,234,567.89"), 1234567.89)

    def test_amount_with_currency_symbol(self):
        self.assertEqual(clean_amount("¥1,234,567.89"), 1234567.89)
        self.assertEqual(clean_amount("1,234,567.89/CNY"), 1234567.89)
        self.assertEqual(clean_amount("20.00/RMB"), 20.00)

    def test_amount_with_negative_sign(self):
        self.assertEqual(clean_amount("-1,234,567.89"), -1234567.89)

    def test_amount_with_deposit_keyword(self):
        self.assertEqual(clean_amount("存入 1,234,567.89"), -1234567.89)

    def test_amount_with_whitespace(self):
        self.assertEqual(clean_amount("  1,234,567.89  "), 1234567.89)

    def test_amount_with_multiple_commas(self):
        self.assertEqual(clean_amount("1,234,567,890.12"), 1234567890.12)

    def test_amount_with_trailing_comma(self):
        self.assertEqual(clean_amount("1,234,567,"), 1234567.0)

    def test_amount_with_leading_zero(self):
        self.assertEqual(clean_amount("01,234.56"), 1234.56)

    def test_amount_with_multiple_currency_symbols(self):
        self.assertEqual(clean_amount("¥¥1,234,567.89/CNY"), 1234567.89)


if __name__ == "__main__":
    unittest.main()
