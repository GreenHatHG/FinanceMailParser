from __future__ import annotations

from pathlib import Path

from typing import cast

import pytest
import yaml

from financemailparser.infrastructure.config import business_rules as br
from financemailparser.infrastructure.config import config_manager as cm
from financemailparser.infrastructure.config.config_manager import get_config_manager
from financemailparser.infrastructure.config.user_rules import (
    AmountRange,
    UserRulesError,
    amount_in_ranges,
    get_expenses_account_rules,
    get_transaction_filters,
    match_expenses_account,
    save_expenses_account_rules,
    save_transaction_filters,
)


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _set_business_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rules_file = tmp_path / "business_rules.yaml"
    _write_yaml(
        rules_file,
        """
version: 1
email_subject_keywords:
  credit_card: ["x"]
  alipay: ["y"]
  wechat: ["z"]
transaction_filters_defaults:
  skip_keywords: ["A", "B"]
  amount_ranges:
    - {gte: 0, lte: 10}
bank_alias_keywords:
  CCB: {display_name: "建设银行", aliases: ["建行"]}
""".lstrip(),
    )
    monkeypatch.setattr(br, "BUSINESS_RULES_FILE", rules_file)
    br.get_business_rules.cache_clear()
    return rules_file


def _set_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(cm, "CONFIG_FILE", config_file)
    get_config_manager.cache_clear()
    return config_file


def test_get_expenses_account_rules_returns_empty_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    _set_config_file(tmp_path, monkeypatch)
    assert get_expenses_account_rules() == []


def test_get_expenses_account_rules_normalizes_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    config_file = _set_config_file(tmp_path, monkeypatch)

    _write_yaml(
        config_file,
        """
user_rules:
  version: 1
  expenses_account_rules:
    rules:
      - account: " Expenses:Food:Cafe "
        keywords: [" 星巴克 ", "瑞幸"]
""".lstrip(),
    )

    rules = get_expenses_account_rules()
    assert rules == [{"account": "Expenses:Food:Cafe", "keywords": ["星巴克", "瑞幸"]}]


def test_get_expenses_account_rules_rejects_todo_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    config_file = _set_config_file(tmp_path, monkeypatch)

    _write_yaml(
        config_file,
        """
user_rules:
  version: 1
  expenses_account_rules:
    rules:
      - account: "Expenses:TODO:Food"
        keywords: ["x"]
""".lstrip(),
    )

    with pytest.raises(UserRulesError) as exc:
        get_expenses_account_rules()
    assert "不允许包含" in str(exc.value)


def test_match_expenses_account_first_match_wins() -> None:
    rules = [
        {"account": "Expenses:Food", "keywords": ["星巴克"]},
        {"account": "Expenses:Other", "keywords": ["星"]},
    ]
    assert match_expenses_account("今天去星巴克", rules) == "Expenses:Food"


def test_get_transaction_filters_uses_defaults_and_allows_partial_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    config_file = _set_config_file(tmp_path, monkeypatch)

    # Missing transaction_filters -> defaults
    _write_yaml(
        config_file,
        """
user_rules:
  version: 1
""".lstrip(),
    )
    out = get_transaction_filters()
    assert out["skip_keywords"] == ["A", "B"]
    assert out["amount_ranges"] == [{"gte": 0.0, "lte": 10.0}]

    # Empty skip_keywords overrides, ranges fallback to defaults
    _write_yaml(
        config_file,
        """
user_rules:
  version: 1
  transaction_filters:
    skip_keywords: []
""".lstrip(),
    )
    out2 = get_transaction_filters()
    assert out2["skip_keywords"] == []
    assert out2["amount_ranges"] == [{"gte": 0.0, "lte": 10.0}]


def test_save_transaction_filters_persists_normalized_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    config_file = _set_config_file(tmp_path, monkeypatch)

    save_transaction_filters(
        skip_keywords=["  k  "],
        amount_ranges=[{"gte": "1", "lte": 2}],
    )

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert raw["user_rules"]["version"] == 1
    assert raw["user_rules"]["transaction_filters"]["skip_keywords"] == ["k"]
    assert raw["user_rules"]["transaction_filters"]["amount_filters"]["ranges"] == [
        {"gte": 1.0, "lte": 2.0}
    ]


def test_save_expenses_account_rules_persists_normalized_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_business_rules(tmp_path, monkeypatch)
    config_file = _set_config_file(tmp_path, monkeypatch)

    save_expenses_account_rules(
        [{"account": " Expenses:Food:Cafe ", "keywords": [" 星巴克 "]}]
    )
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert raw["user_rules"]["expenses_account_rules"]["rules"] == [
        {"account": "Expenses:Food:Cafe", "keywords": ["星巴克"]}
    ]


def test_amount_in_ranges_is_inclusive_and_ignores_invalid_ranges() -> None:
    ranges_raw: list[dict[str, object]] = [
        {"gte": 0.0, "lte": 10.0},
        {"gte": "x", "lte": 1.0},  # invalid range, should be ignored by implementation
    ]
    ranges = cast(list[AmountRange], ranges_raw)
    assert amount_in_ranges(0.0, ranges) is True
    assert amount_in_ranges(10.0, ranges) is True
    assert amount_in_ranges(10.1, ranges) is False
