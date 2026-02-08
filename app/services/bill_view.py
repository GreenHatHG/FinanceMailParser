from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from constants import (
    DATE_FMT_COMPACT,
    EMAILS_DIR,
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)
from config.business_rules import get_bank_alias_keywords
from data_source.local_fs.bills_repo import (
    read_bill_html_text,
    read_bill_metadata_json,
    scan_credit_card_bill_folders,
)
from utils.bank_alias import (
    build_bank_alias_keywords,
    build_bank_display_names,
    find_bank_code_by_alias,
)

logger = logging.getLogger(__name__)


def _get_bank_name_from_subject(
    subject: str,
    *,
    bank_alias_keywords: dict[str, list[str]],
    bank_display_names: dict[str, str],
) -> str:
    bank_code = find_bank_code_by_alias(
        subject,
        bank_alias_keywords=bank_alias_keywords,
    )
    if not bank_code:
        return "其他银行"
    return bank_display_names.get(bank_code, bank_code)


def scan_credit_card_bills(
    *,
    emails_dir: Path = EMAILS_DIR,
    on_warning: Optional[Callable[[str], None]] = None,
) -> list[dict[str, Any]]:
    """
    Scan local credit-card bill folders under emails_dir and return UI-ready dicts.

    Notes:
    - This function intentionally returns dicts to minimize UI refactor cost.
    - HTML content is not loaded here to avoid unnecessary IO.
    """
    bills: list[dict[str, Any]] = []
    try:
        bank_alias_rules = get_bank_alias_keywords()
        bank_alias_keywords = build_bank_alias_keywords(bank_alias_rules)
        bank_display_names = build_bank_display_names(bank_alias_rules)
    except Exception as e:
        msg = f"读取银行别名规则失败，将显示为其他银行：{str(e)}"
        if on_warning:
            on_warning(msg)
        else:
            logger.warning(msg)
        bank_alias_keywords = {}
        bank_display_names = {}

    folders = scan_credit_card_bill_folders(emails_dir=emails_dir)
    for folder in folders:
        metadata_path = folder / EMAIL_METADATA_FILENAME
        html_path = folder / EMAIL_HTML_FILENAME

        metadata = read_bill_metadata_json(
            metadata_path=metadata_path,
            on_warning=on_warning,
        )
        if not metadata:
            continue

        try:
            date_str = folder.name[:8]
            date = datetime.strptime(date_str, DATE_FMT_COMPACT)
        except Exception as e:
            msg = f"解析账单目录日期失败：{folder.name}（{str(e)}）"
            if on_warning:
                on_warning(msg)
            else:
                logger.warning(msg)
            continue

        subject = str(metadata.get("subject", "") or "")
        bank = _get_bank_name_from_subject(
            subject,
            bank_alias_keywords=bank_alias_keywords,
            bank_display_names=bank_display_names,
        )

        bills.append(
            {
                "folder_name": folder.name,
                "date": date,
                "bank": bank,
                "subject": subject,
                "from": str(metadata.get("from", "") or ""),
                "metadata_path": metadata_path,
                "html_path": html_path,
                "size": int(metadata.get("size", 0) or 0),
            }
        )

    bills.sort(key=lambda x: x["date"], reverse=True)
    return bills


def load_bill_html(
    *,
    html_path: Path,
) -> str:
    content = read_bill_html_text(html_path=html_path, on_warning=None)
    if content is None:
        raise OSError(f"无法读取账单 HTML：{html_path}")
    return content
