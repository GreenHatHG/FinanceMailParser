from beancount import loader
from collections import defaultdict
import beancount.core.data
import decimal

def aggregate_expenses_by_parent_account_with_alias(file_path, year=None, month=None, start_date=None, end_date=None, display_format="value"):
    """
    聚合费用交易，并显示账户别名（中文注释），可按时间筛选和格式化显示。
    从原始文件中提取注释（;后面的内容）作为账户别名。

    Args:
        file_path (str): Beancount 文件路径。
        year (int, optional): 筛选年份。默认为 None (不筛选年份)。
        month (int, optional): 筛选月份 (1-12)。默认为 None (不筛选月份)。如果指定了年份，则筛选指定年份的月份，否则筛选所有年份的该月份。
        start_date (date, optional): 筛选开始日期。默认为 None (不筛选开始日期)。
        end_date (date, optional): 筛选结束日期。默认为 None (不筛选结束日期)。
        display_format (str, optional): 显示格式，可以是 "value", "percentage", "value_percentage"。默认为 "value"。
    """
    entries, errors, options_map = loader.load_file(file_path)
    if errors:
        print("Beancount 文件加载时发现错误：")
        for error in errors:
            print(error)
        return

    # 提取账户别名（从原始文件中读取注释）
    account_aliases = {}
    for entry in entries:
        if isinstance(entry, beancount.core.data.Open) and 'filename' in entry.meta and 'lineno' in entry.meta:
            account_name = entry.account
            filename = entry.meta['filename']
            lineno = entry.meta['lineno']

            # 读取原始文件中的行
            try:
                with open(filename, 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                    if 0 <= lineno - 1 < len(lines):  # lineno通常从1开始
                        line = lines[lineno - 1]
                        # 提取注释部分
                        if ';' in line:
                            comment = line.split(';', 1)[1].strip()
                            account_aliases[account_name] = comment
            except Exception as e:
                print(f"读取文件 {filename} 时出错: {e}")

    expense_totals = defaultdict(decimal.Decimal)

    # 聚合费用
    for entry in entries:
        if isinstance(entry, beancount.core.data.Transaction):
            date_to_check = entry.date
            if year and date_to_check.year != year:
                continue
            if month and date_to_check.month != month:
                continue
            if start_date and date_to_check < start_date:
                continue
            if end_date and date_to_check > end_date:
                continue

            for posting in entry.postings:
                account_name = posting.account
                if account_name.startswith('Expenses:'):
                    account_parts = account_name.split(':')
                    if len(account_parts) >= 3:
                        parent_account = account_parts[0] + ':' + account_parts[1]
                    elif len(account_parts) == 2:
                        parent_account = account_name
                    else:
                        parent_account = account_name

                    expense_totals[parent_account] += posting.units.number

    sorted_expenses = sorted(expense_totals.items(), key=lambda item: item[1], reverse=True)

    total_expenses_value = sum(expense_totals.values())

    time_filter_desc = ""
    if year:
        time_filter_desc += f"{year}年"
        if month:
            time_filter_desc += f"{month}月"
    elif month:
        time_filter_desc += f"所有年份{month}月"
    elif start_date or end_date:
        time_filter_desc += f"{start_date.strftime('%Y年%m月%d日') if start_date else '最早'} - {end_date.strftime('%Y年%m月%d日') if end_date else '最晚'}期间"
    else:
        time_filter_desc += "所有时间"

    display_format_desc = ""
    if display_format == "value_percentage":
        display_format_desc = "(数值+百分比)"
    elif display_format == "percentage":
        display_format_desc = "(百分比)"
    else:
        display_format_desc = "(数值)"

    print(f"--- {time_filter_desc}费用 {display_format_desc} ---")

    for account, total in sorted_expenses:
        alias = account_aliases.get(account, "")
        output_str = f"{account}"
        if alias:
            output_str += f" ({alias})"

        if display_format == "percentage" or display_format == "value_percentage":
            percentage = (total / total_expenses_value) * 100 if total_expenses_value else 0
            percentage_str = f"{percentage:.2f}%"
            if display_format == "value_percentage":
                output_str += f": {total} ({percentage_str})"
            else:
                output_str += f": {percentage_str}"
        else: # display_format == "value" or default
            output_str += f": {total}"

        print(output_str)

if __name__ == "__main__":
    beancount_file = "/home/jooooody/beancount/main.bean"

    # 2023 年费用
    # aggregate_expenses_by_parent_account_with_alias(beancount_file, year=2023)

    # 2023 年 10 月费用 (数值+百分比)
    # aggregate_expenses_by_parent_account_with_alias(beancount_file, year=2023, month=10, display_format="value_percentage")

    # 2023 年 10 月费用 (百分比)
    # aggregate_expenses_by_parent_account_with_alias(beancount_file, year=2023, month=10, display_format="percentage")

    # 2023 年 10 月 15 日 - 2023 年 11 月 15 日 费用 (数值)
    # start_date = date(2023, 10, 15)
    # end_date = date(2023, 11, 15)
    # aggregate_expenses_by_parent_account_with_alias(beancount_file, start_date=start_date, end_date=end_date, display_format="value")

    # 所有时间费用 (默认数值)
    # aggregate_expenses_by_parent_account_with_alias(beancount_file)