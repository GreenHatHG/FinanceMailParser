import logging
from typing import Callable, List, Optional
from datetime import datetime

from bs4 import BeautifulSoup

from models.source import TransactionSource
from models.txn import Transaction
from utils.clean_amount import clean_amount
from utils.date_filter import is_in_date_range
from utils.filter_transactions import filter_matching_refunds

logger = logging.getLogger(__name__)


def parse_icbc_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
) -> List[Transaction]:
    """
    解析工商银行信用卡 HTML 对账单文件

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

        rows = soup.find_all("tr")
        transactions = []
        filtered_dates = []

        # 提取交易数据
        for row in rows:
            cols = row.find_all("td")
            if len(cols) != 7 or cols[5].text.strip() == "交易金额/币种":
                continue

            transaction_info = {
                "card_number": cols[0].text.strip(),
                "transaction_date": cols[1].text.strip(),
                "posting_date": cols[2].text.strip(),
                "transaction_type": cols[3].text.strip(),
                "merchant": cols[4].text.strip(),
                "transaction_amount": cols[5].text.strip(),
                "posting_amount": cols[6].text.strip(),
            }

            # 跳过不需要的交易
            if skip_transaction and skip_transaction(transaction_info["merchant"]):
                continue

            # 日期过滤
            try:
                if not is_in_date_range(
                    transaction_info["transaction_date"],
                    start_date,
                    end_date,
                    logger=logger,
                ):
                    filtered_dates.append(transaction_info["transaction_date"])
                    continue

                amount = float(clean_amount(transaction_info["transaction_amount"]))
                if "支出" in transaction_info["posting_amount"]:
                    amount = -amount

                txn = Transaction(
                    TransactionSource.ICBC.value,
                    transaction_info["transaction_date"],
                    transaction_info["merchant"],
                    amount,
                )
                transactions.append(txn)

            except ValueError as e:
                logger.error(f"处理交易记录时出错: {str(e)}", exc_info=True)
                continue

        # 打印过滤信息
        if filtered_dates:
            logger.debug(f"按日期过滤掉 {len(filtered_dates)} 条记录")

        transactions = filter_matching_refunds(transactions)

        for txn in transactions:
            txn.amount = abs(txn.amount)
        return transactions

    except Exception as e:
        raise Exception(f"解析工商银行对账单失败: {str(e)}")
