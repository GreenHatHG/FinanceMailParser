"""
Prompt 脱敏检查（用于发送给 AI 前的安全提示）

当前版本聚焦于“金额脱敏是否完整”：
- 从 Markdown prompt 中提取 ```beancount``` 代码块
- 使用 Beancount lexer 扫描 NUMBER + CURRENCY（同一行）模式
- 如果能扫描到真实金额 token，则认为“疑似未完全脱敏”

注意：
- 不使用完整 beancount parser 解析整段文本，因为脱敏 token `__AMT_xxx_000001__`
  不是合法数字，可能导致解析失败；lexer 更稳妥。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Tuple

from beancount.parser import lexer


_EXPONENT_ERROR_RE = re.compile(r"^[eE][+-]?\d+$")


@dataclass(frozen=True)
class PromptRedactionCheckResult:
    ok: bool
    total_issues: int
    sample_lines: Tuple[str, ...]
    code_blocks_scanned: int
    error_message: str | None = None


def _iter_markdown_code_blocks(markdown: str) -> Iterable[tuple[str | None, str]]:
    """
    A small, dependency-free Markdown code fence extractor.

    Returns:
        Iterable of (language, content) where language is lowercased or None.
    """
    if not markdown:
        return

    in_block = False
    lang: str | None = None
    buf: list[str] = []

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip("\n")

        if not in_block:
            if line.startswith("```"):
                lang_part = line[3:].strip()
                lang = lang_part.lower() if lang_part else None
                in_block = True
                buf = []
            continue

        # in block
        if line.startswith("```"):
            yield lang, "\n".join(buf)
            in_block = False
            lang = None
            buf = []
            continue

        buf.append(line)

    # Unclosed fence: ignore (avoid false positives on partial edits).


def check_prompt_redaction(prompt: str, max_samples: int = 8) -> PromptRedactionCheckResult:
    """
    Check whether the prompt likely contains unmasked amounts.

    Args:
        prompt: The final prompt that will be sent to AI (Markdown).
        max_samples: Max sample lines to include for UI display.

    Returns:
        PromptRedactionCheckResult
    """
    max_samples = int(max_samples) if max_samples and int(max_samples) > 0 else 8
    total_issues = 0
    samples: list[str] = []
    scanned = 0

    try:
        for block_index, (lang, content) in enumerate(_iter_markdown_code_blocks(prompt), start=1):
            if (lang or "").lower() != "beancount":
                continue
            scanned += 1

            lines = (content or "").splitlines()
            toks = list(lexer.lex_iter_string(content or ""))

            i = 0
            while i < len(toks):
                tok_type, lineno, lexeme, _value = toks[i]

                # Pattern A: NUMBER + CURRENCY
                if tok_type == "NUMBER" and i + 1 < len(toks):
                    next_type, next_lineno, next_lexeme, _ = toks[i + 1]
                    if next_type == "CURRENCY" and next_lineno == lineno:
                        number_str = (lexeme or b"").decode("utf-8", errors="strict")
                        currency_str = (next_lexeme or b"").decode("utf-8", errors="strict")
                        total_issues += 1

                        if len(samples) < max_samples:
                            line_text = lines[int(lineno) - 1] if 0 < int(lineno) <= len(lines) else ""
                            sanitized = (line_text or "").replace(number_str, "<AMOUNT>")
                            samples.append(
                                f"[beancount#{block_index}:{int(lineno)}] {sanitized} (hit: <AMOUNT> {currency_str})"
                            )
                        i += 2
                        continue

                # Pattern B: NUMBER + error(exponent) + CURRENCY
                if tok_type == "NUMBER" and i + 2 < len(toks):
                    mid_type, mid_lineno, mid_lexeme, _ = toks[i + 1]
                    next_type, next_lineno, next_lexeme, _ = toks[i + 2]
                    mid_text = (mid_lexeme or b"").decode("utf-8", errors="ignore") or ""
                    if (
                        mid_type == "error"
                        and mid_lineno == lineno
                        and _EXPONENT_ERROR_RE.match(mid_text) is not None
                        and next_type == "CURRENCY"
                        and next_lineno == lineno
                    ):
                        number_str = (lexeme or b"").decode("utf-8", errors="strict") + (mid_lexeme or b"").decode(
                            "utf-8", errors="strict"
                        )
                        currency_str = (next_lexeme or b"").decode("utf-8", errors="strict")
                        total_issues += 1

                        if len(samples) < max_samples:
                            line_text = lines[int(lineno) - 1] if 0 < int(lineno) <= len(lines) else ""
                            sanitized = (line_text or "").replace(number_str, "<AMOUNT>")
                            samples.append(
                                f"[beancount#{block_index}:{int(lineno)}] {sanitized} (hit: <AMOUNT> {currency_str})"
                            )
                        i += 3
                        continue

                i += 1

        return PromptRedactionCheckResult(
            ok=(total_issues == 0),
            total_issues=total_issues,
            sample_lines=tuple(samples),
            code_blocks_scanned=scanned,
            error_message=None,
        )
    except Exception as e:
        # Conservative fallback: if check fails, we don't block; UI can show "unknown".
        return PromptRedactionCheckResult(
            ok=True,
            total_issues=0,
            sample_lines=tuple(),
            code_blocks_scanned=scanned,
            error_message=str(e),
        )

