from __future__ import annotations

from pathlib import Path

import pytest

from financemailparser.infrastructure.config import business_rules as br


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_get_business_rules_normalizes_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules_file = tmp_path / "business_rules.yaml"
    _write_yaml(
        rules_file,
        """
version: 1
email_subject_keywords:
  credit_card: [" 信用卡 ", " 账单"]
  alipay: [" 支付宝 "]
  wechat: [" 微信 "]
transaction_filters_defaults:
  skip_keywords: [" 免息 "]
  amount_ranges:
    - {gte: "0", lte: 9.9}
bank_alias_keywords:
  " ccb ":
    display_name: " 建设银行 "
    aliases: [" 建行 ", "CCB"]
""".lstrip(),
    )

    monkeypatch.setattr(br, "BUSINESS_RULES_FILE", rules_file)
    br.get_business_rules.cache_clear()

    data = br.get_business_rules()
    assert data["email_subject_keywords"]["credit_card"] == ["信用卡", "账单"]
    assert data["transaction_filters_defaults"]["skip_keywords"] == ["免息"]
    assert data["transaction_filters_defaults"]["amount_ranges"] == [
        {"gte": 0.0, "lte": 9.9}
    ]
    assert data["bank_alias_keywords"]["CCB"]["display_name"] == "建设银行"
    assert data["bank_alias_keywords"]["CCB"]["aliases"] == ["建行", "CCB"]


def test_get_business_rules_raises_on_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules_file = tmp_path / "business_rules.yaml"
    _write_yaml(rules_file, "version: 0\n")

    monkeypatch.setattr(br, "BUSINESS_RULES_FILE", rules_file)
    br.get_business_rules.cache_clear()

    with pytest.raises(br.BusinessRulesError) as exc:
        br.get_business_rules()
    assert "版本不支持" in str(exc.value)


def test_get_business_rules_raises_on_missing_required_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules_file = tmp_path / "business_rules.yaml"
    _write_yaml(rules_file, "version: 1\n")

    monkeypatch.setattr(br, "BUSINESS_RULES_FILE", rules_file)
    br.get_business_rules.cache_clear()

    with pytest.raises(br.BusinessRulesError) as exc:
        br.get_business_rules()
    assert "email_subject_keywords" in str(exc.value)


def test_get_business_rules_rejects_invalid_amount_range_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
  skip_keywords: ["k"]
  amount_ranges:
    - {gte: 10, lte: 1}
bank_alias_keywords:
  CCB: {display_name: "建设银行", aliases: ["建行"]}
""".lstrip(),
    )

    monkeypatch.setattr(br, "BUSINESS_RULES_FILE", rules_file)
    br.get_business_rules.cache_clear()

    with pytest.raises(br.BusinessRulesError) as exc:
        br.get_business_rules()
    assert "非法区间" in str(exc.value)
