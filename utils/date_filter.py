"""
日期过滤工具函数

统一封装「按 start_date / end_date 过滤交易」的逻辑，供所有账单解析器复用，
避免每个解析器各写一套日期解析与比较规则，后续也便于集中维护。
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional, Sequence

DEFAULT_DATE_FORMATS: Sequence[str] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def parse_date_safe(
    date_str: str,
    formats: Sequence[str] = DEFAULT_DATE_FORMATS,
    logger: Optional[logging.Logger] = None,
) -> Optional[datetime]:
    """
    尝试用多种格式解析日期字符串。

    Args:
        date_str: 日期字符串（通常是 YYYY-MM-DD 或 YYYY/MM/DD）
        formats: 允许的日期格式列表
        logger: 可选 logger，用于记录解析失败信息

    Returns:
        datetime 或 None（解析失败）
    """
    date_str = str(date_str).strip()
    if not date_str:
        return None

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    if logger:
        logger.warning(f"无法解析日期字符串: {date_str}")
    return None


def is_in_date_range(
    date_str: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    formats: Sequence[str] = DEFAULT_DATE_FORMATS,
    logger: Optional[logging.Logger] = None,
    keep_if_unparseable: bool = True,
) -> bool:
    """
    判断 date_str 是否落在 [start_date, end_date] 范围内（包含边界）。

    说明：
    - 若 start_date/end_date 都为空，则恒为 True；
    - 若 date_str 无法解析：
      - keep_if_unparseable=True：返回 True（偏保守，避免误删数据）
      - keep_if_unparseable=False：返回 False
    """
    if not start_date and not end_date:
        return True

    dt = parse_date_safe(date_str, formats=formats, logger=logger)
    if not dt:
        return keep_if_unparseable

    if start_date and dt.date() < start_date.date():
        return False
    if end_date and dt.date() > end_date.date():
        return False

    return True

