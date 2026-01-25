import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
import logging
from pathlib import Path

from constants import EMAILS_DIR, TRANSACTIONS_CSV
from data_source.qq_email import QQEmailParser, QQEmailConfigManager
from data_source.qq_email.email_processor import save_email_content
from data_source.qq_email.utils import create_storage_structure
from statement_parsers.parse import parse_statement_email, find_csv_file
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
        # 如果指定了月份但没指定年份，需要根据月份判断年份
        if year is None:
            if month > today.month:
                start_year = today.year - 1  # 如果指定月份大于当前月份，说明是去年的账单
            else:
                start_year = today.year
        else:
            start_year = year

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
    return start_date, end_date

def get_email_search_period(statement_year: Optional[int] = None, statement_month: Optional[int] = None, statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取邮件搜索的日期范围
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
    return email_start, email_end

def get_extended_email_search_period(statement_year: Optional[int] = None, 
                                   statement_month: Optional[int] = None, 
                                   statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取扩展的邮件搜索日期范围，包含上一个账单周期
    """
    # 获取当前账单周期的搜索期间
    current_start, current_end = get_email_search_period(statement_year, statement_month, statement_day)
    
    # 获取上一个账单周期的搜索期间
    if statement_month == 1:
        prev_year = statement_year - 1 if statement_year else None
        prev_month = 12
    else:
        prev_year = statement_year
        prev_month = statement_month - 1 if statement_month else None
        
    prev_start, _ = get_email_search_period(prev_year, prev_month, statement_day)
    return prev_start, current_end

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
    """
    # 设置全局日志级别
    set_global_log_level(log_level)
    logger.info("开始下载邮件...")
    
    # 获取账单统计期间
    statement_start, statement_end = get_statement_period(year, month, statement_day)
    logger.info(f"账单统计期间: {statement_start.strftime('%Y-%m-%d')} 到 {statement_end.strftime('%Y-%m-%d')}")
    
    # 获取扩展的邮件搜索期间（用于信用卡账单）
    extended_start, extended_end = get_extended_email_search_period(year, month, statement_day)
    logger.debug(f"信用卡账单搜索期间: {extended_start.strftime('%Y-%m-%d')} 到 {extended_end.strftime('%Y-%m-%d')}")

    # 创建解析器实例（支持从配置文件读取）
    qq_config_manager = QQEmailConfigManager()
    email, password = qq_config_manager.get_email_config()

    if not email or not password:
        logger.error("未配置邮箱信息，请设置环境变量或使用 UI 配置")
        logger.error("环境变量：QQ_EMAIL 和 QQ_EMAIL_AUTH_CODE")
        logger.error("或运行：streamlit run ui/app.py 进行配置")
        return

    parser = QQEmailParser(email, password)

    if not parser.login():
        logger.error("登录失败，程序退出")
        return

    try:
        email_dir = create_storage_structure()
        
        # 检查支付宝账单是否已存在
        alipay_dir = email_dir / 'alipay'
        alipay_exists = False
        if alipay_dir.exists():
            for subdir in alipay_dir.iterdir():
                if subdir.is_dir():
                    csv_file = find_csv_file(subdir)
                    if csv_file:
                        logger.info(f"找到已存在的支付宝账单: {csv_file.name}")
                        alipay_exists = True
                        break
        
        # 检查微信账单是否已存在
        wechat_dir = email_dir / 'wechat'
        wechat_exists = False
        if wechat_dir.exists():
            for subdir in wechat_dir.iterdir():
                if subdir.is_dir():
                    csv_file = find_csv_file(subdir)
                    if csv_file:
                        logger.info(f"找到已存在的微信账单: {csv_file.name}")
                        wechat_exists = True
                        break

        # 分别处理不同类型的账单
        # 1. 获取信用卡账单（使用扩展日期范围）
        credit_card_emails = parser.get_email_list(extended_start, extended_end)
        saved_counts = {'credit_card': 0, 'alipay': 0, 'wechat': 0}
        
        for email_data in credit_card_emails:
            if parser.is_credit_card_statement(email_data):
                date_str = email_data['date'].strftime('%Y%m%d')
                safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
                email_folder = email_dir / f"{date_str}_{safe_subject}"
                save_email_content(email_folder, email_data, email_data['raw_message'])
                saved_counts['credit_card'] += 1

        # 2. 获取支付宝账单（如果不存在）
        if not alipay_exists:
            # 支付宝账单使用普通的搜索期间
            alipay_emails = parser.get_latest_bill_emails('alipay')
            alipay_dir.mkdir(exist_ok=True)
            
            for email_data in alipay_emails:
                saved_files = parser.save_bill_attachments(email_data, alipay_dir)
                if saved_files:
                    logger.info(f"已保存支付宝账单附件: {', '.join(saved_files)}")
                    for file_path in saved_files:
                        if file_path.lower().endswith('.zip'):
                            extract_dir = alipay_dir / Path(file_path).stem
                            if parser.extract_zip_file(file_path, extract_dir, alipay_pwd):
                                saved_counts['alipay'] += 1
        else:
            logger.info("跳过支付宝账单下载（已存在）")

        # 3. 获取微信支付账单（如果不存在）
        if not wechat_exists:
            wechat_emails = parser.get_latest_bill_emails('wechat')
            wechat_dir.mkdir(exist_ok=True)
            
            for email_data in wechat_emails:
                download_link = parser.extract_wechat_download_link(email_data)
                if download_link:
                    logger.info(f"找到微信账单下载链接，开始下载...")
                    saved_file = parser.download_wechat_bill(download_link, wechat_dir)
                    if saved_file:
                        extract_dir = wechat_dir / Path(saved_file).stem
                        if parser.extract_zip_file(saved_file, extract_dir, wechat_pwd):
                            saved_counts['wechat'] += 1
                            logger.info(f"已成功下载并解压微信账单文件")
        else:
            logger.info("跳过微信账单下载（已存在）")

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
    解析已保存的邮件
    """
    set_global_log_level(log_level)
    logger.info("开始解析已保存的邮件...")
    
    try:
        email_dir = EMAILS_DIR
        if not email_dir.exists():
            logger.error("未找到emails目录，请先运行download命令下载邮件")
            return
            
        # 获取账单统计期间（用于过滤交易记录）
        statement_start, statement_end = get_statement_period(year, month, statement_day)
        
        all_transactions = []
        wechat_alipay_transactions = []
        credit_card_transactions = []
        
        for email_folder in email_dir.iterdir():
            if not email_folder.is_dir():
                continue
                
            try:
                is_wechat_alipay = any(folder_name in email_folder.name.lower() 
                                      for folder_name in ['alipay', 'wechat'])
                
                if is_wechat_alipay:
                    # 支付宝和微信账单使用普通的账单统计期间
                    transactions = parse_statement_email(email_folder, statement_start, statement_end)
                else:
                    # 信用卡账单使用扩展的搜索期间
                    extended_email_start, extended_email_end = get_extended_email_search_period(year, month, statement_day)
                    transactions = parse_statement_email(email_folder, extended_email_start, extended_email_end)
                
                if transactions:
                    # 只对信用卡账单进行日期过滤
                    if not is_wechat_alipay:
                        filtered_transactions = []
                        for txn in transactions:
                            # 确保txn.date是datetime对象
                            if isinstance(txn.date, str):
                                try:
                                    # 尝试将字符串转换为datetime对象
                                    txn_date = datetime.strptime(txn.date, '%Y-%m-%d')
                                except ValueError:
                                    logger.warning(f"无法解析交易日期: {txn.date}")
                                    continue
                            else:
                                txn_date = txn.date
                            
                            if statement_start <= txn_date <= statement_end:
                                filtered_transactions.append(txn)
                        transactions = filtered_transactions
                    
                    if transactions:
                        if is_wechat_alipay:
                            wechat_alipay_transactions.extend(transactions)
                        else:
                            credit_card_transactions.extend(transactions)
                        logger.info(f"成功解析 {email_folder.name} 中的 {len(transactions)} 条交易记录")
            except Exception as e:
                logger.error(f"解析 {email_folder.name} 时出错: {str(e)}", exc_info=True)
                continue

        # 合并交易描述
        all_transactions = merge_transaction_descriptions(
            credit_card_transactions,
            wechat_alipay_transactions
        )
        
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
    csv_writer = CSVWriter(TRANSACTIONS_CSV, Transaction.get_fieldnames())
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
