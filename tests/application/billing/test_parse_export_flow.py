from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from financemailparser.application.billing import parse_export as mod
from financemailparser.application.billing.parse_export import ParsedBillsResult
from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import DigitalPaymentTransaction, Transaction
from financemailparser.application.billing.transactions_postprocess import (
    TransactionFilterStats,
)


def _txn(date: str, desc: str, amt: float, source: TransactionSource) -> Transaction:
    return Transaction(source.value, date, desc, amt)


def _dp(
    date: str,
    desc: str,
    amt: float,
    *,
    source: TransactionSource = TransactionSource.WECHAT,
    card_source: TransactionSource | None = None,
) -> DigitalPaymentTransaction:
    txn = DigitalPaymentTransaction(source.value, date, desc, amt)
    txn.card_source = card_source
    return txn


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

    cc_txns = [_txn("2026-01-02", "Coffee", 12.34, TransactionSource.CCB)]
    dp_txns = [_txn("2026-01-03", "Tea", 1.0, TransactionSource.ALIPAY)]

    # parse_all_bills is now used internally; stub it to return known results
    monkeypatch.setattr(
        mod,
        "parse_all_bills",
        lambda *_a, **_kw: ParsedBillsResult(
            credit_card_transactions=cc_txns,
            digital_transactions=dp_txns,
            folders_total=2,
            folders_parsed=2,
        ),
    )
    monkeypatch.setattr(
        mod,
        "load_transaction_filters_safe",
        lambda: (["skip"], [{"gte": 0.0, "lte": 0.0}]),
    )
    monkeypatch.setattr(
        mod,
        "filter_transactions_by_rules",
        lambda txns, **_kw: (
            list(txns),
            TransactionFilterStats(0, 0, len(list(txns)), len(list(txns))),
            [],
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
    # Raw concat: cc + dp = 2 transactions total
    assert result["stats"]["txns_total"] == 2


def test_parse_downloaded_bills_no_dedup_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that parse_downloaded_bills_to_beancount does NOT call merge_transaction_descriptions."""
    emails_dir = tmp_path / "emails"
    emails_dir.mkdir()
    output_dir = tmp_path / "out"

    monkeypatch.setattr(mod, "EMAILS_DIR", emails_dir)
    monkeypatch.setattr(mod, "BEANCOUNT_OUTPUT_DIR", output_dir)

    monkeypatch.setattr(
        mod,
        "parse_all_bills",
        lambda *_a, **_kw: ParsedBillsResult(
            credit_card_transactions=[
                _txn("2026-01-01", "A", 10.0, TransactionSource.CCB)
            ],
            digital_transactions=[
                _txn("2026-01-01", "A", 10.0, TransactionSource.ALIPAY)
            ],
            folders_total=2,
            folders_parsed=2,
        ),
    )
    monkeypatch.setattr(
        mod,
        "load_transaction_filters_safe",
        lambda: ([], []),
    )
    monkeypatch.setattr(
        mod,
        "filter_transactions_by_rules",
        lambda txns, **_kw: (
            list(txns),
            TransactionFilterStats(0, 0, len(list(txns)), len(list(txns))),
            [],
        ),
    )
    monkeypatch.setattr(mod, "load_expenses_account_rules_safe", lambda: [])
    monkeypatch.setattr(mod, "apply_expenses_account_rules", lambda *_a, **_kw: 0)
    monkeypatch.setattr(mod, "transactions_to_beancount", lambda *_a, **_kw: "BEAN")

    result = mod.parse_downloaded_bills_to_beancount(
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
    )

    # Both transactions should be present (no dedup removes the duplicate)
    assert result["stats"]["txns_total"] == 2


def test_parse_downloaded_bills_to_beancount_with_dedup_updates_stats_and_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emails_dir = tmp_path / "emails"
    emails_dir.mkdir()
    output_dir = tmp_path / "out"

    monkeypatch.setattr(mod, "EMAILS_DIR", emails_dir)
    monkeypatch.setattr(mod, "BEANCOUNT_OUTPUT_DIR", output_dir)

    monkeypatch.setattr(
        mod,
        "parse_all_bills",
        lambda *_a, **_kw: ParsedBillsResult(
            credit_card_transactions=[
                _txn("2026-01-01", "短", 12.34, TransactionSource.CCB),
                _txn("2026-01-02", "X", 5.0, TransactionSource.CCB),
                _txn("2026-01-03", "X refund", -5.0, TransactionSource.CCB),
            ],
            digital_transactions=[
                _dp(
                    "2026-01-01",
                    "更长的描述",
                    12.34,
                    source=TransactionSource.WECHAT,
                    card_source=TransactionSource.CCB,
                ),
            ],
            folders_total=2,
            folders_parsed=2,
        ),
    )
    monkeypatch.setattr(
        mod,
        "load_transaction_filters_safe",
        lambda: ([], []),
    )
    monkeypatch.setattr(
        mod,
        "filter_transactions_by_rules",
        lambda txns, **_kw: (
            list(txns),
            TransactionFilterStats(0, 0, len(list(txns)), len(list(txns))),
            [],
        ),
    )
    monkeypatch.setattr(mod, "load_expenses_account_rules_safe", lambda: [])
    monkeypatch.setattr(mod, "apply_expenses_account_rules", lambda *_a, **_kw: 0)
    monkeypatch.setattr(mod, "transactions_to_beancount", lambda *_a, **_kw: "BEAN")

    result = mod.parse_downloaded_bills_to_beancount(
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        enable_cc_digital_dedup=True,
        enable_refund_dedup=True,
    )

    assert result["beancount_text"] == "BEAN"
    assert str(result["output_path"]).endswith("_deduped.bean")

    stats = result["stats"]
    assert stats["txns_before_dedup"] == 4
    assert stats["cc_digital_removed"] == 1
    assert stats["refund_pairs_removed"] == 2
    assert stats["txns_total"] == 1
    details = result["details"]
    assert len(details["cc_wechat_alipay_removed"]) == 1
    assert len(details["refund_pairs_removed"]) == 1
