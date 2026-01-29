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

    def fingerprint_without_accounts(self) -> str:
        """
        生成不包含账户的指纹（用于对账金额恢复）。
        格式：{date}|{amounts_joined}|{description}

        注意：这个方法和 fingerprint() 目前是一样的，
        因为 fingerprint() 本来就不包含账户信息。
        保留这个方法是为了语义清晰。
        """
        return self.fingerprint()


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


@dataclass
class AccountFillingReport:
    """账户填充对账报告数据类"""
    total_transactions: int                # 总交易数
    matched_transactions: int              # 匹配成功的交易数
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


    def reconcile_account_filling(
        self,
        original_text: str,
        restored_text: str
    ) -> AccountFillingReport:
        """
        对账账户填充：检查恢复金额后的 Beancount 是否保持日期、金额、描述不变。

        只检查日期、金额、描述是否一致，不检查账户变化。

        Args:
            original_text: 原始的 Beancount 文本（未脱敏）
            restored_text: 恢复金额后的 Beancount 文本

        Returns:
            账户填充对账报告
        """
        try:
            # 解析原始和恢复后的交易列表
            original_txns = self.parse_transactions(original_text)
            restored_txns = self.parse_transactions(restored_text)

            # 检查交易数量是否一致
            if len(original_txns) != len(restored_txns):
                return AccountFillingReport(
                    total_transactions=len(original_txns),
                    matched_transactions=0,
                    is_valid=False,
                    error_message=f"交易数量不一致：原始 {len(original_txns)} 笔，恢复后 {len(restored_txns)} 笔"
                )

            # 构建指纹映射（只包含日期、金额、描述）
            original_map: Dict[str, BeancountTransaction] = {
                txn.fingerprint(): txn for txn in original_txns
            }
            restored_map: Dict[str, BeancountTransaction] = {
                txn.fingerprint(): txn for txn in restored_txns
            }

            # 检查每笔交易是否都能匹配上
            matched = 0
            for fp in original_map:
                if fp in restored_map:
                    matched += 1

            # 判断是否通过校验
            is_valid = matched == len(original_txns)

            return AccountFillingReport(
                total_transactions=len(original_txns),
                matched_transactions=matched,
                is_valid=is_valid,
                error_message=None if is_valid else f"有 {len(original_txns) - matched} 笔交易的日期、金额或描述发生了变化"
            )

        except Exception as e:
            # 解析失败 -> 返回错误报告
            return AccountFillingReport(
                total_transactions=0,
                matched_transactions=0,
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
