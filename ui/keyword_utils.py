"""
UI helpers for editing keyword lists.

These helpers are used by multiple Streamlit pages to avoid duplication.
"""

from __future__ import annotations

from typing import List


def keywords_to_text(keywords: List[str]) -> str:
    """
    Convert a keyword list to multi-line text (one keyword per line).
    """
    return "\n".join([str(k).strip() for k in (keywords or []) if str(k).strip()])


def parse_keywords(text: str) -> List[str]:
    """
    Parse user input text into a keyword list.

    Rules:
    - Support comma / Chinese comma as separators
    - Also support one keyword per line
    """
    raw = str(text or "")
    raw = raw.replace("，", ",")
    raw = raw.replace(",", "\n")
    keywords: List[str] = []
    for line in raw.splitlines():
        kw = line.strip()
        if kw:
            keywords.append(kw)
    return keywords
