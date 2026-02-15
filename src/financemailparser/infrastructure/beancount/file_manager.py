"""
Beancount 文件管理工具（ui_plan.md 2.7.1）

负责扫描 outputs/beancount 下的 .bean 文件，并提供：
- 文件信息封装（大小、修改时间、文件名日期范围）
- 文件内容读取（失败返回 None，不中断流程）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional


_DATE_RANGE_RE = re.compile(r"(?P<start>\d{8})_(?P<end>\d{8})")


def _format_yyyymmdd(value: str) -> Optional[str]:
    if not value or len(value) != 8:
        return None
    yyyy, mm, dd = value[:4], value[4:6], value[6:8]
    return f"{yyyy}-{mm}-{dd}"


def _parse_date_range_from_filename(
    filename: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    从文件名解析日期范围：
    transactions_20260101_20260129.bean -> ("2026-01-01", "2026-01-29")
    """
    match = _DATE_RANGE_RE.search(filename)
    if not match:
        return None, None
    return _format_yyyymmdd(match.group("start")), _format_yyyymmdd(match.group("end"))


@dataclass(frozen=True)
class BeancountFileInfo:
    """Beancount 文件信息封装类"""

    path: Path
    name: str
    size: int
    mtime: float
    start_date: Optional[str]
    end_date: Optional[str]

    @classmethod
    def from_path(cls, path: Path) -> "BeancountFileInfo":
        stat = path.stat()
        start_date, end_date = _parse_date_range_from_filename(path.name)
        return cls(
            path=path,
            name=path.name,
            size=int(stat.st_size),
            mtime=float(stat.st_mtime),
            start_date=start_date,
            end_date=end_date,
        )


def scan_beancount_files(dir: Path) -> list[BeancountFileInfo]:
    """
    扫描目录，返回文件列表（按文件名倒序排序，最新的在前）。
    """
    if not dir.exists() or not dir.is_dir():
        return []

    infos: list[BeancountFileInfo] = []
    for path in dir.glob("*.bean"):
        if not path.is_file():
            continue
        try:
            infos.append(BeancountFileInfo.from_path(path))
        except Exception:
            # stat 失败等情况：跳过，不中断流程
            continue

    return sorted(infos, key=lambda x: x.name, reverse=True)


def read_beancount_file(path: Path) -> Optional[str]:
    """
    读取文件内容，失败返回 None（不抛异常、不中断流程）。
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None
    except Exception:
        return None


def delete_beancount_file(path: Path) -> bool:
    """
    删除指定的 Beancount 文件。

    Returns:
        True 表示删除成功，False 表示删除失败。
    """
    try:
        path.unlink()
        return True
    except Exception:
        return False
