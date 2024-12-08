import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
import logging
from pathlib import Path

from data_source.qq_email import QQEmailParser
from data_source.qq_email.email_processor import save_email_content
from data_source.qq_email.utils import create_storage_structure
from statement_parsers.qq_email import parse_statement_email
from utils.logger import set_global_log_level
from models.txn import Transaction  # 添加导入语句

logger = logging.getLogger(__name__)


def get_date_range(year: Optional[int] = None, month: Optional[int] = None, statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取指定年月的账单日期范围
    
    Args:
        year: 年份，如果为None则使用当前年份
        month: 月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
        
    Returns:
        开始日期和结束日期的元组，表示账单发送的日期范围
        例如：10月份的账单（统计期间为10.5-11.5）会在11.6-12.5期间发送
    """
    today = datetime.now()
    
    if year is None and month is None:
        # 根据当前日期和账单日判断应该获取哪个月的账单
        if today.day >= statement_day:
            # 如果当前日期已过账单日，获取上月账单
            if today.month == 1:
                start_month = 11
                start_year = today.year - 1
            else:
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
        # 对于指定月份，我们需要在原始月份基础上加1个月
        # 因为我们要找的是账单发送的时间范围
        start_month = month if month is not None else today.month
        start_year = year if year is not None else today.year
        
        # 调整到账单发送月份（比消费月份加1）
        if start_month == 12:
            start_month = 1
            start_year += 1
        else:
            start_month += 1
    
    # 计算账单发送开始日期（下月6号）
    start_date = datetime(start_year, start_month, statement_day + 1)
    
    # 计算账单发送结束日期（下下月5号）
    if start_month == 12:
        end_month = 1
        end_year = start_year + 1
    else:
        end_month = start_month + 1
        end_year = start_year
    
    end_date = datetime(end_year, end_month, statement_day)
    
    # 添加日志打印
    logger.info(f"搜索邮件的日期范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
            
    return start_date, end_date


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
        # 新增：打印每个银行的详细交易记录
        logger.debug(f"\n{bank} 的交易明细:")
        for txn in bank_transactions[bank]:
            logger.debug(f"  - 日期: {txn.date}, 描述: {txn.description}, 金额: ¥{txn.amount:.2f}")


def download_emails(year: Optional[int] = None, 
                   month: Optional[int] = None, 
                   statement_day: int = 5,
                   log_level: str = 'INFO') -> None:
    """
    第一步：从QQ邮箱下载并保存邮件到本地
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
        # 获取日期范围
        start_date, end_date = get_date_range(year, month, statement_day)
        
        # 获取邮件列表并保存到本地
        email_list = parser.get_email_list(start_date, end_date)
        
        saved_count = 0
        for email_data in email_list:
            if parser.is_credit_card_statement(email_data):
                # 获取邮件保存路径
                date_str = email_data['date'].strftime('%Y%m%d')
                safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
                email_folder = create_storage_structure() / f"{date_str}_{safe_subject}"
                
                # 保存邮件内容
                save_email_content(email_folder, email_data, email_data['raw_message'])
                saved_count += 1
                
        logger.info(f"邮件下载完成，共保存了 {saved_count} 封信用卡账单邮件")

    except Exception as e:
        logger.error(f"下载邮件时出错: {str(e)}", exc_info=True)
    finally:
        parser.close()


def parse_saved_emails(log_level: str = 'INFO') -> None:
    """
    第二步：解析已保存的邮件
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
            
        # 遍历所有邮件文件夹
        all_transactions = []
        for email_folder in email_dir.iterdir():
            if not email_folder.is_dir():
                continue
                
            try:
                # 解析账单
                transactions = parse_statement_email(email_folder)
                if transactions:
                    all_transactions.extend(transactions)
                    logger.info(f"成功解析 {email_folder.name} 中的 {len(transactions)} 条交易记录")
            except Exception as e:
                logger.error(f"解析 {email_folder.name} 时出错: {str(e)}")
                continue
                
        # 输出统计信息
        print_transaction_stats(all_transactions)
        
    except Exception as e:
        logger.error(f"解析邮件时出错: {str(e)}", exc_info=True)


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
                       help='设置日志级��，默认为INFO')
    
    args = parser.parse_args()
    
    # 验证月份
    if args.month is not None and not (1 <= args.month <= 12):
        parser.error('月份必须在1到12之间')
    
    # 验证账单日
    if not (1 <= args.statement_day <= 31):
        parser.error('账单日必须在1到31之间')
    
    if args.command == 'download':
        download_emails(args.year, args.month, args.statement_day, args.log_level)
    else:
        parse_saved_emails(args.log_level) 