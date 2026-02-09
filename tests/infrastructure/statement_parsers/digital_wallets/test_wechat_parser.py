from __future__ import annotations

from datetime import datetime
from pathlib import Path

from financemailparser.domain.models.source import TransactionSource
from financemailparser.infrastructure.statement_parsers.digital_wallets.wechat import (
    parse_wechat_statement,
)


def _write_wechat_csv(path: Path, *, header_offset: int, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    dummy_lines = ["dummy\n" for _ in range(header_offset)]
    header = "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
    data_lines = [",".join(r) + "\n" for r in rows]
    path.write_text(
        "".join(dummy_lines) + header + "".join(data_lines), encoding="utf-8"
    )


def test_parse_wechat_statement_parses_and_filters_and_sets_card_source(
    tmp_path: Path,
) -> None:
    # The parser uses WECHAT_CSV_DEFAULTS.header_row == 16
    csv_path = tmp_path / "wechat.csv"
    _write_wechat_csv(
        csv_path,
        header_offset=16,
        rows=[
            [
                "2026-01-01 10:00:00",
                "扫码",
                "A店",
                "咖啡",
                "支出",
                "¥12.34",
                "建行信用卡(1234)",
                "成功",
                "t1",
                "m1",
                "",
            ],
            [
                "2026-01-03 10:00:00",
                "扫码",
                "B店",
                "跳过",
                "支出",
                "¥1.00",
                "零钱",
                "成功",
                "t2",
                "m2",
                "",
            ],
        ],
    )

    out = parse_wechat_statement(
        str(csv_path),
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        skip_transaction=lambda d: "跳过" in d,
        bank_alias_keywords={"CCB": ["建行"]},
    )

    assert len(out) == 1
    txn = out[0]
    assert txn.source == TransactionSource.WECHAT
    assert txn.date == "2026-01-01"
    assert txn.description == "咖啡-扫码-A店"
    assert txn.amount == 12.34
    assert getattr(txn, "card_source") == TransactionSource.CCB
