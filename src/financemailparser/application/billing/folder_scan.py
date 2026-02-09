from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from financemailparser.infrastructure.repositories.local_bills import (
    scan_credit_card_bill_folders,
)


def scan_downloaded_bill_folders(email_dir: Path) -> Tuple[List[Path], List[Path]]:
    """
    Scan bill folders under `emails/` and classify them.

    Returns:
        (credit_card_folders, digital_folders)
    """
    if not email_dir.exists():
        return [], []

    credit_card_folders = sorted(
        scan_credit_card_bill_folders(emails_dir=email_dir),
        key=lambda p: p.name,
    )
    digital_folders = [
        folder
        for folder in (email_dir / "alipay", email_dir / "wechat")
        if folder.is_dir()
    ]
    return credit_card_folders, digital_folders
