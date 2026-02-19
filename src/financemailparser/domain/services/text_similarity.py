"""
Lightweight text similarity helpers for domain logic.

This module intentionally avoids heavy ML dependencies. It is designed for
high-frequency matching (e.g., refund pairing) and must remain pure:
- stdlib only
- no imports from other internal layers (application/infrastructure/shared/etc.)
"""

from __future__ import annotations

import re

# Keep the stopword list small and conservative: it should remove only very common
# boilerplate terms that otherwise inflate similarity for unrelated transactions.
_DEFAULT_STOPWORDS: tuple[str, ...] = (
    # Platforms / sources
    "支付宝",
    "微信",
    # Generic money flow terms
    "收款",
    "付款",
    "收入",
    "支出",
    "入账",
    "出账",
    # Common transaction types (too generic to help matching)
    "消费",
    "退款",
    "退货",
    "返还",
    "冲正",
    # English counterparts (keep minimal)
    "refund",
    "转账",
    "打款",
    "红包",
    "提现",
    "充值",
    "还款",
    "手续费",
    # Common boilerplate
    "交易",
    "订单",
    "订单号",
    "关联订单号",
    "关联",
)

_RE_SPACES = re.compile(r"\s+")
_RE_DIGITS = re.compile(r"\d+")
_RE_PUNCT = re.compile(r"""[\-—_:/\\|,，。．·•!！?？（）()\[\]{}<>《》"'“”‘’]""")


def normalize_text_for_similarity(
    text: str, *, stopwords: tuple[str, ...] = _DEFAULT_STOPWORDS
) -> str:
    """
    Normalize text for similarity comparison.

    Notes:
    - This is a heuristic normalization. It is meant to reduce noisy tokens such as
      platform names, digits (order IDs), and punctuation.
    - We do NOT perform segmentation; we rely on char-level bigrams.
    """
    s = str(text or "").lower()
    s = _RE_SPACES.sub("", s)
    s = _RE_DIGITS.sub("", s)
    s = _RE_PUNCT.sub("", s)
    for w in stopwords:
        if w:
            s = s.replace(w, "")
    return s.strip()


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def bigram_jaccard_similarity(a: str, b: str) -> float:
    """
    Character-bigram Jaccard similarity in [0, 1].

    We treat empty normalized strings as non-matchable (similarity=0)
    to stay conservative and avoid accidental deletion.
    """
    na = normalize_text_for_similarity(a)
    nb = normalize_text_for_similarity(b)
    if not na or not nb:
        return 0.0

    # Special-case very short texts:
    # - for single-char/single-token descriptions, bigrams are empty and would
    #   always produce 0, which breaks refund pairing on short labels.
    # - we only treat exact-equality as similar; no substring heuristics.
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 0.0

    A = _bigrams(na)
    B = _bigrams(nb)
    return float(len(A & B) / len(A | B)) if (A and B) else 0.0
