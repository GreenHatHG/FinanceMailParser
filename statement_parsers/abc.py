from bs4 import BeautifulSoup
from typing import Callable, List, Optional
from datetime import datetime

from models.txn import Transaction
from statement_parsers import format_date
from utils.clean_amount import clean_amount
from utils.date_filter import is_in_date_range
from models.source import TransactionSource


def parse_abc_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
) -> List[Transaction]:
    """
    解析农业银行信用卡 HTML 对账单文件

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

        # 提取交易数据
        transactions = []
        for row in soup.find_all("div", {"id": "fixBand10"}):
            cells = row.find_all("td")
            if len(cells) <= 8:
                continue

            # 提取交易信息
            transaction_info = {
                "transaction_date": cells[2].get_text(strip=True),
                "transaction_type": cells[5].get_text(strip=True),
                "merchant_info": cells[6].get_text(strip=True),
                "amount": cells[8].get_text(strip=True),  # 使用入账金额
            }

            # 跳过不需要的交易
            if skip_transaction and skip_transaction(transaction_info["merchant_info"]):
                continue

            try:
                txn_date_str = format_date(transaction_info["transaction_date"])
                if not is_in_date_range(txn_date_str, start_date, end_date):
                    continue

                # 清理并检查金额
                amount = clean_amount(transaction_info["amount"])
                if float(amount) > 0:  # 跳过收入
                    continue

                # 创建交易记录
                txn = Transaction(
                    TransactionSource.ABC.value,
                    txn_date_str,
                    f"{transaction_info['transaction_type']}-{transaction_info['merchant_info']}",
                    -1 * float(amount),
                )
                transactions.append(txn)

            except ValueError as e:
                print(f"处理交易记录时出错: {str(e)}")
                continue

        return transactions

    except Exception as e:
        raise Exception(f"解析农业银行对账单失败: {str(e)}")


if __name__ == "__main__":
    from constants import EMAILS_DIR, EMAIL_HTML_FILENAME

    # 示例：把这里的文件夹名替换成你本地 emails/ 下实际存在的账单目录
    sample_html = (
        EMAILS_DIR / "20250206_中国农业银行金穗信用卡电子对账单" / EMAIL_HTML_FILENAME
    )
    parse_abc_statement(str(sample_html))
