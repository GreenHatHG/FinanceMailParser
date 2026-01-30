"""
全局常量定义

存储项目级别的常量，供所有模块使用
"""

import os
from pathlib import Path

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

# 邮件存储目录
EMAILS_DIR = get_path_from_env("FINANCEMAILPARSER_EMAILS_DIR", PROJECT_ROOT / "emails")

# Beancount 输出目录
BEANCOUNT_OUTPUT_DIR = get_path_from_env(
    "FINANCEMAILPARSER_BEANCOUNT_OUTPUT_DIR", PROJECT_ROOT / "outputs" / "beancount"
)

# 脱敏映射目录
MASK_MAP_DIR = get_path_from_env(
    "FINANCEMAILPARSER_MASK_MAP_DIR", PROJECT_ROOT / "outputs" / "mask_maps"
)

# 交易记录输出文件
TRANSACTIONS_CSV = get_path_from_env(
    "FINANCEMAILPARSER_TRANSACTIONS_CSV", PROJECT_ROOT / "transactions.csv"
)
