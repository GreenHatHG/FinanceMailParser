"""
Beancount Writer

将解析得到的 Transaction 列表导出为 Beancount 文本。

当前阶段（ui_plan.md 2.6）目标：
- 只输出“可被 beancount 解析”的基础交易结构；
- 账户先用占位账户（后续再做 AI/规则智能填充）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from utils.date_filter import parse_date_safe


@dataclass(frozen=True)
class BeancountExportOptions:
    currency: str = "CNY"
    default_assets_account: str = "Assets:TODO"
    default_expenses_account: str = "Expenses:TODO"
    default_income_account: str = "Income:TODO"
    include_source_comment: bool = True


def _escape_beancount_string(value: str) -> str:
    # beancount 字符串用双引号包裹，这里做最小转义
    return str(value).replace("\\", "\\\\").replace("\"", "\\\"").strip()


def _format_amount(amount: float) -> str:
    # 统一保留两位小数，避免 1.0 / 1.0000003 这种输出
    return f"{amount:.2f}"


def transaction_to_beancount(
    *,
    date: str,
    narration: str,
    amount: float,
    source: Optional[str] = None,
    options: BeancountExportOptions = BeancountExportOptions(),
) -> str:
    """
    把单条交易转换成 Beancount entry 字符串。

    规则（尽量通用）：
    - amount >= 0: 视为支出 -> Expenses + Assets(-)
    - amount < 0: 视为收入 -> Assets + Income(-)
    """
    date_dt = parse_date_safe(date)
    date_str = date_dt.strftime("%Y-%m-%d") if date_dt else str(date).strip()

    narration_escaped = _escape_beancount_string(narration)

    lines: list[str] = [f'{date_str} * "{narration_escaped}"']
    if options.include_source_comment and source:
        lines.append(f"  ; source: {source}")

    if amount >= 0:
        amt = float(amount)
        lines.append(f"  {options.default_expenses_account}  {_format_amount(amt)} {options.currency}")
        lines.append(f"  {options.default_assets_account}  {_format_amount(-amt)} {options.currency}")
    else:
        amt = float(-amount)
        lines.append(f"  {options.default_assets_account}  {_format_amount(amt)} {options.currency}")
        lines.append(f"  {options.default_income_account}  {_format_amount(-amt)} {options.currency}")

    return "\n".join(lines) + "\n\n"


def transactions_to_beancount(
    transactions: Iterable[object],
    options: BeancountExportOptions = BeancountExportOptions(),
    *,
    header_comment: Optional[str] = None,
) -> str:
    """
    将 transactions 转换为 Beancount 文本。

    约定：
    - transaction 对象至少提供：date / description / amount / source
    """
    chunks: list[str] = []
    if header_comment:
        for line in header_comment.splitlines():
            chunks.append(f"; {line}")
        chunks.append("\n")

    for txn in transactions:
        date = getattr(txn, "date", "")
        narration = getattr(txn, "description", "")
        amount = getattr(txn, "amount", 0.0)
        source = getattr(getattr(txn, "source", None), "value", None) or getattr(txn, "source", None)
        chunks.append(
            transaction_to_beancount(
                date=str(date),
                narration=str(narration),
                amount=float(amount),
                source=str(source) if source is not None else None,
                options=options,
            )
        )

    return "".join(chunks)

