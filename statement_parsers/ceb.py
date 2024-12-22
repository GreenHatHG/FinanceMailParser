from typing import List, Optional

from bs4 import BeautifulSoup

from models.txn import Transaction
from statement_parsers import is_skip_transaction
from utils.clean_amount import clean_amount
from models.source import TransactionSource


def parse_ceb_statement(file_path: str) -> List[Transaction]:
    """
    解析光大银行信用卡 HTML 对账单文件
    
    Args:
        file_path: HTML 文件路径
        
    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file.read(), 'html.parser')

        # 查找人民币账户交易明细表格
        rmb_details = soup.find('td', string=lambda x: x and '人民币账户交易明细' in str(x))
        if not rmb_details:
            raise ValueError("未找到人民币账户交易明细")

        transactions = []
        transactions_table = _find_transactions_table(rmb_details)
        if not transactions_table:
            return transactions

        # 解析交易记录
        for row in transactions_table.find_all('tr')[1:]:  # 跳过表头
            cols = row.find_all('td')
            if len(cols) != 5:
                continue

            # 验证日期格式
            first_col = cols[0].text.strip()
            if len(first_col) != 10 or first_col.count('/') != 2:
                continue

            # 提取交易信息
            transaction_info = {
                'post_date': cols[1].text.strip(),
                'description': cols[3].text.strip(),
                'amount': cols[4].text.strip()
            }

            # 跳过不需要的交易
            if is_skip_transaction(transaction_info['description']):
                continue

            try:
                # 创建交易记录
                txn = Transaction(
                    TransactionSource.CEB.value,
                    transaction_info['post_date'],
                    transaction_info['description'],
                    clean_amount(transaction_info['amount'])
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
    account_table = rmb_details_td.find_parent('table')
    if not account_table:
        return None

    return account_table.find_next_sibling('table').find_next_sibling('table')
