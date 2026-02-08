from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from constants import EMAIL_HTML_FILENAME, EMAIL_METADATA_FILENAME


def scan_credit_card_bill_folders(
    *,
    emails_dir: Path,
) -> list[Path]:
    if not emails_dir.exists():
        return []

    folders: list[Path] = []
    for folder in emails_dir.iterdir():
        if not folder.is_dir():
            continue
        if folder.name in ("alipay", "wechat", ".DS_Store"):
            continue

        metadata_path = folder / EMAIL_METADATA_FILENAME
        html_path = folder / EMAIL_HTML_FILENAME
        if not metadata_path.exists() or not html_path.exists():
            continue

        folders.append(folder)

    return folders


def read_bill_metadata_json(
    *,
    metadata_path: Path,
    on_warning: Optional[Callable[[str], None]] = None,
) -> Optional[dict[str, Any]]:
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as e:
        if on_warning:
            on_warning(f"读取账单元数据失败：{metadata_path}（{str(e)}）")
        return None


def read_bill_html_text(
    *,
    html_path: Path,
    on_warning: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    try:
        return html_path.read_text(encoding="utf-8")
    except Exception as e:
        if on_warning:
            on_warning(f"读取账单 HTML 失败：{html_path}（{str(e)}）")
        return None
