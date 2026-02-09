from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple


def _shift_months(year: int, month: int, months: int) -> Tuple[int, int]:
    total_months = year * 12 + (month - 1) - months
    shifted_year = total_months // 12
    shifted_month = total_months % 12 + 1
    return shifted_year, shifted_month


def _get_month_end(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1) - timedelta(days=1)
    return datetime(year, month + 1, 1) - timedelta(days=1)


def get_quick_select_options() -> List[str]:
    today = datetime.now()
    options = ["本月", "上月", "最近三个月", "最近半年"]

    # Add month options from 2 months ago to 6 months ago (inclusive).
    for offset in range(2, 7):
        year, month = _shift_months(today.year, today.month, offset)
        options.append(f"{year}年{month:02d}月")

    return options


def calculate_date_range_for_quick_select(option: str) -> Tuple[datetime, datetime]:
    """
    根据快捷选项计算日期范围

    Args:
        option: 快捷选项（'本月'、'上月'、'最近三个月'、'最近半年'、'YYYY年MM月'）

    Returns:
        (start_date, end_date) 元组

    Raises:
        ValueError: 未知的快捷选项
    """
    today = datetime.now()

    if option == "本月":
        # 本月账单：本月1号到今天
        start_date = datetime(today.year, today.month, 1)
        end_date = today
    elif option == "上月":
        # 上月账单：上月1号到上月最后一天
        if today.month == 1:
            start_date = datetime(today.year - 1, 12, 1)
            end_date = datetime(today.year - 1, 12, 31)
        else:
            start_date = datetime(today.year, today.month - 1, 1)
            end_date = datetime(today.year, today.month, 1) - timedelta(days=1)
    elif option == "最近三个月":
        # 最近三个月：三个月前的1号到今天
        three_months_ago = today - timedelta(days=90)
        start_date = datetime(three_months_ago.year, three_months_ago.month, 1)
        end_date = today
    elif option == "最近半年":
        # 最近半年：六个月前所在月的1号到今天
        half_year_ago_year, half_year_ago_month = _shift_months(
            today.year, today.month, 6
        )
        start_date = datetime(half_year_ago_year, half_year_ago_month, 1)
        end_date = today
    elif option.endswith("月") and "年" in option:
        # 月份快捷项：YYYY年MM月
        try:
            year_part, month_part = option[:-1].split("年", 1)
            year = int(year_part)
            month = int(month_part)
            if month < 1 or month > 12:
                raise ValueError
        except ValueError:
            raise ValueError(f"未知的快捷选项：{option}")
        start_date = datetime(year, month, 1)
        end_date = _get_month_end(year, month)
    else:
        raise ValueError(f"未知的快捷选项：{option}")

    return start_date, end_date
