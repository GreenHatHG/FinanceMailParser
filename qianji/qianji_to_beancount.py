from beancount import loader
import beancount.core.data
from collections import defaultdict
import pandas as pd
import datetime
from typing import Dict, Tuple, Optional, Union, List, Any


class CategoryMappingError(Exception):
    """当类别无法映射到 Beancount 账户时引发的异常。"""
    pass


def qianji_to_beancount(
        csv_file: str,
        beancount_file: str,
        account_mapping: Optional[Dict[str, Union[str, Dict[str, str]]]] = None,
        default_asset_account: str = "Assets:Unknown",
        account_descriptions: Optional[Dict[str, str]] = None
) -> None:
    """
    将钱迹 CSV 导出转换为 Beancount 格式并写入文件。

    Args:
        csv_file: 钱迹 CSV 文件的路径。
        beancount_file: 输出 Beancount 文件的路径。
        account_mapping: 可选字典，将钱迹类别映射到 Beancount 账户。
                         可以处理嵌套子类别。
        default_asset_account: 交易对方的默认 Beancount 资产账户。
        account_descriptions: 可选字典，将 Beancount 账户映射到中文描述。
                              当备注为空时，用于账目描述。

    Raises:
        FileNotFoundError: 如果找不到 CSV 文件。
        CategoryMappingError: 如果类别无法映射到 Beancount 账户。
        ValueError: 如果 CSV 文件格式无效。
    """
    try:
        df = pd.read_csv(csv_file)
    except FileNotFoundError:
        raise FileNotFoundError(f"找不到 CSV 文件：{csv_file}")
    except Exception as e:
        raise ValueError(f"读取 CSV 文件时出错：{e}")

    # 验证 CSV 结构
    expected_columns = ['时间', '分类', '二级分类', '金额', '币种', '备注']
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV 文件缺少必需的列：{', '.join(missing_columns)}")

    beancount_entries = []

    for index, row in df.iterrows():
        try:
            date_str = row['时间']
            category = row['分类']
            subcategory = row['二级分类']
            amount = row['金额']
            currency = row['币种']
            narration = row['备注']

            # 转换日期格式
            try:
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                date = date_obj.strftime('%Y-%m-%d')
            except ValueError:
                raise ValueError(f"无效的日期格式：{date_str} 在第 {index} 行。预期格式：YYYY-MM-DD HH:MM:SS")

            # 映射到 Beancount 账户
            account = map_to_beancount_account(category, subcategory, account_mapping)

            # 确定账目描述
            narration = determine_narration(narration, account, account_descriptions)

            # 创建 Beancount 条目
            entry = f"{date} * \"{narration}\"\n"
            entry += f"  {account}  {amount} {currency}\n"
            entry += f"  {default_asset_account}  {-amount} {currency}\n\n"
            beancount_entries.append(entry)

        except CategoryMappingError as e:
            raise CategoryMappingError(f"第 {index} 行：{e}")
        except Exception as e:
            raise ValueError(f"处理第 {index} 行时出错：{e}")

    try:
        with open(beancount_file, 'w', encoding='utf-8') as f:
            f.writelines(beancount_entries)
        print(f"成功添加了 {len(beancount_entries)} 条记录到 {beancount_file}")
    except Exception as e:
        raise IOError(f"写入 Beancount 文件时出错：{e}")


