from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from financemailparser.application.billing import parse_export as mod
from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import Transaction
from financemailparser.application.billing.transactions_postprocess import (
    TransactionFilterStats,
)


def _txn(date: str, desc: str, amt: float, source: TransactionSource) -> Transaction:
    return Transaction(source.value, date, desc, amt)


def test_parse_downloaded_bills_to_beancount_raises_when_emails_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "EMAILS_DIR", tmp_path / "missing_emails")
    with pytest.raises(FileNotFoundError):
        mod.parse_downloaded_bills_to_beancount(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 31),
            log_level="INFO",
        )


def test_parse_downloaded_bills_to_beancount_writes_output_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emails_dir = tmp_path / "emails"
    emails_dir.mkdir()
    output_dir = tmp_path / "out"

    monkeypatch.setattr(mod, "EMAILS_DIR", emails_dir)
    monkeypatch.setattr(mod, "BEANCOUNT_OUTPUT_DIR", output_dir)

    credit_folder = emails_dir / "cc"
    digital_folder = emails_dir / "alipay"
    credit_folder.mkdir()
    digital_folder.mkdir()

    monkeypatch.setattr(
        mod,
        "scan_downloaded_bill_folders",
        lambda _p: ([credit_folder], [digital_folder]),
    )
    monkeypatch.setattr(
        mod,
        "load_transaction_filters_safe",
        lambda: (["skip"], [{"gte": 0.0, "lte": 0.0}]),
    )
    monkeypatch.setattr(
        mod, "make_should_skip_transaction", lambda _k: (lambda _d: False)
    )
    monkeypatch.setattr(
        mod,
        "get_bank_alias_keywords",
        lambda: {"CCB": {"display_name": "x", "aliases": ["x"]}},
    )
    monkeypatch.setattr(mod, "build_bank_alias_keywords", lambda _r: {"CCB": ["x"]})

    calls: list[tuple[str, Path]] = []

    def stub_parse(
        folder: Path, *_args: object, **_kwargs: object
    ) -> list[Transaction]:
        calls.append(("parse", folder))
        if folder.name == "cc":
            return [_txn("2026-01-02", "Coffee", 12.34, TransactionSource.CCB)]
        return [_txn("2026-01-03", "Tea", 1.0, TransactionSource.ALIPAY)]

    monkeypatch.setattr(mod, "parse_statement_email", stub_parse)
    monkeypatch.setattr(
        mod, "merge_transaction_descriptions", lambda cc, dp: list(cc) + list(dp)
    )
    monkeypatch.setattr(
        mod,
        "filter_transactions_by_rules",
        lambda txns, **_kw: (
            list(txns),
            TransactionFilterStats(0, 0, len(list(txns)), len(list(txns))),
        ),
    )
    monkeypatch.setattr(mod, "load_expenses_account_rules_safe", lambda: [])
    monkeypatch.setattr(mod, "apply_expenses_account_rules", lambda *_a, **_kw: 0)
    monkeypatch.setattr(mod, "transactions_to_beancount", lambda *_a, **_kw: "BEAN")

    progress: list[tuple[int, int, str]] = []

    def cb(p: int, total: int, msg: str) -> None:
        progress.append((p, total, msg))

    result = mod.parse_downloaded_bills_to_beancount(
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        log_level="INFO",
        progress_callback=cb,
    )

    assert result["beancount_text"] == "BEAN"
    assert Path(str(result["output_path"])).exists() is True
    assert any(p == 100 and total == 100 for p, total, _ in progress)
    assert calls and {p for _, p in calls} == {credit_folder, digital_folder}
