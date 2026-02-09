import logging
from datetime import datetime
from typing import Callable, List, Mapping, Optional, Sequence

import pandas as pd

from financemailparser.domain.models.txn import (
    DigitalPaymentTransaction,
    Transaction,
)
from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.services.bank_alias import (
    find_transaction_source_by_alias,
)
from financemailparser.domain.services.date_filter import is_in_date_range
from financemailparser.shared.constants import (
    DATE_FMT_ISO,
    DATETIME_FMT_ISO,
    WECHAT_CSV_DEFAULTS,
)

logger = logging.getLogger(__name__)


def extract_date(datetime_str: str) -> str:
    dt = datetime.strptime(datetime_str, DATETIME_FMT_ISO)
    date_str = dt.strftime(DATE_FMT_ISO)
    return date_str


def parse_wechat_statement(
    file_path: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    skip_transaction: Optional[Callable[[str], bool]] = None,
    bank_alias_keywords: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Transaction]:
    header_row = WECHAT_CSV_DEFAULTS.header_row
    encoding = WECHAT_CSV_DEFAULTS.encoding
    skip_footer = WECHAT_CSV_DEFAULTS.skip_footer

    # 微信账单格式：交易时间 交易类型 交易对方 商品 收/支 金额(元) 支付方式 当前状态 交易单号 商户单号 备注 共11列
    df = pd.read_csv(
        file_path, header=header_row, skipfooter=skip_footer, encoding=encoding
    )  # 微信的对账单格式从第17行开始（0-indexed为16）
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

    # 不再过滤信用卡支付记录，直接使用时间过滤后的数据
    transactions: List[Transaction] = []
    filtered_keywords = []

    for index, row in df_in_range.iterrows():
        if "¥" not in row["金额(元)"]:
            logger.error(row)
            raise Exception("get amount failed")

        desc = row["商品"] + "-" + row["交易类型"] + "-" + row["交易对方"]

        # 过滤关键字（用户可配置，默认包含：零钱提现/微信红包）
        if skip_transaction and skip_transaction(desc):
            filtered_keywords.append(desc)
            continue

        payment_method = row["支付方式"]
        card_info = None
        if "信用卡" in payment_method:
            card_info = find_transaction_source_by_alias(
                payment_method,
                bank_alias_keywords=bank_alias_keywords,
            )

        txn = DigitalPaymentTransaction(
            TransactionSource.WECHAT.value,
            extract_date(row["交易时间"]),
            desc,
            row["金额(元)"].replace("¥", ""),
            payment_method=payment_method,
        )
        if card_info:
            txn.card_source = card_info
        transactions.append(txn)

    if filtered_keywords:
        logger.info(
            f"按关键字过滤掉 {len(filtered_keywords)} 条记录：{filtered_keywords}"
        )

    logger.info(f"最终保留 {len(transactions)} 条记录")
    return transactions
