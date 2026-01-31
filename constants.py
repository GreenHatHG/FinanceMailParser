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


# ==================== 运行参数（不可由用户配置） ====================


@dataclass(frozen=True)
class CsvParseDefaults:
    header_row: int
    encoding: str
    skip_footer: int = 0


@dataclass(frozen=True)
class RuntimeDefaults:
    imap_server: str
    download_timeout_seconds: int
    fallback_encodings: tuple[str, ...]
    alipay_csv: CsvParseDefaults
    wechat_csv: CsvParseDefaults

    def validate(self) -> None:
        import codecs

        if not isinstance(self.imap_server, str) or not self.imap_server.strip():
            raise ValueError("DEFAULT_IMAP_SERVER must be non-empty str")

        if (
            not isinstance(self.download_timeout_seconds, int)
            or self.download_timeout_seconds <= 0
        ):
            raise ValueError("DEFAULT_DOWNLOAD_TIMEOUT_SECONDS must be int > 0")

        if (
            not isinstance(self.fallback_encodings, tuple)
            or not self.fallback_encodings
        ):
            raise ValueError("FALLBACK_ENCODINGS must be a non-empty tuple")

        if len(set(self.fallback_encodings)) != len(self.fallback_encodings):
            raise ValueError("FALLBACK_ENCODINGS contains duplicates")

        for enc in self.fallback_encodings:
            if not isinstance(enc, str) or not enc.strip():
                raise ValueError(f"FALLBACK_ENCODINGS contains invalid item: {enc!r}")
            codecs.lookup(enc)

        self._validate_csv_defaults("ALIPAY_CSV_DEFAULTS", self.alipay_csv)
        self._validate_csv_defaults("WECHAT_CSV_DEFAULTS", self.wechat_csv)

    @staticmethod
    def _validate_csv_defaults(label: str, value: CsvParseDefaults) -> None:
        import codecs

        if not isinstance(value.header_row, int) or value.header_row < 0:
            raise ValueError(
                f"{label}.header_row must be int >= 0, got {value.header_row!r}"
            )

        if not isinstance(value.skip_footer, int) or value.skip_footer < 0:
            raise ValueError(
                f"{label}.skip_footer must be int >= 0, got {value.skip_footer!r}"
            )

        if not isinstance(value.encoding, str) or not value.encoding.strip():
            raise ValueError(
                f"{label}.encoding must be non-empty str, got {value.encoding!r}"
            )
        codecs.lookup(value.encoding)


RUNTIME_DEFAULTS = RuntimeDefaults(
    imap_server="imap.qq.com",
    download_timeout_seconds=30,
    fallback_encodings=("utf-8", "gb18030", "big5", "iso-8859-1"),
    alipay_csv=CsvParseDefaults(header_row=22, encoding="gbk", skip_footer=0),
    wechat_csv=CsvParseDefaults(header_row=16, encoding="utf-8", skip_footer=0),
)


DEFAULT_IMAP_SERVER = RUNTIME_DEFAULTS.imap_server
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = RUNTIME_DEFAULTS.download_timeout_seconds
FALLBACK_ENCODINGS = RUNTIME_DEFAULTS.fallback_encodings
ALIPAY_CSV_DEFAULTS = RUNTIME_DEFAULTS.alipay_csv
WECHAT_CSV_DEFAULTS = RUNTIME_DEFAULTS.wechat_csv


def validate_runtime_defaults() -> None:
    RUNTIME_DEFAULTS.validate()
