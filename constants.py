"""
全局常量定义

存储项目级别的常量，供所有模块使用
"""

from pathlib import Path

# 项目根目录路径
PROJECT_ROOT = Path(__file__).parent

# 配置文件路径
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

# 邮件存储目录
EMAILS_DIR = PROJECT_ROOT / "emails"

# 交易记录输出文件
TRANSACTIONS_CSV = PROJECT_ROOT / "transactions.csv"