def map_to_beancount_account(
        category: str,
        subcategory: Optional[str],
        account_mapping: Optional[Dict[str, Union[str, Dict[str, str]]]]
) -> str:
    """
    将钱迹类别和子类别映射到 Beancount 账户。

    Args:
        category: 钱迹的主要类别。
        subcategory: 钱迹的子类别，可以为 None 或 NaN。
        account_mapping: 将类别映射到 Beancount 账户的字典。

    Returns:
        映射的 Beancount 账户名称。

    Raises:
        CategoryMappingError: 如果类别无法映射。
    """
    if not account_mapping:
        # 未提供映射，构造默认账户名称
        if pd.notna(subcategory) and subcategory:
            account = f"Expenses:{category}:{subcategory}".replace(" ", "")
        else:
            account = f"Expenses:{category}".replace(" ", "")
        return account

    # 尝试在映射中查找类别
    if category not in account_mapping:
        raise CategoryMappingError(f"在账户映射中找不到类别“{category}”")

    category_mapping = account_mapping[category]

    # 如果映射是字符串，直接使用它（这是一个顶级账户）
    if isinstance(category_mapping, str):
        return category_mapping

    # 如果映射是字典，处理子类别映射
    if isinstance(category_mapping, dict):
        # 处理空或 NaN 子类别
        if pd.isna(subcategory) or not subcategory:
            # 检查是否有针对空子类别的特定映射
            if "" in category_mapping:
                return category_mapping[""]
            # 检查是否有与类别同名的直接父账户映射
            parent_account = f"Expenses:{category.replace(' ', '')}"
            for account in category_mapping.values():
                # 从任何子类别账户中提取父账户
                if ':' in account:
                    parent_account = ':'.join(account.split(':')[:-1])
                    break
            return parent_account

        # 如果子类别存在且在映射中
        if subcategory in category_mapping:
            return category_mapping[subcategory]

        # 未找到匹配的子类别
        subcategory_str = str(subcategory) if pd.notna(subcategory) else "空"
        available_subcategories = ", ".join(f"'{k}'" for k in category_mapping.keys())
        raise CategoryMappingError(
            f"在账户映射中找不到类别“{category}”的子类别“{subcategory_str}”。"
            f"可用的子类别：{available_subcategories}"
        )

    # 意外的映射类型
    raise CategoryMappingError(f"类别“{category}”的映射类型无效")


def determine_narration(
        narration: Any,
        account: str,
        account_descriptions: Optional[Dict[str, str]]
) -> str:
    """
    确定 Beancount 条目的账目描述。

    Args:
        narration: 来自钱迹的原始账目描述。
        account: Beancount 账户名称。
        account_descriptions: 将账户映射到描述的字典。

    Returns:
        要在 Beancount 条目中使用的账目描述。
    """
    if pd.isna(narration) or not str(narration).strip():
        # 如果可用，使用账户描述
        if account_descriptions and account in account_descriptions:
            return account_descriptions[account]
        # 否则使用账户名称
        return account

    # 使用原始账目描述
    return str(narration).strip()


