from bs4 import BeautifulSoup
from typing import List

from models.txn import Transaction
from statement_parsers import format_date, clean_amount, is_skip_transaction


def parse_abc_statement(file_path: str) -> List[Transaction]:
    """
    解析农业银行信用卡 HTML 对账单文件
    
    Args:
        file_path: HTML 文件路径
        
    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file.read(), 'html.parser')

        # 提取交易数据
        transactions = []
        for row in soup.find_all('div', {'id': 'fixBand10'}):
            cells = row.find_all('td')
            if len(cells) < 8:
                continue

            # 提取交易信息
            transaction_info = {
                'transaction_date': cells[2].get_text(strip=True),
                'transaction_type': cells[5].get_text(strip=True),
                'merchant_info': cells[6].get_text(strip=True),
                'amount': cells[8].get_text(strip=True)  # 使用入账金额
            }

            # 跳过不需要的交易
            if is_skip_transaction(transaction_info['merchant_info']):
                continue

            try:
                # 清理并检查金额
                amount = clean_amount(transaction_info['amount'])
                if float(amount) > 0:  # 跳过收入
                    continue

                # 创建交易记录
                txn = Transaction(
                    "农业银行信用卡",
                    format_date(transaction_info['transaction_date']),
                    f"{transaction_info['transaction_type']}-{transaction_info['merchant_info']}",
                    amount
                )
                transactions.append(txn)

            except ValueError as e:
                print(f"处理交易记录时出错: {str(e)}")
                continue

        return transactions

    except Exception as e:
        raise Exception(f"解析农业银行对账单失败: {str(e)}")
