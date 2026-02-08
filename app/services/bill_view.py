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
from data_source.local_fs.bills_repo import (
    read_bill_html_text,
    read_bill_metadata_json,
    scan_credit_card_bill_folders,
)

logger = logging.getLogger(__name__)


def _get_bank_name_from_subject(subject: str) -> str:
    subject_lower = str(subject or "").lower()

    if "招商银行" in subject or "cmbchina" in subject_lower or "cmb" in subject_lower:
        return "招商银行"
    if "建设银行" in subject or "ccb" in subject_lower or "建行" in subject:
        return "建设银行"
    if "工商银行" in subject or "icbc" in subject_lower or "工行" in subject:
        return "工商银行"
    if "农业银行" in subject or "abc" in subject_lower or "农行" in subject:
        return "农业银行"
    if (
        "光大" in subject
        or "光大银行" in subject
        or "ceb" in subject_lower
        or "everbright" in subject_lower
    ):
        return "光大银行"
    return "其他银行"


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

    folders = scan_credit_card_bill_folders(
        emails_dir=emails_dir, on_warning=on_warning
    )
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
        bank = _get_bank_name_from_subject(subject)

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
