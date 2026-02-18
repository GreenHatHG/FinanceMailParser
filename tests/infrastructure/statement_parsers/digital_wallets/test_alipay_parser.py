from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from financemailparser.domain.models.source import TransactionSource
from financemailparser.infrastructure.statement_parsers.digital_wallets.alipay import (
    parse_alipay_statement,
)


def _write_alipay_csv(path: Path, *, header_offset: int, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "交易时间",
        "交易分类",
        "交易对方",
        "对方账号",
        "商品说明",
        "收/支",
        "金额",
        "收/付款方式",
        "交易状态",
        "交易订单号",
        "商家订单号",
        "备注",
    ]

    filler_row = [""] * len(header)
    sheet_rows: list[list[str]] = [filler_row[:] for _ in range(header_offset)]
    sheet_rows.append(header)
    sheet_rows.extend(rows)

    df = pd.DataFrame(sheet_rows)
    df.to_csv(path, index=False, header=False, encoding="gbk")


def test_parse_alipay_statement_sets_sign_and_card_source(tmp_path: Path) -> None:
    # The parser uses ALIPAY_CSV_DEFAULTS.header_row == 22 (0-indexed).
    csv_path = tmp_path / "alipay.csv"
    _write_alipay_csv(
        csv_path,
        header_offset=22,
        rows=[
            [
                "2026-01-01 10:00:00",
                "c1",
                "A店",
                "acc",
                "咖啡",
                "支出",
                "12.34",
                "建行信用卡(1234)",
                "成功",
                "t1",
                "m1",
                "",
            ],
            [
                "2026-01-01 11:00:00",
                "c1",
                "A店",
                "acc",
                "退款",
                "收入",
                "12.34",
                "余额",
                "成功",
                "t2",
                "m2",
                "",
            ],
        ],
    )

    out = parse_alipay_statement(
        str(csv_path),
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        bank_alias_keywords={"CCB": ["建行"]},
    )

    assert len(out) == 2
    spend, income = out
    assert spend.source == TransactionSource.ALIPAY
    assert spend.amount == 12.34
    assert getattr(spend, "card_source") == TransactionSource.CCB

    assert income.source == TransactionSource.ALIPAY
    assert income.amount == -12.34
