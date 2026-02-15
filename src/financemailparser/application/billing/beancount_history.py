"""
Beancount 历史解析结果查询与管理。

为 UI 层提供历史 Beancount 文件的扫描、读取和删除功能。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from financemailparser.infrastructure.beancount.file_manager import (
    BeancountFileInfo,
    delete_beancount_file,
    read_beancount_file,
    scan_beancount_files,
)
from financemailparser.shared.constants import BEANCOUNT_OUTPUT_DIR


@dataclass(frozen=True)
class BeancountHistoryItem:
    """供 UI 展示的 Beancount 历史文件摘要"""

    info: BeancountFileInfo
    size_kb: float
    modified_time_str: str


def list_beancount_history(
    output_dir: Path = BEANCOUNT_OUTPUT_DIR,
) -> list[BeancountHistoryItem]:
    """扫描并返回历史 Beancount 文件列表（按修改时间倒序）。"""
    file_infos = scan_beancount_files(dir=output_dir)
    items: list[BeancountHistoryItem] = []
    for info in file_infos:
        items.append(
            BeancountHistoryItem(
                info=info,
                size_kb=info.size / 1024,
                modified_time_str=datetime.fromtimestamp(info.mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )
        )
    return items


def get_beancount_file_content(path: Path) -> Optional[str]:
    """读取 Beancount 文件内容。"""
    return read_beancount_file(path)


def remove_beancount_file(path: Path) -> bool:
    """删除 Beancount 文件。"""
    return delete_beancount_file(path)


def count_transactions(content: str) -> int:
    """统计 Beancount 文本中的交易数量（以日期开头且包含 ' * ' 的行）。"""
    return sum(
        1 for line in content.splitlines() if line[:1].isdigit() and " * " in line
    )
