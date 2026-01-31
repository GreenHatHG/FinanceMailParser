from datetime import datetime

from constants import DATE_FMT_COMPACT, DATE_FMT_ISO


def is_skip_transaction(description: str) -> bool:
    """
    检查是否需要跳过该交易

    Args:
        description: 交易描述

    Returns:
        是否跳过
    """
    skip_keywords = ["还款", "银联入账", "转入", "入账"]
    return any(keyword in description for keyword in skip_keywords)


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
