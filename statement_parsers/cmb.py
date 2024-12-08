from bs4 import BeautifulSoup
from typing import List

from models.txn import Transaction
from statement_parsers import is_skip_transaction, format_date
from utils.clean_amount import clean_amount


def parse_cmb_statement(html_file_path: str) -> List[Transaction]:
    """
    解析招商银行信用卡 HTML 对账单文件
    
    Args:
        html_file_path: HTML 文件路径
        
    Returns:
        Transaction 对象列表
    """
    try:
        # 读取并解析 HTML
        with open(html_file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file.read(), 'html.parser')

        transactions = []
        for row in soup.find_all(id="fixBand15"):
            columns = row.find_all('div')
            if len(columns) < 4:
                continue
                
            # 提取交易信息
            transaction_info = {
                'date': columns[1].get_text(strip=True),
                'description': columns[2].get_text(strip=True),
                'amount': columns[3].get_text(strip=True)
            }
            
            # 跳过不需要的交易
            if is_skip_transaction(transaction_info['description']):
                continue
                
            # 跳过特定商户
            if '消费分期-京东支付-网银在线' in transaction_info['description']:
                continue
                
            try:
                # 创建交易记录
                txn = Transaction(
                    "招商银行信用卡",
                    format_date(transaction_info['date'], '%m%d'),
                    transaction_info['description'],
                    clean_amount(transaction_info['amount'])
                )
                transactions.append(txn)
                
            except ValueError as e:
                print(f"处理交易记录时出错: {str(e)}")
                continue
                
        return transactions
        
    except Exception as e:
        raise Exception(f"解析招商银行对账单失败: {str(e)}")
