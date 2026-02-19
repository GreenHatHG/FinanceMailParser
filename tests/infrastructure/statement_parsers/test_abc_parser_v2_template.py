from __future__ import annotations

from datetime import datetime
from pathlib import Path

from financemailparser.infrastructure.statement_parsers.banks.abc_china import (
    parse_abc_statement,
)

ABC_UNIONPAY_CREDIT_DESC = "银联入账 某人/付款尾号:2389/"


def test_abc_new_template_parses_rows_and_flips_signs(tmp_path: Path) -> None:
    html_path = tmp_path / "abc.html"
    html_path.write_text(
        """
        <html>
          <body>
            <table>
              <tr>
                <td>交易日期</td><td>入账日期</td><td>卡号后四位</td>
                <td>交易描述</td><td>交易金额/币种</td><td>入账金额/币种(支出为-)</td>
              </tr>
              <tr>
                <td>251207</td><td>251207</td><td>6139</td>
                <td>{abc_unionpay_credit_desc}</td><td>109.12/CNY</td><td>109.12/CNY</td>
              </tr>
              <tr>
                <td>251230</td><td>251230</td><td>6139</td>
                <td>网上消费 美团支付，美团老街小卷粉烧烤</td><td>15.00/CNY</td><td>-15.00/CNY</td>
              </tr>
            </table>
          </body>
        </html>
        """.strip().format(
            abc_unionpay_credit_desc=ABC_UNIONPAY_CREDIT_DESC,
        ),
        encoding="utf-8",
    )

    txns = parse_abc_statement(
        str(html_path),
        start_date=datetime(2025, 12, 1),
        end_date=datetime(2025, 12, 31),
    )
    assert len(txns) == 2

    by_desc = {t.description: float(t.amount) for t in txns}
    assert by_desc[ABC_UNIONPAY_CREDIT_DESC] == -109.12
    assert by_desc["网上消费 美团支付，美团老街小卷粉烧烤"] == 15.00
