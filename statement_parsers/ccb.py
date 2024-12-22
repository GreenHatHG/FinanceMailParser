from typing import List, Dict, Optional
import logging

from bs4 import BeautifulSoup

from models.txn import Transaction
from statement_parsers import is_skip_transaction
from utils.clean_amount import clean_amount
from models.source import TransactionSource

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

        # Apply final filter to remove transactions with matching refunds
        final_transactions_info = _filter_matching_refunds(filtered_transactions_info)

        transactions = []
        for transaction_info in final_transactions_info:
            try:
                amount = float(clean_amount(transaction_info['amount']))

                # Create transaction record
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


def _filter_matching_refunds(filtered_transactions_info: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    过滤掉具有匹配退款的交易。
    对于同一天相同描述的交易，将正数金额与负数金额一一配对，
    未配对的交易将被保留。

    Args:
        filtered_transactions_info: 已过滤的交易信息列表

    Returns:
        过滤后的交易信息列表
    """
    # 按日期和描述分组
    transaction_groups = {}
    for transaction in filtered_transactions_info:
        key = (transaction['transaction_date'], transaction['description'])
        if key not in transaction_groups:
            transaction_groups[key] = []
        transaction_groups[key].append(transaction)

    filtered_transactions = []

    # 处理每个分组
    for transactions in transaction_groups.values():
        # 将交易分为正数和负数两组
        positive_txns = []
        negative_txns = []

        for txn in transactions:
            amount = float(clean_amount(txn['amount']))
            if amount > 0:
                positive_txns.append((amount, txn))
            else:
                negative_txns.append((abs(amount), txn))

        # 标记已匹配的交易
        matched_positive = set()
        matched_negative = set()

        # 匹配正负交易
        for i, (pos_amount, pos_txn) in enumerate(positive_txns):
            for j, (neg_amount, neg_txn) in enumerate(negative_txns):
                if j not in matched_negative and i not in matched_positive and pos_amount == neg_amount:
                    matched_positive.add(i)
                    matched_negative.add(j)
                    logger.info(f"跳过匹配退款的交易: {pos_txn['description']} - 日期: {pos_txn['transaction_date']} - 金额: {pos_amount}")
                    logger.info(f"跳过匹配退款的交易: {neg_txn['description']} - 日期: {neg_txn['transaction_date']} - 金额: -{neg_amount}")
                    break

        # 添加未匹配的交易
        for i, (_, txn) in enumerate(positive_txns):
            if i not in matched_positive:
                filtered_transactions.append(txn)

        for j, (_, txn) in enumerate(negative_txns):
            if j not in matched_negative:
                filtered_transactions.append(txn)

    return filtered_transactions
