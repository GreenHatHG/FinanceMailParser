from typing import List, Dict, Tuple
import logging
from models.txn import Transaction

logger = logging.getLogger(__name__)


def filter_matching_refunds(transactions: List[Transaction]) -> List[Transaction]:
    """
    过滤掉具有匹配退款的交易。
    对于同一天相同描述的交易，将正数金额与负数金额一一配对，
    未配对的交易将被保留。

    Args:
        transactions: Transaction对象列表

    Returns:
        过滤后的Transaction对象列表
    """
    # 按日期和描述分组
    transaction_groups: Dict[Tuple[str, str], List[Transaction]] = {}
    for transaction in transactions:
        key = (transaction.date, transaction.description)
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
            if txn.amount > 0:
                positive_txns.append((txn.amount, txn))
            else:
                negative_txns.append((abs(txn.amount), txn))

        # 标记已匹配的交易
        matched_positive = set()
        matched_negative = set()

        # 匹配正负交易
        for i, (pos_amount, pos_txn) in enumerate(positive_txns):
            for j, (neg_amount, neg_txn) in enumerate(negative_txns):
                if (
                    j not in matched_negative
                    and i not in matched_positive
                    and pos_amount == neg_amount
                ):
                    matched_positive.add(i)
                    matched_negative.add(j)
                    logger.info(
                        f"跳过匹配退款的交易: {pos_txn.description} - 日期: {pos_txn.date} - 金额: {pos_amount}"
                    )
                    logger.info(
                        f"跳过匹配退款的交易: {neg_txn.description} - 日期: {neg_txn.date} - 金额: -{neg_amount}"
                    )
                    break

        # 添加未匹配的交易
        for i, (_, txn) in enumerate(positive_txns):
            if i not in matched_positive:
                filtered_transactions.append(txn)

        for j, (_, txn) in enumerate(negative_txns):
            if j not in matched_negative:
                filtered_transactions.append(txn)

    return filtered_transactions
