from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from constants import EMAIL_HTML_FILENAME, EMAIL_METADATA_FILENAME


def is_digital_bill_folder(folder: Path) -> bool:
    return folder.is_dir() and folder.name in ("alipay", "wechat")


def is_credit_card_bill_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    if folder.name in ("alipay", "wechat", ".DS_Store"):
        return False
    return (folder / EMAIL_HTML_FILENAME).exists() and (
        folder / EMAIL_METADATA_FILENAME
    ).exists()


def scan_downloaded_bill_folders(email_dir: Path) -> Tuple[List[Path], List[Path]]:
    """
    Scan bill folders under `emails/` and classify them.

    Returns:
        (credit_card_folders, digital_folders)
    """
    credit_card_folders: List[Path] = []
    digital_folders: List[Path] = []

    for folder in sorted(email_dir.iterdir()):
        if is_digital_bill_folder(folder):
            digital_folders.append(folder)
            continue
        if is_credit_card_bill_folder(folder):
            credit_card_folders.append(folder)

    return credit_card_folders, digital_folders
