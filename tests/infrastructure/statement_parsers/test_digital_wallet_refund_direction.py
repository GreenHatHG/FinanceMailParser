from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from financemailparser.infrastructure.statement_parsers.digital_wallets.alipay import (
    parse_alipay_statement,
)
from financemailparser.infrastructure.statement_parsers.digital_wallets.wechat import (
    parse_wechat_statement,
)


_ALIPAY_COLUMNS_WITH_EXTRA = (
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
    "EXTRA",  # dropped by parser
)


def _write_alipay_csv_like_export(path: Path, *, rows: list[dict[str, str]]) -> None:
    """
    Write a minimal Alipay CSV that matches parser expectations:
    - header at 23rd line (0-index = 22)
    - GBK encoding
    - a trailing extra column which the parser drops
    """
    empty_prefix_line = ",".join([""] * len(_ALIPAY_COLUMNS_WITH_EXTRA))
    prefix = "\n".join([empty_prefix_line] * 22) + "\n"
    header = ",".join(_ALIPAY_COLUMNS_WITH_EXTRA) + "\n"

    def row_to_csv_line(r: dict[str, str]) -> str:
        values = [str(r.get(col, "")) for col in _ALIPAY_COLUMNS_WITH_EXTRA]
        # No quoting for simplicity; our test data avoids commas in fields.
        return ",".join(values) + "\n"

    body = "".join([row_to_csv_line(r) for r in rows])
    path.write_text(prefix + header + body, encoding="gbk")


def test_alipay_refund_is_forced_to_negative_even_when_in_out_not_income(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "alipay.csv"
    _write_alipay_csv_like_export(
        csv_path,
        rows=[
            {
                "交易时间": "2026-02-09 15:52:23",
                "交易分类": "交易",
                "交易对方": "x",
                "对方账号": "y",
                "商品说明": "退款-测试商品",
                "收/支": "不计收支",
                "金额": "69.90",
                "收/付款方式": "余额宝",
                "交易状态": "退款成功",
                "交易订单号": "oid",
                "商家订单号": "mid",
                "备注": "",
                "EXTRA": "",
            },
            {
                "交易时间": "2026-02-09 19:33:30",
                "交易分类": "交易",
                "交易对方": "x",
                "对方账号": "y",
                "商品说明": "普通支出",
                "收/支": "支出",
                "金额": "10.00",
                "收/付款方式": "余额宝",
                "交易状态": "交易成功",
                "交易订单号": "oid2",
                "商家订单号": "mid2",
                "备注": "",
                "EXTRA": "",
            },
        ],
    )

    txns = parse_alipay_statement(str(csv_path))
    assert len(txns) == 2
    refund, expense = txns[0], txns[1]
    assert float(refund.amount) == -69.90
    assert float(expense.amount) == 10.00


def test_wechat_refund_is_forced_to_negative_even_when_in_out_not_income(
    tmp_path: Path,
) -> None:
    xlsx_path = tmp_path / "wechat.xlsx"
    df = pd.DataFrame(
        [
            {
                "交易时间": "2026-01-02 10:00:00",
                "交易类型": "退款",
                "交易对方": "商户A",
                "商品": "退款-测试商品",
                "收/支": "不计收支",
                "金额(元)": "¥69.90",
                "支付方式": "零钱",
                "当前状态": "退款成功",
                "交易单号": "t1",
                "商户单号": "m1",
                "备注": "",
            },
            {
                "交易时间": "2026-01-02 11:00:00",
                "交易类型": "消费",
                "交易对方": "商户B",
                "商品": "普通支出",
                "收/支": "支出",
                "金额(元)": "¥10.00",
                "支付方式": "零钱",
                "当前状态": "交易成功",
                "交易单号": "t2",
                "商户单号": "m2",
                "备注": "",
            },
        ]
    )

    # The parser expects the header at row 17 (0-index header=16).
    df.to_excel(xlsx_path, index=False, startrow=16, engine="openpyxl")

    txns = parse_wechat_statement(
        str(xlsx_path),
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
    )
    assert len(txns) == 2
    refund, expense = txns[0], txns[1]
    assert float(refund.amount) == -69.90
    assert float(expense.amount) == 10.00
