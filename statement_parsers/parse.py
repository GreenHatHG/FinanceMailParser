import logging
from pathlib import Path
from typing import Callable, List, Optional
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

logger = logging.getLogger(__name__)


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

        subject = metadata_file.read_text(encoding="utf-8").lower()

        if "建设银行" in subject or "ccb" in subject:
            logger.info("解析建设银行账单")
            return parse_ccb_statement(
                str(html_file),
                start_date,
                end_date,
                skip_transaction=skip_transaction,
            )

        elif "招商银行" in subject or "cmb" in subject:
            logger.info("解析招商银行账单")
            return parse_cmb_statement(
                str(html_file),
                start_date,
                end_date,
                skip_transaction=skip_transaction,
            )

        elif "光大银行" in subject or "ceb" in subject:
            logger.info("解析光大银行账单")
            return parse_ceb_statement(
                str(html_file),
                start_date,
                end_date,
                skip_transaction=skip_transaction,
            )

        elif "农业银行" in subject or "abc" in subject:
            logger.info("解析农业银行账单")
            return parse_abc_statement(
                str(html_file),
                start_date,
                end_date,
                skip_transaction=skip_transaction,
            )

        elif "工商银行" in subject or "icbc" in subject:
            logger.info("解析工商银行账单")
            return parse_icbc_statement(
                str(html_file),
                start_date,
                end_date,
                skip_transaction=skip_transaction,
            )

        else:
            logger.warning(f"未知的银行账单类型: {subject}")
            return None

    except Exception as e:
        logger.error(f"解析账单时出错: {str(e)}", exc_info=True)
        return None
