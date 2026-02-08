import logging
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence
from datetime import datetime

from constants import EMAIL_HTML_FILENAME, EMAIL_METADATA_FILENAME
from models.txn import Transaction
from statement_parsers.abc import parse_abc_statement
from statement_parsers.alipay import parse_alipay_statement
from statement_parsers.ccb import parse_ccb_statement
from statement_parsers.ceb import parse_ceb_statement
from statement_parsers.cmb import parse_cmb_statement
from statement_parsers.wechat import parse_wechat_statement
from statement_parsers.icbc import parse_icbc_statement
from utils.bank_alias import find_bank_code_by_alias

logger = logging.getLogger(__name__)


_CREDIT_CARD_PARSER_BY_BANK_CODE: dict[str, Callable[..., List[Transaction]]] = {
    "CCB": parse_ccb_statement,
    "CMB": parse_cmb_statement,
    "CEB": parse_ceb_statement,
    "ABC": parse_abc_statement,
    "ICBC": parse_icbc_statement,
}


def find_csv_file(directory: Path) -> Optional[Path]:
    """
    递归查找目录中的CSV文件

    Args:
        directory: 要搜索的目录

    Returns:
        找到的第一个CSV文件路径，如果没找到返回None
    """
    for item in directory.rglob("*.csv"):
        return item
    return None


def parse_statement_email(
    email_folder: Path,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip_transaction: Optional[Callable[[str], bool]] = None,
    bank_alias_keywords: Optional[Mapping[str, Sequence[str]]] = None,
) -> Optional[List[Transaction]]:
    """
    解析邮件中的信用卡账单、支付宝账单和微信支付账单

    Args:
        email_folder: 邮件保存的文件夹路径
        start_date: 开始日期，如果提供则只返回该日期之后的交易
        end_date: 结束日期，如果提供则只返回该日期之前的交易

    Returns:
        解析出的交易记录列表，如果解析失败返回None
    """
    try:
        # 处理支付宝和微信支付账单
        if email_folder.name == "alipay":
            csv_file = find_csv_file(email_folder)
            if csv_file:
                logger.info(f"解析支付宝账单: {csv_file}")
                return parse_alipay_statement(
                    str(csv_file.resolve()),
                    start_date,
                    end_date,
                    skip_transaction=skip_transaction,
                    bank_alias_keywords=bank_alias_keywords,
                )
            return None

        if email_folder.name == "wechat":
            csv_file = find_csv_file(email_folder)
            if csv_file:
                logger.info(f"解析微信支付账单: {csv_file}")
                return parse_wechat_statement(
                    str(csv_file.resolve()),
                    start_date,
                    end_date,
                    skip_transaction=skip_transaction,
                    bank_alias_keywords=bank_alias_keywords,
                )
            return None

        # 处理信用卡账单
        html_file = email_folder / EMAIL_HTML_FILENAME
        if not html_file.exists():
            logger.warning(f"未找到HTML内容文件: {html_file}")
            return None

        metadata_file = email_folder / EMAIL_METADATA_FILENAME
        if not metadata_file.exists():
            logger.warning(f"未找到元数据文件: {metadata_file}")
            return None

        subject = metadata_file.read_text(encoding="utf-8")
        bank_code = find_bank_code_by_alias(
            subject, bank_alias_keywords=bank_alias_keywords
        )
        if not bank_code:
            logger.warning(f"未知的银行账单类型: {subject}")
            return None

        parser = _CREDIT_CARD_PARSER_BY_BANK_CODE.get(bank_code)
        if not parser:
            logger.warning("未找到银行代码对应的解析器: %s", bank_code)
            return None

        logger.info("解析%s账单", bank_code)
        return parser(
            str(html_file),
            start_date,
            end_date,
            skip_transaction=skip_transaction,
        )

    except Exception as e:
        logger.error(f"解析账单时出错: {str(e)}", exc_info=True)
        return None
