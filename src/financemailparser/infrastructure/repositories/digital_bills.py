"""
数字钱包（支付宝/微信）账单文件的原始读取。

仅负责将本地文件读取为 DataFrame，不做业务过滤或转换。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from financemailparser.shared.constants import (
    ALIPAY_CSV_DEFAULTS,
    WECHAT_CSV_DEFAULTS,
)

logger = logging.getLogger(__name__)


def read_alipay_bill_dataframe(bill_file: Path) -> Optional[pd.DataFrame]:
    """
    读取支付宝 CSV 账单文件并返回 DataFrame。

    Returns:
        DataFrame 或 None（读取失败时）
    """
    try:
        defaults = ALIPAY_CSV_DEFAULTS
        df = pd.read_csv(
            bill_file,
            header=defaults.header_row,
            skipfooter=defaults.skip_footer,
            encoding=defaults.encoding,
        )
        # 支付宝 CSV 末尾有多余列，删除最后一列
        df.drop(df.columns[-1], axis=1, inplace=True)
        return df
    except Exception:
        logger.exception("读取支付宝账单文件失败：%s", bill_file)
        return None


def read_wechat_bill_dataframe(bill_file: Path) -> Optional[pd.DataFrame]:
    """
    读取微信 XLSX 账单文件并返回 DataFrame。

    Returns:
        DataFrame 或 None（读取失败时）
    """
    try:
        defaults = WECHAT_CSV_DEFAULTS
        df = pd.read_excel(
            bill_file,
            header=defaults.header_row,
            skipfooter=defaults.skip_footer,
            engine="openpyxl",
        )
        return df
    except Exception:
        logger.exception("读取微信账单文件失败：%s", bill_file)
        return None
