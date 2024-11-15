from typing import List, Dict, Optional

from bs4 import BeautifulSoup

from models.txn import Transaction
from statement_parsers import is_skip_transaction, clean_amount


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

        transactions = []
        # 查找交易记录
        for row in soup.find_all("tr", style="font-size:12px;"):
            transaction_info = _extract_transaction_info(row)
            if not transaction_info:
                continue

            # 验证币种
            if transaction_info['currency'] != "CNY":
                print(f"跳过非人民币交易: {transaction_info['description']}")
                continue

            # 跳过不需要的交易
            if is_skip_transaction(transaction_info['description']):
                continue

            try:
                amount = float(clean_amount(transaction_info['amount']))

                # 跳过收入和退款配对的交易
                if amount < 0 or _has_matching_refund(transaction_info, soup):
                    continue

                # 创建交易记录
                txn = Transaction(
                    "建设银行信用卡",
                    transaction_info['transaction_date'],
                    transaction_info['description'],
                    str(amount)
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


def _has_matching_refund(transaction: Dict[str, str], soup: BeautifulSoup) -> bool:
    """
    检查是否存在匹配的退款交易
    
    Args:
        transaction: 当前交易信息
        soup: BeautifulSoup对象
        
    Returns:
        是否存在匹配的退款
    """
    amount = float(clean_amount(transaction['amount']))

    # 查找相同日期、描述但金额相反的交易
    for row in soup.find_all("tr", style="font-size:12px;"):
        refund_info = _extract_transaction_info(row)
        if not refund_info:
            continue

        if (refund_info['transaction_date'] == transaction['transaction_date'] and
                refund_info['description'] == transaction['description']):
            try:
                refund_amount = float(clean_amount(refund_info['amount']))
                if refund_amount == -amount:
                    return True
            except ValueError:
                continue

    return False
