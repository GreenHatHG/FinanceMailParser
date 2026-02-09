from financemailparser.infrastructure.statement_parsers.clean_amount import clean_amount
import pytest


def test_valid_amount():
    assert clean_amount("¥1,234.56") == 1234.56
    assert clean_amount("存入¥1,000") == -1000.0
    assert clean_amount("1000.00") == 1000.00
    assert clean_amount("1,234,567.89") == 1234567.89
    assert clean_amount("¥0.99") == 0.99
    assert clean_amount("存入¥0") == 0.0
    assert clean_amount("¥1,000,000.00") == 1000000.00
    assert clean_amount("1,234.00元") == 1234.00


def test_invalid_amount():
    with pytest.raises(ValueError):
        clean_amount("无效金额")
    with pytest.raises(ValueError):
        clean_amount("存入无效金额")
    with pytest.raises(ValueError):
        clean_amount("¥abc")
    with pytest.raises(ValueError):
        clean_amount("123,456.78.90")  # 两个小数点的情况


def test_edge_cases():
    assert clean_amount("存入¥-1,000") == 1000.0
    assert clean_amount("¥-1,234.56") == -1234.56
    assert clean_amount("¥1,234,567.00") == 1234567.00
    assert clean_amount("¥0") == 0.0


def test_basic_amount():
    assert clean_amount("1234.56") == 1234.56


def test_amount_with_comma():
    assert clean_amount("1,234,567.89") == 1234567.89


def test_amount_with_currency_symbol():
    assert clean_amount("¥1,234,567.89") == 1234567.89
    assert clean_amount("1,234,567.89/CNY") == 1234567.89
    assert clean_amount("20.00/RMB") == 20.00


def test_amount_with_negative_sign():
    assert clean_amount("-1,234,567.89") == -1234567.89


def test_amount_with_deposit_keyword():
    assert clean_amount("存入 1,234,567.89") == -1234567.89


def test_amount_with_whitespace():
    assert clean_amount("  1,234,567.89  ") == 1234567.89


def test_amount_with_multiple_commas():
    assert clean_amount("1,234,567,890.12") == 1234567890.12


def test_amount_with_trailing_comma():
    assert clean_amount("1,234,567,") == 1234567.0


def test_amount_with_leading_zero():
    assert clean_amount("01,234.56") == 1234.56


def test_amount_with_multiple_currency_symbols():
    assert clean_amount("¥¥1,234,567.89/CNY") == 1234567.89
