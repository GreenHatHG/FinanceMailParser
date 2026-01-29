"""
Beancount 对账工具（ui_plan.md 2.7.4）

功能：
- 解析 Beancount 文本为结构化交易对象
- 对比 AI 处理前后的交易列表
- 检测缺失、篡改、异常新增的交易
- 生成详细的对账报告
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional, Dict, Tuple


# Beancount 交易日期行正则：2024-02-15 * "描述"
_TRANSACTION_DATE_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})\s+[*!]\s+"(?P<description>[^"]*)"',
    re.MULTILINE
)

# 金额行正则：匹配账户和金额（包括脱敏 token）
# 示例：  Liabilities:CreditCard:CMB  -100.00 CNY
# 示例：  Liabilities:CreditCard:CMB  -__AMT_xxx_000001__ CNY
_AMOUNT_LINE_RE = re.compile(
    r'^\s+(?P<account>[A-Za-z][A-Za-z0-9:_-]*)\s+(?P<sign>[+-]?)(?P<amount>[\d.]+|__AMT_[A-Za-z0-9]+_\d{6}__)\s+(?P<currency>[A-Z]{3})',
    re.MULTILINE
)


@dataclass(frozen=True)
class BeancountTransaction:
    """Beancount 交易数据类"""
    date: str                    # 交易日期（YYYY-MM-DD）
    description: str             # 交易描述
    amounts: Tuple[str, ...]     # 金额列表（带符号，如 "-100.00" 或 "-__AMT_xxx_000001__"）
    accounts: Tuple[str, ...]    # 账户列表

    def fingerprint(self) -> str:
        """
        生成交易指纹（用于唯一标识）。
        格式：{date}|{amounts_joined}|{description}
        """
        amounts_str = ",".join(sorted(self.amounts))
        return f"{self.date}|{amounts_str}|{self.description}"


@dataclass
class TamperedInfo:
    """篡改信息数据类"""
    before: BeancountTransaction  # 发送前的交易
    after: BeancountTransaction   # AI 返回后的交易
    reason: str                   # 篡改原因


@dataclass
class ReconcileReport:
    """对账报告数据类"""
    total_before: int                      # 发送前交易数
    total_after: int                       # AI 返回后交易数
    missing: List[BeancountTransaction]    # 缺失的交易
    tampered: List[TamperedInfo]           # 被篡改的交易
    added: List[BeancountTransaction]      # 异常新增的交易
    is_valid: bool                         # 是否通过校验
    error_message: Optional[str]           # 错误信息


class BeancountReconciler:
    """Beancount 对账器"""

    def parse_transactions(self, text: str) -> List[BeancountTransaction]:
        """
        解析 Beancount 文本为交易对象列表。

        Args:
            text: Beancount 文本

        Returns:
            交易对象列表
        """
        if not text:
            return []

        transactions: List[BeancountTransaction] = []
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]

            # 匹配交易日期行
            match = _TRANSACTION_DATE_RE.match(line)
            if not match:
                i += 1
                continue

            date = match.group('date')
            description = match.group('description')

            # 提取后续的金额行（直到遇到空行或下一个交易）
            amounts: List[str] = []
            accounts: List[str] = []
            i += 1

            while i < len(lines):
                amount_line = lines[i]

                # 空行或下一个交易 -> 结束当前交易
                if not amount_line.strip() or _TRANSACTION_DATE_RE.match(amount_line):
                    break

                # 匹配金额行
                amount_match = _AMOUNT_LINE_RE.match(amount_line)
                if amount_match:
                    account = amount_match.group('account')
                    sign = amount_match.group('sign')
                    amount = amount_match.group('amount')
                    currency = amount_match.group('currency')

                    # 构建完整金额字符串（带符号和币种）
                    full_amount = f"{sign}{amount} {currency}"
                    amounts.append(full_amount)
                    accounts.append(account)

                i += 1

            # 创建交易对象
            if amounts:  # 只有包含金额的交易才记录
                txn = BeancountTransaction(
                    date=date,
                    description=description,
                    amounts=tuple(amounts),
                    accounts=tuple(accounts)
                )
                transactions.append(txn)

        return transactions

    def reconcile(self, before_text: str, after_text: str) -> ReconcileReport:
        """
        对账主函数：比对 AI 处理前后的交易列表。

        Args:
            before_text: 发送前的 Beancount 文本（脱敏版本）
            after_text: AI 返回的 Beancount 文本（脱敏版本）

        Returns:
            对账报告
        """
        try:
            # 解析前后交易列表
            before_txns = self.parse_transactions(before_text)
            after_txns = self.parse_transactions(after_text)

            # 构建指纹映射（用于快速查找）
            before_map: Dict[str, BeancountTransaction] = {
                txn.fingerprint(): txn for txn in before_txns
            }
            after_map: Dict[str, BeancountTransaction] = {
                txn.fingerprint(): txn for txn in after_txns
            }

            # 检测缺失的交易（前有后无）
            missing: List[BeancountTransaction] = []
            for fp, txn in before_map.items():
                if fp not in after_map:
                    missing.append(txn)

            # 检测异常新增的交易（前无后有）
            added: List[BeancountTransaction] = []
            for fp, txn in after_map.items():
                if fp not in before_map:
                    added.append(txn)

            # 检测篡改（指纹不同但日期+描述相同的交易）
            tampered: List[TamperedInfo] = []
            # TODO: 这里可以实现更复杂的篡改检测逻辑
            # 目前通过指纹已经能检测到金额变化

            # 判断是否通过校验
            is_valid = len(missing) == 0 and len(added) == 0 and len(tampered) == 0

            return ReconcileReport(
                total_before=len(before_txns),
                total_after=len(after_txns),
                missing=missing,
                tampered=tampered,
                added=added,
                is_valid=is_valid,
                error_message=None if is_valid else "发现交易差异"
            )

        except Exception as e:
            # 解析失败 -> 返回错误报告
            return ReconcileReport(
                total_before=0,
                total_after=0,
                missing=[],
                tampered=[],
                added=[],
                is_valid=False,
                error_message=f"解析失败：{str(e)}"
            )


def reconcile_beancount(before_text: str, after_text: str) -> ReconcileReport:
    """
    便捷函数：对账 Beancount 文本。

    Args:
        before_text: 发送前的 Beancount 文本
        after_text: AI 返回的 Beancount 文本

    Returns:
        对账报告
    """
    reconciler = BeancountReconciler()
    return reconciler.reconcile(before_text, after_text)
