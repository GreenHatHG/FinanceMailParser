from typing import List, Dict, Optional
import logging

from bs4 import BeautifulSoup

from models.txn import Transaction
from statement_parsers import is_skip_transaction
from utils.clean_amount import clean_amount
from models.source import TransactionSource
from utils.filter_transactions import filter_matching_refunds

logger = logging.getLogger(__name__)


def parse_ccb_statement(file_path: str) -> List[Transaction]:
    """
    解析建设银行信用卡 HTML 对账单文件

    Args:
        file_path: HTML 文件路径

    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'lxml')

        all_transactions_info = []  # Store all transaction information

        # Extract all transaction records
        for row in soup.find_all("tr", style="font-size:12px;"):
            transaction_info = _extract_transaction_info(row)
            if not transaction_info:
                continue
            all_transactions_info.append(transaction_info)

        # Apply initial filters
        filtered_transactions_info = []
        for transaction_info in all_transactions_info:
            # Validate currency
            if transaction_info['currency'] != "CNY":
                logger.info(f"跳过非人民币交易: {transaction_info['description']} - 日期: {transaction_info['transaction_date']} - 金额: {transaction_info['amount']}")
                continue

            # Skip unnecessary transactions
            if is_skip_transaction(transaction_info['description']):
                logger.info(f"跳过不需要的交易: {transaction_info['description']} - 日期: {transaction_info['transaction_date']} - 金额: {transaction_info['amount']}")
                continue

            filtered_transactions_info.append(transaction_info)

        transactions = []
        for transaction_info in filtered_transactions_info:
            try:
                amount = float(clean_amount(transaction_info['amount']))
                txn = Transaction(
                    TransactionSource.CCB.value,
                    transaction_info['transaction_date'],
                    transaction_info['description'],
                    amount
                )
                transactions.append(txn)
            except ValueError as e:
                print(f"处理交易记录时出错: {str(e)}")
                continue

        transactions = filter_matching_refunds(transactions)

        return transactions

    except Exception as e:
        raise Exception(f"解析建设银行对账单失败: {str(e)}")


def _extract_transaction_info(row: BeautifulSoup) -> Optional[Dict[str, str]]:
    """
    从表格行提取交易信息

    Args:
        row: 表格行元素

    Returns:
        交易信息字典或None
    """
    columns = row.find_all("td")
    if len(columns) != 8:
        return None

    return {
        'transaction_date': columns[0].get_text(strip=True),
        'description': columns[3].get_text(strip=True),
        'currency': columns[4].get_text(strip=True),
        'amount': columns[5].get_text(strip=True)
    }
