import logging
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence
from datetime import datetime

from financemailparser.shared.constants import (
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)
from financemailparser.domain.models.txn import Transaction
from financemailparser.infrastructure.statement_parsers.banks.abc_china import (
    parse_abc_statement,
)
from financemailparser.infrastructure.statement_parsers.digital_wallets.alipay import (
    parse_alipay_statement,
)
from financemailparser.infrastructure.statement_parsers.banks.ccb import (
    parse_ccb_statement,
)
from financemailparser.infrastructure.statement_parsers.banks.ceb import (
    parse_ceb_statement,
)
from financemailparser.infrastructure.statement_parsers.banks.cmb import (
    parse_cmb_statement,
)
from financemailparser.infrastructure.statement_parsers.digital_wallets.wechat import (
    parse_wechat_statement,
)
from financemailparser.infrastructure.statement_parsers.banks.icbc import (
    parse_icbc_statement,
)
from financemailparser.domain.services.bank_alias import find_bank_code_by_alias
from financemailparser.infrastructure.repositories.file_scan import (
    find_file_by_suffixes,
)

logger = logging.getLogger(__name__)


_CREDIT_CARD_PARSER_BY_BANK_CODE: dict[str, Callable[..., List[Transaction]]] = {
    "CCB": parse_ccb_statement,
    "CMB": parse_cmb_statement,
    "CEB": parse_ceb_statement,
    "ABC": parse_abc_statement,
    "ICBC": parse_icbc_statement,
}


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
            bill_file = find_file_by_suffixes(email_folder, [".csv"])
            if bill_file:
                logger.info(f"解析支付宝账单: {bill_file}")
                return parse_alipay_statement(
                    str(bill_file.resolve()),
                    start_date,
                    end_date,
                    skip_transaction=skip_transaction,
                    bank_alias_keywords=bank_alias_keywords,
                )
            return None

        if email_folder.name == "wechat":
            bill_file = find_file_by_suffixes(email_folder, [".xlsx"])
            if bill_file:
                logger.info(f"解析微信支付账单: {bill_file}")
                return parse_wechat_statement(
                    str(bill_file.resolve()),
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
