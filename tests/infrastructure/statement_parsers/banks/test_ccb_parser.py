from __future__ import annotations

from datetime import datetime
from pathlib import Path

from financemailparser.domain.models.source import TransactionSource
from financemailparser.infrastructure.statement_parsers.banks.ccb import (
    parse_ccb_statement,
)


def _write_html(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _row(*, date: str, desc: str, currency: str, amount: str) -> str:
    # ccb parser expects: <tr style="font-size:12px;"> with 8 <td>, and uses:
    # [0]=date, [3]=description, [4]=currency, [5]=amount.
    cells = [
        date,
        "c1",
        "c2",
        desc,
        currency,
        amount,
        "c6",
        "c7",
    ]
    return (
        '<tr style="font-size:12px;">'
        + "".join(f"<td>{c}</td>" for c in cells)
        + "</tr>"
    )


def test_parse_ccb_statement_extracts_transactions_and_filters(tmp_path: Path) -> None:
    html = (
        "<html><body><table>"
        + _row(date="2026-01-01", desc="Coffee", currency="CNY", amount="¥12.34")
        + _row(date="2026-01-02", desc="SkipMe", currency="CNY", amount="¥1.00")
        + _row(date="2026-01-03", desc="USD txn", currency="USD", amount="12.00")
        + "</table></body></html>"
    )
    file_path = tmp_path / "ccb.html"
    _write_html(file_path, html)

    out = parse_ccb_statement(
        str(file_path),
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        skip_transaction=lambda d: "SkipMe" in d,
    )

    assert len(out) == 1
    txn = out[0]
    assert txn.source == TransactionSource.CCB
    assert txn.date == "2026-01-01"
    assert txn.description == "Coffee"
    assert txn.amount == 12.34


def test_parse_ccb_statement_filters_matching_refunds(tmp_path: Path) -> None:
    html = (
        "<html><body><table>"
        + _row(date="2026-01-01", desc="X", currency="CNY", amount="¥10.00")
        + _row(date="2026-01-01", desc="X", currency="CNY", amount="存入¥10.00")
        + "</table></body></html>"
    )
    file_path = tmp_path / "ccb.html"
    _write_html(file_path, html)

    out = parse_ccb_statement(str(file_path))
    assert out == []
