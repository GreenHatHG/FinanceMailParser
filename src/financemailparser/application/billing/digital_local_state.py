from __future__ import annotations

from pathlib import Path
from typing import Optional

from financemailparser.infrastructure.repositories.file_scan import (
    find_file_by_suffixes,
    find_latest_file_by_suffixes,
)


def describe_local_digital_bill_state(
    provider_dir: Path,
    *,
    bill_type: str,
) -> tuple[str, Optional[Path], Optional[Path]]:
    """
    Describe the local state for a digital bill provider (alipay/wechat).

    Returns:
        (message, bill_file_path, zip_path)
    """
    if not provider_dir.exists():
        return "未发现本地目录（将尝试下载最新一封）", None, None

    bill_suffixes = [".xlsx"] if bill_type == "wechat" else [".csv"]
    bill_file = find_file_by_suffixes(provider_dir, bill_suffixes)
    if bill_file:
        return (
            "已存在账单文件（将跳过下载）",
            bill_file,
            find_latest_file_by_suffixes(provider_dir, [".zip"]),
        )

    zip_path = find_latest_file_by_suffixes(provider_dir, [".zip"])
    if zip_path:
        return (
            "未发现账单文件，但检测到 ZIP（将优先尝试解压）",
            None,
            zip_path,
        )

    return "目录存在但未发现账单文件（将尝试下载最新一封）", None, None
