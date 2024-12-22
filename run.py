import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
import logging
from pathlib import Path

from data_source.qq_email import QQEmailParser
from data_source.qq_email.email_processor import save_email_content
from data_source.qq_email.utils import create_storage_structure
from statement_parsers.parse import parse_statement_email
from utils.csv_writer import CSVWriter
from utils.logger import set_global_log_level
from models.txn import Transaction, DigitalPaymentTransaction
from models.source import TransactionSource  # 添加导入语句

logger = logging.getLogger(__name__)

# Constants for transaction categorization
TRANSPORT_KEYWORDS = [
    '12306铁路一卡通-银联无卡自助消费',
    '（特约）龙支付清算户',
    '上海哈啰普惠科技有限公司',
    '北京公交',
    '昌32路',
    '北京公共交通',
    '北京轨道交通',
    '地铁',
    '昌19'
]

MEAL_KEYWORDS = [
    '麦当劳',
    '公司餐厅消费',
    '拉扎斯',
    '美团平台商户',
    '深圳美团科技有限公司',
    '饿了么',
    '多点',
    '盒马',
    '星巴克',
    '海底捞',
    '蜜雪冰城',
    '索迪斯',
    '北京总部'
]

def get_statement_period(year: Optional[int] = None, month: Optional[int] = None, statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取账单统计期间的日期范围
    
    Args:
        year: 年份，如果为None则使用当前年份
        month: 月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
        
    Returns:
        开始日期和结束日期的元组，表示账单统计的日期范围
        例如：10月份的账单统计期间为10.6-11.5
    """
    today = datetime.now()
    
    if year is None and month is None:
        # 根据当前日期和账单日判断应该获取哪个月的账单
        if today.day >= statement_day:
            # 如果当前日期已过账单日，获取上月账单
            start_month = today.month - 1 if today.month > 1 else 12
            start_year = today.year if today.month > 1 else today.year - 1
        else:
            # 如果当前日期未到账单日，获取上上月账单
            if today.month <= 2:
                start_month = 10 + today.month
                start_year = today.year - 1
            else:
                start_month = today.month - 2
                start_year = today.year
    else:
        start_month = month if month is not None else today.month
        start_year = year if year is not None else today.year

    # 计算账单统计开始日期（本月6号）
    start_date = datetime(start_year, start_month, statement_day + 1)
    
    # 计算账单统计结束日期（下月5号）
    if start_month == 12:
        end_month = 1
        end_year = start_year + 1
    else:
        end_month = start_month + 1
        end_year = start_year
    
    end_date = datetime(end_year, end_month, statement_day)

    logger.info(f"账单统计期间: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
    return start_date, end_date

def get_email_search_period(statement_year: Optional[int] = None, statement_month: Optional[int] = None, statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取邮件搜索的日期范围
    
    Args:
        statement_year: 账单年份，如果为None则使用当前年份
        statement_month: 账单月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
        
    Returns:
        开始日期和结束日期的元组，表示邮件搜索的日期范围
        例如：10月份的账单（统计期间为10.6-11.5）会在11.6-12.5期间发送
    """
    # 获取账单统计期间
    statement_start, statement_end = get_statement_period(statement_year, statement_month, statement_day)
    
    # 邮件搜索开始日期为账单统计结束日期的第二天
    email_start = statement_end + timedelta(days=1)
    
    # 邮件搜索结束日期为下个月的账单日
    if email_start.month == 12:
        email_end_month = 1
        email_end_year = email_start.year + 1
    else:
        email_end_month = email_start.month + 1
        email_end_year = email_start.year
        
    email_end = datetime(email_end_year, email_end_month, statement_day)
    
    logger.info(f"邮件搜索期间: {email_start.strftime('%Y-%m-%d')} 到 {email_end.strftime('%Y-%m-%d')}")
    return email_start, email_end

def print_transaction_stats(transactions: List[Transaction]) -> None:
    """
    打印交易记录的统计信息
    
    Args:
        transactions: 交易记录列表
    """
    if not transactions:
        logger.info("未找到任何交易记录")
        return
        
    total_amount = sum(txn.amount for txn in transactions)
    logger.info(f"处理完成，共解析 {len(transactions)} 条交易记录")
    logger.info(f"总金额: ¥{total_amount:.2f}")
    
    # 按银行分类统计
    bank_stats = {}
    bank_transactions = {}  # 新增：存储每个银行的交易记录
    for txn in transactions:
        bank = txn.source
        if bank not in bank_stats:
            bank_stats[bank] = {'count': 0, 'amount': 0}
            bank_transactions[bank] = []  # 新增：初始化银行交易列表
        bank_stats[bank]['count'] += 1
        bank_stats[bank]['amount'] += txn.amount
        bank_transactions[bank].append(txn)  # 新增：添加交易到对应银行
    
    logger.info("\n按银行统计:")
    for bank, stats in bank_stats.items():
        logger.info(f"{bank}: {stats['count']}笔交易, 总金额 ¥{stats['amount']:.2f}")
        # 新印每个银行的详细交易记录
        logger.debug(f"\n{bank} 的交易明细:")
        for txn in bank_transactions[bank]:
            logger.debug(f"  - 日期: {txn.date}, 描述: {txn.description}, 金额: ¥{txn.amount:.2f}")


def download_emails(year: Optional[int] = None, 
                   month: Optional[int] = None, 
                   statement_day: int = 5,
                   log_level: str = 'INFO',
                   alipay_pwd: Optional[str] = None,
                   wechat_pwd: Optional[str] = None) -> None:
    """
    从QQ邮箱下载信用卡账单、支付宝账单和微信支付账单
    
    Args:
        year: 年份
        month: 月份
        statement_day: 账单日
        log_level: 日志级别
        alipay_pwd: 支付宝账单解压密码
        wechat_pwd: 微信账单解压密码
    """
    # 设置全局日志级别
    set_global_log_level(log_level)
    logger.info("开始下载邮件...")
    
    # 创建解析器实例
    parser = QQEmailParser(os.getenv('QQ_EMAIL'), os.getenv('QQ_EMAIL_AUTH_CODE'))

    if not parser.login():
        logger.error("登录失败，程序退出")
        return

    try:
        email_dir = create_storage_structure()

        # 获取信用卡账单的日期范围（使用邮件搜索期间）
        start_date, end_date = get_email_search_period(year, month, statement_day)
        
        # 分别处理不同类型的账单
        # 1. 获取信用卡账单（使用日期范围）
        credit_card_emails = parser.get_email_list(start_date, end_date)
        saved_counts = {'credit_card': 0, 'alipay': 0, 'wechat': 0}
        
        for email_data in credit_card_emails:
            if parser.is_credit_card_statement(email_data):
                date_str = email_data['date'].strftime('%Y%m%d')
                safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
                email_folder = email_dir / f"{date_str}_{safe_subject}"
                save_email_content(email_folder, email_data, email_data['raw_message'])
                saved_counts['credit_card'] += 1

        # 2. 获取支付宝账单（直接下载附件）
        alipay_emails = parser.get_latest_bill_emails('alipay')
        alipay_dir = email_dir / 'alipay'
        alipay_dir.mkdir(exist_ok=True)
        
        for email_data in alipay_emails:
            saved_files = parser.save_bill_attachments(email_data, alipay_dir)
            if saved_files:
                logger.info(f"已保存支付宝账单附件: {', '.join(saved_files)}")
                # 尝试解压每个ZIP文件
                for file_path in saved_files:
                    if file_path.lower().endswith('.zip'):
                        extract_dir = alipay_dir / Path(file_path).stem
                        if parser.extract_zip_file(file_path, extract_dir, alipay_pwd):
                            saved_counts['alipay'] += 1

        # 3. 获取微信支付账单（下载并解压）
        wechat_emails = parser.get_latest_bill_emails('wechat')
        wechat_dir = email_dir / 'wechat'
        wechat_dir.mkdir(exist_ok=True)
        
        for email_data in wechat_emails:
            download_link = parser.extract_wechat_download_link(email_data)
            if download_link:
                logger.info(f"找到微信账单下载链接，开始下载...")
                saved_file = parser.download_wechat_bill(download_link, wechat_dir)
                if saved_file:
                    # 解压下载的文件
                    extract_dir = wechat_dir / Path(saved_file).stem
                    if parser.extract_zip_file(saved_file, extract_dir, wechat_pwd):
                        saved_counts['wechat'] += 1
                        logger.info(f"已成功下载并解压微信账单文件")

        # 打印统计信息
        logger.info("\n下载完成统计:")
        logger.info(f"- 信用卡账单: {saved_counts['credit_card']} 封")
        logger.info(f"- 支付宝账单: {saved_counts['alipay']} 个文件")
        logger.info(f"- 微信支付账单: {saved_counts['wechat']} 个文件")

    except Exception as e:
        logger.error(f"下载邮件时出错: {str(e)}", exc_info=True)
    finally:
        parser.close()


def merge_transaction_descriptions(credit_card_transactions: List[Transaction], 
                                digital_payment_transactions: List[Transaction]) -> List[Transaction]:
    """合并信用卡交易和数字支付交易的描述"""
    logger.info("开始合并交易描述...")
    
    # 将数字支付交易按日期、金额和关联的信用卡建立索引
    dp_txns_index = {}
    for dp_txn in digital_payment_transactions:
        if isinstance(dp_txn, DigitalPaymentTransaction) and dp_txn.card_source:  # 检查类型和卡信息
            key = (dp_txn.date, dp_txn.amount, dp_txn.card_source)
            if key not in dp_txns_index:
                dp_txns_index[key] = []
            dp_txns_index[key].append(dp_txn)
    
    matched_count = 0
    matched_dp_txns = set()
    
    for cc_txn in credit_card_transactions:
        key = (cc_txn.date, cc_txn.amount, cc_txn.source)
        
        if key in dp_txns_index:
            for dp_txn in dp_txns_index[key]:
                if dp_txn not in matched_dp_txns:
                    logger.debug(f"\n找到匹配的交易:")
                    logger.debug(f"  信用卡: {cc_txn.date} | {cc_txn.description} | ¥{cc_txn.amount:.2f} | {cc_txn.source.value}")
                    logger.debug(f"  {dp_txn.source}: {dp_txn.date} | {dp_txn.description} | ¥{dp_txn.amount:.2f} | 支付方式: {dp_txn.card_source}")
                    
                    cc_desc_len = len(cc_txn.description.strip())
                    dp_desc_len = len(dp_txn.description.strip())
                    
                    if cc_desc_len >= dp_desc_len:
                        final_desc = cc_txn.description
                    else:
                        final_desc = dp_txn.description
                    
                    cc_txn.description = final_desc
                    matched_dp_txns.add(dp_txn)
                    matched_count += 1
                    break
    
    # 过滤掉已匹配的数字支付交易
    unmatched_dp_txns = [txn for txn in digital_payment_transactions if txn not in matched_dp_txns]
    all_transactions = credit_card_transactions + unmatched_dp_txns
    
    logger.info(f"\n合并完成:")
    logger.info(f"  - 成功匹配并合并: {matched_count} 条交易")
    logger.info(f"  - 已移除的重复数字支付交易: {len(matched_dp_txns)} 条")
    logger.info(f"  - 未匹配的数字支付交易: {len(unmatched_dp_txns)} 条")
    logger.info(f"  - 最终交易总数: {len(all_transactions)} 条")
    
    return all_transactions


def parse_saved_emails(log_level: str = 'INFO', year: Optional[int] = None, month: Optional[int] = None, statement_day: int = 5) -> None:
    """
    第二步：解析已保存的邮件
    
    Args:
        log_level: 日志级别
        year: 年份，如果为None则使用当前年份
        month: 月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
    """
    # 设置全局日志级别
    set_global_log_level(log_level)
    logger.info("开始解析已保存的邮件...")
    
    try:
        # 获取emails目录
        email_dir = Path("emails")
        if not email_dir.exists():
            logger.error("未找到emails目录，请先运行download命令下载邮件")
            return
            
        # 获取账单日期范围
        statement_period = get_statement_period(year, month, statement_day)  # 用于微信和支付宝账单
        email_period = get_email_search_period(year, month, statement_day)  # 用于信用卡账单
        
        # 遍历所有邮件文件夹
        all_transactions = []
        digital_payment_transactions = []  # 存储支付宝和微信的交易记录
        credit_card_transactions = []  # 存储信用卡的交易记录
        
        for email_folder in email_dir.iterdir():
            if not email_folder.is_dir():
                continue
                
            try:
                # 解析账单，对于微信和支付宝使用账单统计期间，对于信用卡使用邮件搜索期间
                if email_folder.name in ['alipay', 'wechat']:
                    transactions = parse_statement_email(email_folder, *statement_period)
                else:
                    # 修改这里，为ICBC使用statement_period
                    if '工商银行' in email_folder.name.lower():
                        transactions = parse_statement_email(email_folder, *statement_period)
                    else:
                        transactions = parse_statement_email(email_folder, *email_period)
                    
                if transactions:
                    if any(txn.source in [TransactionSource.ALIPAY, TransactionSource.WECHAT] for txn in transactions):
                        digital_payment_transactions.extend(transactions)
                    else:
                        credit_card_transactions.extend(transactions)
                    logger.info(f"成功解析 {email_folder.name} 中的 {len(transactions)} 条交易记录")
            except Exception as e:
                logger.error(f"解析 {email_folder.name} 时出错: {str(e)}")
                continue

        # 使用新的合并函数
        all_transactions = merge_transaction_descriptions(
            credit_card_transactions,
            digital_payment_transactions
        )
        
        # 输出统计信息
        print_transaction_stats(all_transactions)
        to_csv(all_transactions)
    except Exception as e:
        logger.error(f"解析邮件时出错: {str(e)}", exc_info=True)


def categorize_transaction(transaction: Transaction) -> str:
    """
    Categorize a transaction based on its description and amount.
    
    Args:
        transaction: Transaction object to categorize
        
    Returns:
        str: Category name
    """
    if any(keyword in transaction.description for keyword in TRANSPORT_KEYWORDS):
        return "交通"
    
    if any(keyword in transaction.description for keyword in MEAL_KEYWORDS):
        return "三餐"
    
    return "待分类"

def to_csv(transactions: List[Transaction]) -> None:
    """
    Process transactions and write them to CSV file.
    
    Args:
        transactions: List of Transaction objects to process
    """
    # Filter out invalid transactions
    valid_transactions = [
        txn for txn in transactions 
        if txn.amount != 0.01 and not (-1 < txn.amount <= 0)
    ]
    
    # Sort and categorize transactions
    sorted_transactions = sorted(valid_transactions, key=lambda x: x.date)
    for transaction in sorted_transactions:
        transaction.category = categorize_transaction(transaction)
        print(transaction.to_dict())

    # Write to CSV
    csv_writer = CSVWriter("transactions.csv", Transaction.get_fieldnames())
    csv_writer.write_transactions(sorted_transactions)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='信用卡账单解析工具')
    parser.add_argument('command', choices=['download', 'parse'], 
                       help='执行的命令: download(下载邮件) 或 parse(解析已保存的邮件)')
    parser.add_argument('--year', type=int, help='指定年份，默认为当前年份')
    parser.add_argument('--month', type=int, help='指定月份，默认为上个月')
    parser.add_argument('--statement-day', type=int, default=5, help='账单日，默认为5号')
    parser.add_argument('--log-level', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       default='INFO',
                       help='设置日志级别，默认为INFO')
    parser.add_argument('--alipay-pwd', help='支付宝账单解压密码')
    parser.add_argument('--wechat-pwd', help='微信账单解压密码')
    
    args = parser.parse_args()
    
    # 验证月份
    if args.month is not None and not (1 <= args.month <= 12):
        parser.error('月份必须在1到12之间')
    
    # 验证账单日
    if not (1 <= args.statement_day <= 31):
        parser.error('账单日必须在1到31之间')
    
    if args.command == 'download':
        download_emails(args.year, args.month, args.statement_day, args.log_level,
                       args.alipay_pwd, args.wechat_pwd)
    elif args.command == 'parse':
        parse_saved_emails(args.log_level, args.year, args.month, args.statement_day) 