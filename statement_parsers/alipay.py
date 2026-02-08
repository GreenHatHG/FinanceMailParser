import logging
from datetime import datetime
from typing import Callable, List, Mapping, Optional, Sequence

import pandas as pd

from models.txn import Transaction, DigitalPaymentTransaction
from statement_parsers.wechat import extract_date
from models.source import TransactionSource
from utils.bank_alias import find_transaction_source_by_alias
from utils.date_filter import is_in_date_range
from constants import ALIPAY_CSV_DEFAULTS

logger = logging.getLogger(__name__)


def parse_alipay_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
    bank_alias_keywords: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Transaction]:
    header_row = ALIPAY_CSV_DEFAULTS.header_row
    encoding = ALIPAY_CSV_DEFAULTS.encoding
    skip_footer = ALIPAY_CSV_DEFAULTS.skip_footer

    # 支付宝账单格式：交易时间 交易分类 交易对方 对方账号 商品说明 收/支 金额 收/付款方式 交易状态 交易订单号 商家订单号 备注
    df = pd.read_csv(
        file_path, header=header_row, skipfooter=skip_footer, encoding=encoding
    )  # 支付宝的对账单格式从第23行开始（0-indexed为22）
    df.drop(df.columns[-1], axis=1, inplace=True)
    total_records = len(df)
    logger.info(f"读取到 {total_records} 条记录")

    # 首先按时间过滤
    df_in_range = df.copy()
    filtered_dates = []

    if start_date or end_date:
        mask = pd.Series(True, index=df.index)
        for index, row in df.iterrows():
            txn_date_str = extract_date(row["交易时间"])
            if not is_in_date_range(txn_date_str, start_date, end_date, logger=logger):
                filtered_dates.append(row["交易时间"])
                mask[index] = False

        df_in_range = df[mask]
        if filtered_dates:
            logger.info(f"按日期过滤掉 {len(filtered_dates)} 条记录")

    # 不再过滤信用卡支付记录，直接使用过滤后的数据
    transactions: List[Transaction] = []
    filtered_keywords: List[str] = []
    for index, row in df_in_range.iterrows():
        desc = str(row["商品说明"])
        if skip_transaction and skip_transaction(desc):
            filtered_keywords.append(desc)
            continue

        payment_method = str(row["收/付款方式"])
        # 从支付方式中提取信用卡信息
        card_info = None
        if "信用卡" in payment_method:
            card_info = find_transaction_source_by_alias(
                payment_method,
                bank_alias_keywords=bank_alias_keywords,
            )

        txn = DigitalPaymentTransaction(
            TransactionSource.ALIPAY.value,
            extract_date(row["交易时间"]),
            row["商品说明"],
            row["金额"],
        )
        if card_info:
            txn.card_source = card_info
        transactions.append(txn)

    if filtered_keywords:
        logger.info(f"按关键字过滤掉 {len(filtered_keywords)} 条记录")
        if logger.isEnabledFor(logging.DEBUG):
            for desc in filtered_keywords[:50]:
                logger.debug("过滤记录: %s", desc)

    logger.info(f"最终保留 {len(transactions)} 条记录")
    return transactions
