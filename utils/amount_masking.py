"""
Beancount 金额脱敏/恢复（ui_plan.md 2.7.2）

目标：
- 使用 Beancount lexer 定位金额 token，只对“数字部分”做可逆替换：
  NUMBER COMMODITY -> __AMT_xxx_000001__ COMMODITY
- 保持除“数字字符”以外的内容 100% 原样（空格/缩进/注释/符号/币种等不改）

说明：
- 不做 AST 解析与重写，避免格式变化；只做“定位 + 文本替换”。
- 通过 lexer token（NUMBER/CURRENCY）来定位金额，避免正则误伤日期/编号/注释中的数字。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid
from typing import Dict, Optional, Set, Tuple

from beancount.parser import lexer


# Token 的检测（恢复/校验用）
_TOKEN_RE = re.compile(r"__AMT_[A-Za-z0-9]+_\d{6}__")
_EXPONENT_ERROR_RE = re.compile(r"^[eE][+-]?\d+$")


def generate_run_id(length: int = 10) -> str:
    """
    生成短 run_id，用于同一次脱敏会话的 token 前缀。
    """
    value = uuid.uuid4().hex
    if length <= 0:
        return value
    return value[:length]


@dataclass
class MaskingStats:
    run_id: str
    tokens_total: int


@dataclass
class RestoreReport:
    tokens_found: int
    tokens_replaced: int
    tokens_missing_mapping: Tuple[str, ...]
    tokens_remaining_after_restore: Tuple[str, ...]
    tokens_unused_in_mapping: Tuple[str, ...]


class AmountMasker:
    """
    多文件统一脱敏器：
    - 同一 run_id
    - 跨文件 seq 递增
    - 统一 mapping（token -> 原始数字字符串）
    """

    def __init__(self, run_id: Optional[str] = None, start_seq: int = 1) -> None:
        self.run_id = run_id or generate_run_id()
        self._seq = int(start_seq) if start_seq and int(start_seq) > 0 else 1
        self.mapping: Dict[str, str] = {}

    def _next_token(self) -> str:
        token = f"__AMT_{self.run_id}_{self._seq:06d}__"
        self._seq += 1
        return token

    def mask_text(self, text: Optional[str]) -> Optional[str]:
        """
        对单段 Beancount 文本进行金额脱敏，返回脱敏后的文本。
        - 使用 beancount lexer 定位 (NUMBER[, exponent]) + CURRENCY 的片段
        - 仅替换数字字符串本身，不动正负号/空白/币种/其他文本
        """
        if text is None:
            return None

        # 1) 用 lexer 生成 token 流，抽取“金额数字字符串 + 币种”出现序列（按原文顺序）
        # token: (type, lineno, lexeme_bytes, value)
        operations_by_line: dict[int, list[tuple[str, str]]] = {}
        try:
            toks = list(lexer.lex_iter_string(text))
        except Exception:
            toks = []

        i = 0
        while i < len(toks):
            tok_type, lineno, lexeme, _value = toks[i]

            # Pattern A: NUMBER + CURRENCY
            if tok_type == "NUMBER" and i + 1 < len(toks):
                next_type, next_lineno, next_lexeme, _ = toks[i + 1]
                if next_type == "CURRENCY" and next_lineno == lineno:
                    number_str = (lexeme or b"").decode("utf-8", errors="strict")
                    currency_str = (next_lexeme or b"").decode("utf-8", errors="strict")
                    operations_by_line.setdefault(int(lineno), []).append((number_str, currency_str))
                    i += 2
                    continue

            # Pattern B: NUMBER + error(exponent) + CURRENCY
            # 兼容一些非标准输入里出现的科学计数法（lexer 会把 exponent 作为 error token）。
            if tok_type == "NUMBER" and i + 2 < len(toks):
                mid_type, mid_lineno, mid_lexeme, _ = toks[i + 1]
                next_type, next_lineno, next_lexeme, _ = toks[i + 2]
                if (
                    mid_type == "error"
                    and mid_lineno == lineno
                    and _EXPONENT_ERROR_RE.match((mid_lexeme or b"").decode("utf-8", errors="ignore") or "") is not None
                    and next_type == "CURRENCY"
                    and next_lineno == lineno
                ):
                    number_str = (lexeme or b"").decode("utf-8", errors="strict") + (mid_lexeme or b"").decode(
                        "utf-8", errors="strict"
                    )
                    currency_str = (next_lexeme or b"").decode("utf-8", errors="strict")
                    operations_by_line.setdefault(int(lineno), []).append((number_str, currency_str))
                    i += 3
                    continue

            i += 1

        if not operations_by_line:
            return text

        # 2) 在原始文本逐行做“数字字符串”替换（不改动其他字符）
        lines = text.splitlines(keepends=True)
        out_lines: list[str] = []
        for line_index, line in enumerate(lines, start=1):
            ops = operations_by_line.get(line_index)
            if not ops:
                out_lines.append(line)
                continue

            cursor = 0
            buf: list[str] = []
            for number_str, currency_str in ops:
                pattern = re.compile(re.escape(number_str) + r"(?P<space>\s+)" + re.escape(currency_str))
                match = pattern.search(line, pos=cursor)
                if match is None:
                    continue

                token = self._next_token()
                self.mapping[token] = number_str

                start = match.start()
                buf.append(line[cursor:start])
                buf.append(token)
                cursor = start + len(number_str)

            buf.append(line[cursor:])
            out_lines.append("".join(buf))

        return "".join(out_lines)

    def stats(self) -> MaskingStats:
        return MaskingStats(run_id=self.run_id, tokens_total=len(self.mapping))


def mask_beancount_amounts(text: str, run_id: Optional[str] = None) -> Tuple[str, Dict[str, str], MaskingStats]:
    """
    便捷函数：对单段文本脱敏，并返回 mapping 与统计信息。
    """
    masker = AmountMasker(run_id=run_id)
    masked = masker.mask_text(text) or ""
    return masked, dict(masker.mapping), masker.stats()


def find_amount_tokens(text: str) -> Tuple[str, ...]:
    """
    提取文本中所有金额 token（按出现顺序去重）。
    """
    seen: Set[str] = set()
    ordered: list[str] = []
    for token in _TOKEN_RE.findall(text or ""):
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return tuple(ordered)


def restore_beancount_amounts(text: str, mapping: Dict[str, str]) -> Tuple[str, RestoreReport]:
    """
    对 AI 输出（或任意文本）进行金额恢复：
    - 将 token 替换为原始数字字符串（不包含正负号/币种，正负号保留在 token 外）
    - 输出恢复报告，用于 UI 提示与失败 fast
    """
    text = text or ""
    mapping = mapping or {}

    tokens_in_text = find_amount_tokens(text)
    tokens_in_text_set = set(tokens_in_text)

    missing: list[str] = []
    replaced = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal replaced
        token = match.group(0)
        original = mapping.get(token)
        if original is None:
            missing.append(token)
            return token
        replaced += 1
        return original

    restored = _TOKEN_RE.sub(_repl, text)
    remaining = find_amount_tokens(restored)
    unused = sorted(set(mapping.keys()) - tokens_in_text_set)

    report = RestoreReport(
        tokens_found=len(tokens_in_text),
        tokens_replaced=replaced,
        tokens_missing_mapping=tuple(missing),
        tokens_remaining_after_restore=tuple(remaining),
        tokens_unused_in_mapping=tuple(unused),
    )
    return restored, report
