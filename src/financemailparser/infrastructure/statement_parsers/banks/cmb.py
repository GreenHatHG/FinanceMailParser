from bs4 import BeautifulSoup
from typing import Callable, List, Optional
from datetime import datetime

from financemailparser.domain.models.txn import Transaction
from financemailparser.infrastructure.statement_parsers import format_date
from financemailparser.infrastructure.statement_parsers.clean_amount import clean_amount
from financemailparser.domain.services.date_filter import is_in_date_range
from financemailparser.domain.models.source import TransactionSource


def parse_cmb_statement(
    html_file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
) -> List[Transaction]:
    """
    解析招商银行信用卡 HTML 对账单文件

    Args:
        html_file_path: HTML 文件路径
        start_date: 开始日期，如果提供则只返回该日期之后的交易
        end_date: 结束日期，如果提供则只返回该日期之前的交易

    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(html_file_path, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file.read(), "html.parser")

        transactions = []
        for row in soup.find_all(id="fixBand15"):
            columns = row.find_all("div")
            if len(columns) < 4:
                continue

            # 提取交易信息
            transaction_info = {
                "date": columns[1].get_text(strip=True),
                "description": columns[2].get_text(strip=True),
                "amount": columns[3].get_text(strip=True),
            }

            # 跳过不需要的交易
            if skip_transaction and skip_transaction(transaction_info["description"]):
                continue

            try:
                txn_date_str = format_date(transaction_info["date"], "%m%d")
                if not is_in_date_range(txn_date_str, start_date, end_date):
                    continue

                # 创建交易记录
                txn = Transaction(
                    TransactionSource.CMB.value,
                    txn_date_str,
                    transaction_info["description"],
                    clean_amount(transaction_info["amount"]),
                )
                transactions.append(txn)

            except ValueError as e:
                print(f"处理交易记录时出错: {str(e)}")
                continue

        return transactions

    except Exception as e:
        raise Exception(f"解析招商银行对账单失败: {str(e)}")
