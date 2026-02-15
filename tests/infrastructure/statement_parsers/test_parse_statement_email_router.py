from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pytest

from financemailparser.shared.constants import (
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)
from financemailparser.domain.models.txn import Transaction
from financemailparser.infrastructure.statement_parsers import parse as parse_mod


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_statement_email_returns_none_when_missing_required_files(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "20260101_ccb"
    folder.mkdir()

    assert (
        parse_mod.parse_statement_email(
            folder, bank_alias_keywords={"CCB": ["建设银行"]}
        )
        is None
    )

    _write_text(folder / EMAIL_HTML_FILENAME, "<html></html>")
    assert (
        parse_mod.parse_statement_email(
            folder, bank_alias_keywords={"CCB": ["建设银行"]}
        )
        is None
    )


def test_parse_statement_email_routes_by_bank_alias_and_calls_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "20260101_ccb"
    folder.mkdir()
    _write_text(folder / EMAIL_HTML_FILENAME, "<html></html>")
    _write_text(
        folder / EMAIL_METADATA_FILENAME, '{"subject":"中国建设银行信用卡电子账单"}'
    )

    called: dict[str, object] = {}

    def stub_parser(
        file_path: str,
        start_date: datetime | None,
        end_date: datetime | None,
        *,
        skip_transaction: Callable[[str], bool] | None = None,
    ) -> list[Transaction]:
        called["file_path"] = file_path
        called["start_date"] = start_date
        called["end_date"] = end_date
        called["skip_transaction"] = skip_transaction
        return []

    monkeypatch.setitem(parse_mod._CREDIT_CARD_PARSER_BY_BANK_CODE, "CCB", stub_parser)

    def skip(desc: str) -> bool:
        return "x" in desc

    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 31)
    out = parse_mod.parse_statement_email(
        folder,
        start_date=start,
        end_date=end,
        skip_transaction=skip,
        bank_alias_keywords={"CCB": ["建设银行"]},
    )

    assert out == []
    assert called["file_path"] == str((folder / EMAIL_HTML_FILENAME))
    assert called["start_date"] == start
    assert called["end_date"] == end
    assert called["skip_transaction"] is skip


def test_parse_statement_email_returns_none_when_alias_unknown(tmp_path: Path) -> None:
    folder = tmp_path / "20260101_unknown"
    folder.mkdir()
    _write_text(folder / EMAIL_HTML_FILENAME, "<html></html>")
    _write_text(folder / EMAIL_METADATA_FILENAME, '{"subject":"完全未知的账单"}')

    assert (
        parse_mod.parse_statement_email(
            folder, bank_alias_keywords={"CCB": ["建设银行"]}
        )
        is None
    )


def test_parse_statement_email_returns_none_when_parser_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "20260101_ccb"
    folder.mkdir()
    _write_text(folder / EMAIL_HTML_FILENAME, "<html></html>")
    _write_text(folder / EMAIL_METADATA_FILENAME, '{"subject":"建设银行"}')

    def boom(*_args: object, **_kwargs: object) -> list[Transaction]:
        raise RuntimeError("boom")

    monkeypatch.setitem(parse_mod._CREDIT_CARD_PARSER_BY_BANK_CODE, "CCB", boom)
    assert (
        parse_mod.parse_statement_email(
            folder, bank_alias_keywords={"CCB": ["建设银行"]}
        )
        is None
    )


def test_parse_statement_email_routes_alipay_and_wechat_with_expected_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 31)
    keywords: Mapping[str, Sequence[str]] = {"CCB": ["建设银行"]}

    def skip(desc: str) -> bool:
        return False

    alipay_dir = tmp_path / "alipay" / "nested"
    alipay_dir.mkdir(parents=True)
    (alipay_dir / "a.csv").write_text("x", encoding="utf-8")

    wechat_dir = tmp_path / "wechat"
    wechat_dir.mkdir()
    (wechat_dir / "w.xlsx").write_text("x", encoding="utf-8")

    called: list[tuple[str, str]] = []

    def stub_alipay(
        csv_path: str,
        start_date: datetime | None,
        end_date: datetime | None,
        *,
        skip_transaction: Callable[[str], bool] | None = None,
        bank_alias_keywords: Mapping[str, Sequence[str]] | None = None,
    ) -> list[Transaction]:
        called.append(("alipay", csv_path))
        assert start_date == start
        assert end_date == end
        assert skip_transaction is skip
        assert bank_alias_keywords == keywords
        return []

    def stub_wechat(
        xlsx_path: str,
        start_date: datetime | None,
        end_date: datetime | None,
        *,
        skip_transaction: Callable[[str], bool] | None = None,
        bank_alias_keywords: Mapping[str, Sequence[str]] | None = None,
    ) -> list[Transaction]:
        called.append(("wechat", xlsx_path))
        assert start_date == start
        assert end_date == end
        assert skip_transaction is skip
        assert bank_alias_keywords == keywords
        return []

    monkeypatch.setattr(parse_mod, "parse_alipay_statement", stub_alipay)
    monkeypatch.setattr(parse_mod, "parse_wechat_statement", stub_wechat)

    assert (
        parse_mod.parse_statement_email(
            tmp_path / "alipay",
            start_date=start,
            end_date=end,
            skip_transaction=skip,
            bank_alias_keywords=keywords,
        )
        == []
    )
    assert (
        parse_mod.parse_statement_email(
            tmp_path / "wechat",
            start_date=start,
            end_date=end,
            skip_transaction=skip,
            bank_alias_keywords=keywords,
        )
        == []
    )

    assert len(called) == 2
    assert called[0][0] == "alipay"
    assert called[1][0] == "wechat"


def test_parse_statement_email_returns_none_when_wallet_file_missing(
    tmp_path: Path,
) -> None:
    alipay_dir = tmp_path / "alipay"
    alipay_dir.mkdir()
    assert parse_mod.parse_statement_email(alipay_dir) is None

    wechat_dir = tmp_path / "wechat"
    wechat_dir.mkdir()
    assert parse_mod.parse_statement_email(wechat_dir) is None
