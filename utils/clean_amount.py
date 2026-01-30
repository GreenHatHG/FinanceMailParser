import re


def clean_amount(amount_str: str) -> float:
    """
    统一清理金额字符串格式
    Args:
        amount_str: 原始金额字符串
    Returns:
        清理后的金额（float类型）
    """
    if amount_str.count(".") > 1:
        raise ValueError(f"无效的金额格式: {amount_str}，包含多个小数点")
    # 移除所有空白字符
    amount_str = re.sub(r"\s+", "", amount_str)
    # 处理带有货币符号的情况
    amount_str = amount_str.replace("¥", "").replace("/CNY", "").replace("/RMB", "")
    # 提取数字、小数点和负号，支持千分位
    amount = re.search(r"-?\d+(?:,\d{3})*(?:\.\d*)?", amount_str)
    if amount:
        cleaned_amount = amount.group().replace(",", "")  # 去除千分位
        # 如果包含"存入"，金额为负数
        if "存入" in amount_str:
            return -float(cleaned_amount)
        return float(cleaned_amount)
    else:
        raise ValueError(f"无效的金额格式: {amount_str}，未能提取有效的金额部分")


if __name__ == "__main__":
    print(clean_amount("123,456.78.90"))
