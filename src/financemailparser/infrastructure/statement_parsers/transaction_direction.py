"""
Transaction direction helpers (income vs expense).

Conventions used across this repo:
- amount >= 0: expense (支出)
- amount < 0: income (收入)

Refund-related records must be treated as income (negative amount), otherwise
"refund pair dedup" will fail to match (it requires one positive purchase and
one negative refund with equal absolute amount).
"""

from __future__ import annotations

from typing import Iterable

# Minimal, conservative keywords indicating a refund-like incoming transaction.
# Keep this list small to avoid over-matching.
REFUND_LIKE_KEYWORDS: tuple[str, ...] = (
    "退款",
    "退货",
    "费用返还",
    "返还",
    "冲正",
)


def is_refund_like_text(text: str) -> bool:
    s = str(text or "")
    return any(k in s for k in REFUND_LIKE_KEYWORDS)


def is_refund_like_record(*fields: object) -> bool:
    """
    Determine whether a record is refund-like by scanning a small set of fields.

    This is intentionally simple: we only act when there is a clear refund hint.
    """
    combined = " ".join(str(f or "") for f in fields)
    return is_refund_like_text(combined)


def coerce_amount_by_direction(
    *,
    amount_abs: float,
    is_income: bool,
) -> float:
    """
    Convert a non-negative amount to signed amount by direction.
    """
    amt = abs(float(amount_abs))
    return -amt if is_income else amt


def normalize_amount_for_wallet_record(
    *,
    amount_raw_abs: float,
    in_out_field: str,
    refund_hint_fields: Iterable[object],
) -> float:
    """
    Normalize amount sign for digital-wallet records.

    Rules (conservative):
    - If in_out_field explicitly contains "收入": treat as income (negative)
    - Else if any refund hint field indicates refund-like: treat as income (negative)
    - Else: treat as expense (positive)
    """
    in_out = str(in_out_field or "")
    refund_like = is_refund_like_record(*list(refund_hint_fields))
    is_income = ("收入" in in_out) or refund_like
    return coerce_amount_by_direction(
        amount_abs=float(amount_raw_abs), is_income=is_income
    )
