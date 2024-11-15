from datetime import datetime
import re
from typing import List, Dict, Any

def clean_amount(amount_str: str) -> str:
    """
    统一清理金额字符串格式
    
    Args:
        amount_str: 原始金额字符串
        
    Returns:
        清理后的金额字符串
    """
    # 移除所有空白字符
    amount_str = re.sub(r'\s+', '', amount_str)
    
    # 处理带有货币符号的情况
    amount_str = amount_str.replace('¥', '').replace('/CNY', '')
    
    # 提取数字、小数点和负号
    amount = re.search(r'-?\d+\.?\d*', amount_str)
    if amount:
        # 如果包含"存入"，金额为负数
        if '存入' in amount_str:
            return f"-{amount.group()}"
        return amount.group()
    raise ValueError(f"无效的金额格式: {amount_str}")

def is_skip_transaction(description: str) -> bool:
    """
    检查是否需要跳过该交易
    
    Args:
        description: 交易描述
        
    Returns:
        是否跳过
    """
    skip_keywords = ['还款', '银联入账', '转入', '入账']
    return any(keyword in description for keyword in skip_keywords)

def format_date(date_str: str, format_str: str = '%Y%m%d') -> str:
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
            current_year = datetime.now().year
            date_str = f"{current_year}{date_str}"
            format_str = '%Y%m%d'
        date_obj = datetime.strptime(date_str, format_str)
        return date_obj.strftime('%Y-%m-%d')
    except ValueError as e:
        raise ValueError(f"无效的日期格式: {date_str}, {str(e)}")
