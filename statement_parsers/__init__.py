from datetime import datetime

from constants import DATE_FMT_COMPACT, DATE_FMT_ISO
from config.user_rules import (
    DEFAULT_TRANSACTION_SKIP_KEYWORDS,
    UserRulesError,
    get_transaction_filters,
    match_skip_keyword,
)


def is_skip_transaction(description: str) -> bool:
    """
    检查是否需要跳过该交易

    Args:
        description: 交易描述

    Returns:
        是否跳过
    """
    try:
        filters = get_transaction_filters()
        skip_keywords = filters["skip_keywords"]
        return match_skip_keyword(str(description or ""), skip_keywords) is not None
    except UserRulesError:
        # Invalid user config should not break parsing; fallback to legacy defaults.
        fallback = DEFAULT_TRANSACTION_SKIP_KEYWORDS
        return any(keyword in str(description or "") for keyword in fallback)
    except Exception:
        fallback = DEFAULT_TRANSACTION_SKIP_KEYWORDS
        return any(keyword in str(description or "") for keyword in fallback)


def format_date(date_str: str, format_str: str = DATE_FMT_COMPACT) -> str:
    """
    统一日期格式化

    Args:
        date_str: 原始日期字符串
        format_str: 输入日期格式

    Returns:
        格式化后的日期字符串 (YYYY-MM-DD)
    """
    try:
        if len(date_str) == 4:  # MMDD 格式
            current_date = datetime.now()
            month = int(date_str[:2])
            int(date_str[2:])  # day - validate format but not used

            # 如果账单月份大于当前月份，说明是去年的账单
            year = current_date.year
            if month > current_date.month:
                year -= 1

            date_str = f"{year}{date_str}"
            format_str = DATE_FMT_COMPACT

        date_obj = datetime.strptime(date_str, format_str)
        return date_obj.strftime(DATE_FMT_ISO)
    except ValueError as e:
        raise ValueError(f"无效的日期格式: {date_str}, {str(e)}")
