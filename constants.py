"""
全局常量定义

存储项目级别的常量，供所有模块使用
"""

import os
from pathlib import Path
from dataclasses import dataclass

# 项目根目录路径
PROJECT_ROOT = Path(__file__).parent


def get_path_from_env(env_var: str, default: Path) -> Path:
    """
    从环境变量获取路径，如果未设置则使用默认值

    Args:
        env_var: 环境变量名称
        default: 默认路径

    Returns:
        Path: 配置的路径
    """
    env_value = os.getenv(env_var)
    if env_value:
        return Path(env_value)
    return default


# 配置文件路径
CONFIG_FILE = get_path_from_env(
    "FINANCEMAILPARSER_CONFIG_FILE", PROJECT_ROOT / "config.yaml"
)

# 业务规则配置文件路径（系统规则，非用户输入）
BUSINESS_RULES_FILE = get_path_from_env(
    "FINANCEMAILPARSER_BUSINESS_RULES_FILE", PROJECT_ROOT / "business_rules.yaml"
)

# 邮件存储目录
EMAILS_DIR = get_path_from_env("FINANCEMAILPARSER_EMAILS_DIR", PROJECT_ROOT / "emails")

# Beancount 输出目录
BEANCOUNT_OUTPUT_DIR = get_path_from_env(
    "FINANCEMAILPARSER_BEANCOUNT_OUTPUT_DIR", PROJECT_ROOT / "outputs" / "beancount"
)

# 日期/时间格式（集中管理）
DATE_FMT_ISO = "%Y-%m-%d"
DATE_FMT_SLASH = "%Y/%m/%d"
DATE_FMT_COMPACT = "%Y%m%d"
DATE_FMT_CN = "%Y年%m月%d日"
TIME_FMT_HMS = "%H:%M:%S"
DATETIME_FMT_ISO = "%Y-%m-%d %H:%M:%S"
DATETIME_FMT_COMPACT = "%Y%m%d_%H%M%S"

# 默认日期解析格式（供 utils/date_filter.py 使用）
DEFAULT_DATE_PARSE_FORMATS = (DATE_FMT_ISO, DATE_FMT_SLASH, DATE_FMT_COMPACT)

# Beancount 导出默认占位配置（全局一套）。
# NOTE: These placeholders keep exported entries parseable/balanced before AI fills real accounts.
BEANCOUNT_CURRENCY = "CNY"
BEANCOUNT_TODO_TOKEN = "TODO"
BEANCOUNT_DEFAULT_ASSETS_ACCOUNT = f"Assets:{BEANCOUNT_TODO_TOKEN}"
BEANCOUNT_DEFAULT_EXPENSES_ACCOUNT = f"Expenses:{BEANCOUNT_TODO_TOKEN}"
BEANCOUNT_DEFAULT_INCOME_ACCOUNT = f"Income:{BEANCOUNT_TODO_TOKEN}"

# 脱敏映射目录
MASK_MAP_DIR = get_path_from_env(
    "FINANCEMAILPARSER_MASK_MAP_DIR", PROJECT_ROOT / "outputs" / "mask_maps"
)

# 交易记录输出文件
TRANSACTIONS_CSV = get_path_from_env(
    "FINANCEMAILPARSER_TRANSACTIONS_CSV", PROJECT_ROOT / "transactions.csv"
)

# ==================== 内部约定字符串（跨模块共享） ====================

# 邮件落盘文件名（emails/ 下每个账单目录的标准文件名）
EMAIL_METADATA_FILENAME = "metadata.json"
EMAIL_HTML_FILENAME = "content.html"
EMAIL_TEXT_FILENAME = "content.txt"
EMAIL_PARSED_RESULT_FILENAME = "parsed_result.json"

# ==================== 运行参数（不可由用户配置） ====================


@dataclass(frozen=True)
class CsvParseDefaults:
    header_row: int
    encoding: str
    skip_footer: int = 0


DEFAULT_IMAP_SERVER = "imap.qq.com"
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
FALLBACK_ENCODINGS = ("utf-8", "gb18030", "big5", "iso-8859-1")

ALIPAY_CSV_DEFAULTS = CsvParseDefaults(header_row=22, encoding="gbk", skip_footer=0)
WECHAT_CSV_DEFAULTS = CsvParseDefaults(header_row=16, encoding="utf-8", skip_footer=0)
