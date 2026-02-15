from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence


def find_file_by_suffixes(directory: Path, suffixes: Sequence[str]) -> Optional[Path]:
    """
    Recursively find the first file whose suffix matches any of `suffixes`
    (case-insensitive).
    """
    normalized_suffixes = {str(s).lower() for s in suffixes if str(s)}
    if not normalized_suffixes:
        return None

    for item in directory.rglob("*"):
        try:
            if item.is_file() and item.suffix.lower() in normalized_suffixes:
                return item
        except OSError:
            continue
    return None


def find_latest_file_by_suffixes(
    directory: Path, suffixes: Sequence[str]
) -> Optional[Path]:
    """
    Recursively find the latest (by mtime) file whose suffix matches any of
    `suffixes` (case-insensitive).
    """
    normalized_suffixes = {str(s).lower() for s in suffixes if str(s)}
    if not normalized_suffixes:
        return None

    latest: Optional[Path] = None
    latest_mtime: Optional[float] = None

    for item in directory.rglob("*"):
        try:
            if not (item.is_file() and item.suffix.lower() in normalized_suffixes):
                continue
            mtime = item.stat().st_mtime
            if latest is None or latest_mtime is None or mtime > latest_mtime:
                latest = item
                latest_mtime = mtime
        except OSError:
            continue

    return latest
