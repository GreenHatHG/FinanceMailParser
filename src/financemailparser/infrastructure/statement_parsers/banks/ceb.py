from typing import Callable, List, Optional
from datetime import datetime

from bs4 import BeautifulSoup

from financemailparser.domain.models.txn import Transaction
from financemailparser.infrastructure.statement_parsers.clean_amount import clean_amount
from financemailparser.domain.services.date_filter import is_in_date_range
from financemailparser.domain.models.source import TransactionSource


def parse_ceb_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
) -> List[Transaction]:
    """
    解析光大银行信用卡 HTML 对账单文件

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

        # 查找人民币账户交易明细表格
        rmb_details = soup.find(
            "td", string=lambda x: x and "人民币账户交易明细" in str(x)
        )
        if not rmb_details:
            raise ValueError("未找到人民币账户交易明细")

        transactions: List[Transaction] = []
        transactions_table = _find_transactions_table(rmb_details)
        if not transactions_table:
            return transactions

        # 解析交易记录
        for row in transactions_table.find_all("tr")[1:]:  # 跳过表头
            cols = row.find_all("td")
            if len(cols) != 5:
                continue

            # 验证日期格式
            first_col = cols[0].text.strip()
            if len(first_col) != 10 or first_col.count("/") != 2:
                continue

            # 提取交易信息
            transaction_info = {
                "post_date": cols[1].text.strip(),
                "description": cols[3].text.strip(),
                "amount": cols[4].text.strip(),
            }

            # 跳过不需要的交易
            if skip_transaction and skip_transaction(transaction_info["description"]):
                continue

            try:
                txn_date_str = transaction_info["post_date"].replace("/", "-")
                if not is_in_date_range(txn_date_str, start_date, end_date):
                    continue

                # 创建交易记录
                txn = Transaction(
                    TransactionSource.CEB.value,
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
        raise Exception(f"解析光大银行对账单失败: {str(e)}")


def _find_transactions_table(rmb_details_td: BeautifulSoup) -> Optional[BeautifulSoup]:
    """
    查找交易明细表格

    Args:
        rmb_details_td: 包含"人民币账户交易明细"的td元素

    Returns:
        交易明细表格元素或None
    """
    account_table = rmb_details_td.find_parent("table")
    if not account_table:
        return None

    return account_table.find_next_sibling("table").find_next_sibling("table")
