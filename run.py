import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict

from data_source.qq_email import QQEmailParser
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_date_range(year: Optional[int] = None, month: Optional[int] = None, statement_day: int = 5) -> Tuple[datetime, datetime]:
    """
    获取指定年月的账单日期范围，如果未指定则返回上个月的日期范围
    
    Args:
        year: 年份，如果为None则使用当前年份
        month: 月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
        
    Returns:
        开始日期和结束日期的元组
    """
    today = datetime.now()
    
    if year is None or month is None:
        # 根据当前日期和账单日判断应该获取哪个月的账单
        if today.day >= statement_day:
            # 如果当前日期已过账单日，获取当月账单
            end_month = today.month
            end_year = today.year
        else:
            # 如果当前日期未到账单日，获取上月账单
            if today.month == 1:
                end_month = 12
                end_year = today.year - 1
            else:
                end_month = today.month - 1
                end_year = today.year
    else:
        end_month = month
        end_year = year
    
    # 计算账单结束日期
    end_date = datetime(end_year, end_month, statement_day)
    
    # 计算账单开始日期（上月账单日）
    if end_month == 1:
        start_month = 12
        start_year = end_year - 1
    else:
        start_month = end_month - 1
        start_year = end_year
    
    start_date = datetime(start_year, start_month, statement_day)
            
    return start_date, end_date


def print_transaction_stats(transactions: List[Dict]) -> None:
    """
    打印交易记录的统计信息
    
    Args:
        transactions: 交易记录列表
    """
    if not transactions:
        logger.info("未找到任何交易记录")
        return
        
    total_amount = sum(float(txn['amount']) for txn in transactions)
    logger.info(f"处理完成，共解析 {len(transactions)} 条交易记录")
    logger.info(f"总金额: ¥{total_amount:.2f}")
    
    # 按银行分类统计
    bank_stats = {}
    for txn in transactions:
        bank = txn.get('bank', '未知')
        if bank not in bank_stats:
            bank_stats[bank] = {'count': 0, 'amount': 0}
        bank_stats[bank]['count'] += 1
        bank_stats[bank]['amount'] += float(txn['amount'])
    
    logger.info("\n按银行统计:")
    for bank, stats in bank_stats.items():
        logger.info(f"{bank}: {stats['count']}笔交易, 总金额 ¥{stats['amount']:.2f}")


def run(year: Optional[int] = None, month: Optional[int] = None, statement_day: int = 5) -> None:
    """
    运行信用卡账单解析程序
    
    Args:
        year: 指定年份，如果为None则使用当前年份
        month: 指定月份，如果为None则使用上个月
        statement_day: 账单日，默认为5号
    """
    # 创建解析器实例
    parser = QQEmailParser(os.getenv('QQ_EMAIL'), os.getenv('QQ_EMAIL_AUTH_CODE'))

    if not parser.login():
        logger.error("登录失败，程序退出")
        return

    try:
        # 获取日期范围
        start_date, end_date = get_date_range(year, month, statement_day)
        
        # 处理邮件并获取交易记录
        all_transactions = parser.process_emails(start_date, end_date)
        
        # 输出统计信息
        print_transaction_stats(all_transactions)

    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}", exc_info=True)
    finally:
        parser.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='信用卡账单解析工具')
    parser.add_argument('--year', type=int, help='指定年份，默认为当前年份')
    parser.add_argument('--month', type=int, help='指定月份，默认为上个月')
    parser.add_argument('--statement-day', type=int, default=5, help='账单日，默认为5号')
    
    args = parser.parse_args()
    
    # 验证月份
    if args.month is not None and not (1 <= args.month <= 12):
        parser.error('月份必须在1到12之间')
    
    # 验证账单日
    if not (1 <= args.statement_day <= 31):
        parser.error('账单日必须在1到31之间')
    
    run(args.year, args.month, args.statement_day) 