def generate_account_mappings(bean_file_path: str) -> Tuple[Dict[str, Union[str, Dict[str, str]]], Dict[str, str]]:
    """
    从 Beancount 文件生成映射：
    1. 中文名称到账户名称的映射 (custom_account_mapping)
    2. 账户名称到中文描述的映射 (account_descriptions_mapping)

    Args:
        bean_file_path: Beancount 文件的路径。

    Returns:
        一个元组 (custom_account_mapping, account_descriptions_mapping)
    """
    # 加载 Beancount 文件
    entries, errors, options_map = loader.load_file(bean_file_path)
    if errors:
        print("加载 Beancount 文件时发现错误：")
        for error in errors:
            print(error)
        return {}, {}

    # 提取账户和注释
    account_comments = {}
    for entry in entries:
        if isinstance(entry, beancount.core.data.Open) and 'filename' in entry.meta and 'lineno' in entry.meta:
            account_name = entry.account
            filename = entry.meta['filename']
            lineno = entry.meta['lineno']

            # 从文件中读取原始行
            try:
                with open(filename, 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                    if 0 <= lineno - 1 < len(lines):
                        line = lines[lineno - 1]
                        # 提取注释部分
                        if ';' in line:
                            comment = line.split(';', 1)[1].strip()
                            account_comments[account_name] = comment
            except Exception as e:
                print(f"读取文件 {filename} 时出错：{e}")

    # 创建账户名称到中文描述的映射
    account_descriptions_mapping = {
        account: comment for account, comment in account_comments.items() if comment
    }

    # 创建中文名称到账户名称的映射
    custom_account_mapping = {}
    account_hierarchy = defaultdict(dict)

    for account, comment in account_comments.items():
        if not comment:
            continue

        # 拆分账户名称以获取层次结构
        parts = account.split(':')

        # 处理二级及以上账户
        if len(parts) >= 2:
            top_level = parts[0]  # 例如，"Expenses"
            second_level = parts[1]  # 例如，"Travel"

            # 提取中文描述的最后一部分作为键
            chinese_parts = comment.split(':')
            chinese_key = chinese_parts[-1]

            # 处理三级及以上账户
            if len(parts) >= 3:
                # 特殊处理三级账户
                if top_level == "Expenses" and second_level == "Travel":
                    if "旅行" not in account_hierarchy:
                        account_hierarchy["旅行"] = {}
                    account_hierarchy["旅行"][chinese_key] = account
                elif top_level == "Expenses" and second_level == "GiftsAndTreats":
                    if "请客送礼" not in account_hierarchy:
                        account_hierarchy["请客送礼"] = {}
                    account_hierarchy["请客送礼"][chinese_key] = account
                else:
                    # 处理其他三级账户
                    parent_chinese = ':'.join(chinese_parts[:-1])
                    if parent_chinese not in account_hierarchy:
                        account_hierarchy[parent_chinese] = {}
                    account_hierarchy[parent_chinese][chinese_key] = account
            else:
                # 处理二级账户
                custom_account_mapping[chinese_key] = account

    # 将层次结构添加到映射
    for parent, children in account_hierarchy.items():
        if children:
            # 添加父账户作为空字符串键，用于处理没有子类别的交易
            if parent in account_descriptions_mapping.values():
                # 找到父账户
                for acc, desc in account_descriptions_mapping.items():
                    if desc == parent:
                        # 添加空字符串映射到父账户
                        children[""] = acc
                        break
            custom_account_mapping[parent] = children

    return custom_account_mapping, account_descriptions_mapping


def print_mappings(
        custom_account_mapping: Dict[str, Union[str, Dict[str, str]]],
        account_descriptions_mapping: Dict[str, str]
) -> None:
    """
    打印生成的映射以供查看和复制。

    Args:
        custom_account_mapping: 中文名称到账户名称的映射。
        account_descriptions_mapping: 账户名称到中文描述的映射。
    """
    print("# 中文名称到账户名称的映射")
    print("custom_account_mapping = {")
    for key, value in sorted(custom_account_mapping.items()):
        if isinstance(value, dict):
            print(f"    \"{key}\": {{")
            for sub_key, sub_value in sorted(value.items()):
                print(f"        \"{sub_key}\": \"{sub_value}\",")
            print("    },")
        else:
            print(f"    \"{key}\": \"{value}\",")
    print("}")

    print("\n# 账户名称到中文描述的映射")
    print("account_descriptions_mapping = {")
    for key, value in sorted(account_descriptions_mapping.items()):
        print(f"    \"{key}\": \"{value}\",")
    print("}")


if __name__ == "__main__":
    csv_file = 'QianJi_默认账本_2025-03-04_181602.csv'
    beancount_file = 'beancount.bean'
    bean_file_path = "/home/jooooody/beancount/main.bean"

    try:
        custom_mapping, descriptions_mapping = generate_account_mappings(bean_file_path)
        print_mappings(custom_mapping, descriptions_mapping)

        # 为“请客送礼”的父账户添加显式映射
        if "请客送礼" in custom_mapping and isinstance(custom_mapping["请客送礼"], dict):
            custom_mapping["请客送礼"][""] = "Expenses:GiftsAndTreats"

        qianji_to_beancount(
            csv_file=csv_file,
            beancount_file=beancount_file,
            account_mapping=custom_mapping,
            default_asset_account="Equity:Uncategorized",
            account_descriptions=descriptions_mapping
        )
    except CategoryMappingError as e:
        print(f"类别映射错误：{e}")
    except Exception as e:
        print(f"错误：{e}")