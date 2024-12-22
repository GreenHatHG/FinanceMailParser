import logging
from typing import List, Optional
from datetime import datetime

import pandas as pd

from models.txn import Transaction, DigitalPaymentTransaction
from statement_parsers.wechat import extract_date
from models.source import TransactionSource

logger = logging.getLogger(__name__)

def parse_alipay_statement(file_path: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[Transaction]:
    # 支付宝账单格式：交易时间 交易分类 交易对方 对方账号 商品说明 收/支 金额 收/付款方式 交易状态 交易订单号 商家订单号 备注
    df = pd.read_csv(file_path, header=22, skipfooter=0, encoding='gbk')  # 支付宝的对账单格式从第25行开始
    df.drop(df.columns[-1], axis=1, inplace=True)
    total_records = len(df)
    logger.info(f"读取到 {total_records} 条记录")
    
    # 首先按时间过滤
    df_in_range = df.copy()
    filtered_dates = []
    
    if start_date or end_date:
        mask = pd.Series(True, index=df.index)
        for index, row in df.iterrows():
            txn_date = datetime.strptime(extract_date(row['交易时间']), '%Y-%m-%d')
            if start_date and txn_date.date() < start_date.date():
                filtered_dates.append(row['交易时间'])
                mask[index] = False
            elif end_date and txn_date.date() > end_date.date():
                filtered_dates.append(row['交易时间'])
                mask[index] = False
        
        df_in_range = df[mask]
        if filtered_dates:
            logger.info(f"按日期过滤掉 {len(filtered_dates)} 条记录")
    
    # 过滤收益发放和余额相关记录
    df_filtered = df_in_range[~df_in_range['商品说明'].str.contains('收益发放|余额')]
    filtered_records = df_in_range[df_in_range['商品说明'].str.contains('收益发放|余额')]
    filtered_count = len(filtered_records)
    
    if filtered_count > 0:
        logger.info(f"按关键字过滤掉 {filtered_count} 条收益发放和余额相关记录")
        for _, row in filtered_records.iterrows():
            logger.debug(f"过滤记录: {row['交易时间']} {row['商品说明']} {row['金额']} {row['收/付款方式']}")
    
    # 不再过滤信用卡支付记录，直接使用过滤后的数据
    transactions = []
    for index, row in df_filtered.iterrows():
        payment_method = str(row['收/付款方式'])
        # 从支付方式中提取信用卡信息
        card_info = None
        if '信用卡' in payment_method:
            if '建设银行' in payment_method or 'CCB' in payment_method.upper():
                card_info = TransactionSource.CCB
            elif '招商银行' in payment_method or 'CMB' in payment_method.upper():
                card_info = TransactionSource.CMB
            elif '光大银行' in payment_method or 'CEB' in payment_method.upper():
                card_info = TransactionSource.CEB
            elif '农业银行' in payment_method or 'ABC' in payment_method.upper():
                card_info = TransactionSource.ABC

        txn = DigitalPaymentTransaction(
            TransactionSource.ALIPAY.value,
            extract_date(row['交易时间']),
            row['商品说明'],
            row['金额'],
        )
        if card_info:
            txn.card_source = card_info
        transactions.append(txn)
    
    logger.info(f"最终保留 {len(transactions)} 条记录")
    return transactions
