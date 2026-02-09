from __future__ import annotations

from typing import Any, Mapping, cast

from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.services.bank_alias import (
    build_bank_alias_keywords,
    build_bank_display_names,
    find_bank_code_by_alias,
    find_transaction_source_by_alias,
)


def test_build_bank_alias_keywords_normalizes_and_ignores_invalid_inputs() -> None:
    rules: dict[str, object] = {
        " ccb ": {"aliases": [" 建行 ", "", None, "CCB"]},
        "cmb": {"aliases": "not-a-list"},
        "": {"aliases": ["x"]},
        "icbc": None,
    }
    assert build_bank_alias_keywords(cast(Mapping[str, Mapping[str, Any]], rules)) == {
        "CCB": ["建行", "CCB"]
    }


def test_build_bank_display_names_normalizes_and_ignores_invalid_inputs() -> None:
    rules: dict[str, object] = {
        " ccb ": {"display_name": " 建设银行 "},
        "cmb": {"display_name": ""},
        "": {"display_name": "x"},
        "icbc": None,
    }
    assert build_bank_display_names(cast(Mapping[str, Mapping[str, Any]], rules)) == {
        "CCB": "建设银行"
    }


def test_find_bank_code_by_alias_is_case_insensitive_substring_match() -> None:
    keywords = {"CCB": ["建行", "ccb"], "CMB": ["招行"]}
    assert (
        find_bank_code_by_alias(
            "【CCB】中国建设银行信用卡电子账单", bank_alias_keywords=keywords
        )
        == "CCB"
    )
    assert (
        find_bank_code_by_alias("这是招行账单", bank_alias_keywords=keywords) == "CMB"
    )
    assert find_bank_code_by_alias("完全不相关", bank_alias_keywords=keywords) is None


def test_find_transaction_source_by_alias_returns_none_for_unknown_code() -> None:
    keywords = {"CCB": ["建行"], "NOT_IN_ENUM": ["not-in-enum"]}
    assert (
        find_transaction_source_by_alias("建行账单", bank_alias_keywords=keywords)
        == TransactionSource.CCB
    )
    assert (
        find_transaction_source_by_alias("not-in-enum", bank_alias_keywords=keywords)
        is None
    )
