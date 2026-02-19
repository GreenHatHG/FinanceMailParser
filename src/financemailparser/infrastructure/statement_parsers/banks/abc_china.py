"""ABC (Agricultural Bank of China) credit card statement parser."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, List, Optional

from bs4 import BeautifulSoup

from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.date_filter import is_in_date_range
from financemailparser.infrastructure.statement_parsers.clean_amount import clean_amount


def parse_abc_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
    skip_refund_filter: bool = False,
) -> List[Transaction]:
    """
    解析农业银行信用卡 HTML 对账单文件

    Args:
        file_path: HTML 文件路径
        start_date: 开始日期，如果提供则只返回该日期之后的交易
        end_date: 结束日期，如果提供则只返回该日期之前的交易

    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(file_path, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file.read(), "html.parser")

        transactions: List[Transaction] = []

        # ABC e-bill template (current): transaction details are rendered as plain <tr><td>...</td></tr>
        # with 6 columns:
        #   0) 交易日期 (YYMMDD)
        #   1) 入账日期 (YYMMDD)
        #   2) 卡号后四位
        #   3) 交易描述
        #   4) 交易金额/币种
        #   5) 入账金额/币种 (支出为-)
        #
        # Important: "支出为-" means expenses are negative in the statement, while this repo uses
        # "amount >= 0 as expense". So we flip the sign for ABC by negating the cleaned amount.
        txn_date_re = re.compile(r"^\d{6}$")
        supported_currency_markers = ("CNY", "RMB")

        def _format_yyMMdd_to_iso(date_str: str) -> str:
            if not txn_date_re.match(str(date_str or "")):
                raise ValueError(f"invalid ABC date: {date_str}")
            yy = int(date_str[:2])
            mm = int(date_str[2:4])
            dd = int(date_str[4:6])
            # ABC statement uses 2-digit year; for modern bills we map to 2000+yy.
            return f"{2000 + yy:04d}-{mm:02d}-{dd:02d}"

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) != 6:
                continue

            txn_date_raw = tds[0].get_text(strip=True)
            if not txn_date_re.match(txn_date_raw):
                continue

            desc = tds[3].get_text(strip=True)
            posting_amount_raw = tds[5].get_text(strip=True)
            if not any(
                m in posting_amount_raw.upper() for m in supported_currency_markers
            ):
                # Skip non-CNY records (or non-amount rows).
                continue

            if skip_transaction and skip_transaction(desc):
                continue

            try:
                txn_date_str = _format_yyMMdd_to_iso(txn_date_raw)
                if not is_in_date_range(txn_date_str, start_date, end_date):
                    continue

                posting_amount = float(clean_amount(posting_amount_raw))
                amount = -posting_amount

                transactions.append(
                    Transaction(
                        TransactionSource.ABC.value,
                        txn_date_str,
                        desc,
                        amount,
                    )
                )
            except ValueError:
                continue

        return transactions

    except Exception as e:
        raise Exception(f"解析农业银行对账单失败: {str(e)}")


if __name__ == "__main__":
    from financemailparser.shared.constants import EMAILS_DIR, EMAIL_HTML_FILENAME

    # 示例：把这里的文件夹名替换成你本地 emails/ 下实际存在的账单目录
    sample_html = (
        EMAILS_DIR / "20250206_中国农业银行金穗信用卡电子对账单" / EMAIL_HTML_FILENAME
    )
    parse_abc_statement(str(sample_html))
