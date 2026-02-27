"""
AI 智能处理 Beancount 账单（ui_plan.md 2.7）

功能：
- 自动选择最新 Beancount 文件（outputs/beancount）
- 支持多选历史账单（已填充账户）
- 自动构建并预览 Prompt（默认脱敏）
- 发送前 Prompt 脱敏检查（金额）
- 调用 AI 填充账户 + 对账 + 恢复金额 + 下载
"""

from __future__ import annotations

import difflib
import hashlib
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Optional, Any

import streamlit as st

from financemailparser.infrastructure.beancount.validator import BeancountReconciler
from financemailparser.application.ai.process_beancount import (
    BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW,
    add_review_tag_to_beancount_transactions,
    call_ai_completion,
    extract_beancount_text_from_ai_output,
    prepare_ai_process_prompts,
    read_beancount_file_for_ui,
    reconcile_masked_beancount,
    scan_beancount_files_for_ui,
    restore_amounts_and_reconcile_accounts,
    summarize_beancount_totals_by_currency_for_ui,
    summarize_beancount_transaction_balances_for_ui,
)
from financemailparser.application.ai.config_facade import (
    estimate_prompt_tokens_from_ui,
    get_ai_config_ui_snapshot,
)
from financemailparser.application.ai.process_beancount_ui_state_facade import (
    clear_ai_process_beancount_account_definition_path_from_ui,
    clear_ai_process_beancount_history_paths_from_ui,
    get_ai_process_beancount_ui_state_ui_snapshot,
    save_ai_process_beancount_account_definition_path_from_ui,
    save_ai_process_beancount_history_paths_from_ui,
    save_ai_process_beancount_last_inputs_from_ui,
)
from financemailparser.shared.constants import BEANCOUNT_OUTPUT_DIR, DATETIME_FMT_ISO
from financemailparser.application.ai.prompt_builder_v2 import (
    calculate_prompt_stats_v2,
)
from financemailparser.application.ai.prompt_redaction_check import (
    check_prompt_redaction,
)

st.set_page_config(page_title="AI 处理 Beancount", page_icon="🤖", layout="wide")
st.title("🤖 AI 智能处理 Beancount 账单")
st.write(
    "选择需要给 AI 填充的账单与（可选）历史参考文件，工具将自动构建 Prompt，并发送给 AI 填充消费账户。"
)
st.divider()

AI_CALL_UI_REFRESH_INTERVAL_SECONDS = 0.2
AI_CALL_RETRY_ERROR_MAX_CHARS = 160
AI_CALL_PROGRESS_PREPARING = 0.15
AI_CALL_PROGRESS_WAITING = 0.35
AI_CALL_PROGRESS_RETRY_BASE = 0.35
AI_CALL_PROGRESS_RETRY_STEP = 0.05
AI_CALL_PROGRESS_RUNNING_MAX = 0.95

AI_CALL_STAGE_PREPARING = "准备请求"
AI_CALL_STAGE_WAITING = "等待 AI 响应"
AI_CALL_RESULT_EXPANDER_TITLE = "📄 AI 调用结果（脱敏）"
RECONCILE_RULES_CAPTION = (
    "对账基于脱敏账本：核对每笔交易的日期、描述、金额/币种是否一致；"
    "不校验账户变化（账户由 AI 填充）。"
)
RECONCILE_DIAGNOSIS_TITLE = "🔎 差异定位（小白版）"
RECONCILE_DIAGNOSIS_CAPTION = (
    "怎么看：重点看“结论”一行；下面的“原始/返回”里我用 [] 把不一样的字圈出来了。"
    "这部分只用于解释原因，不会改变对账通过/失败的规则。"
)
RECONCILE_DIAGNOSIS_MAX_CHARS_PER_SEGMENT = 60
RECONCILE_DIAGNOSIS_ADVANCED_TITLE = "高级详情（开发者向）"
RESTORE_RECONCILE_DIAGNOSIS_TITLE = "🔎 金额恢复对账差异定位（小白版）"
RESTORE_RECONCILE_DIAGNOSIS_CAPTION = (
    "怎么看：重点看“结论”一行；下面的“原始/返回”里我用 [] 把不一样的字圈出来了。"
    "这部分只用于解释原因，不会改变校验规则。"
)
RESTORE_VALIDATION_TITLE = "恢复金额后的校验"
TOTALS_VALIDATION_TITLE = "总金额校验（按币种汇总）"
BALANCE_VALIDATION_TITLE = "交易平衡校验（逐笔借贷平衡）"
RESTORE_VALIDATION_CAPTION = (
    "说明：以下校验基于真实金额文本，仅在点击“恢复金额”后计算与展示，不影响下载结果。"
    "对账关注“交易是否被改动（日期/描述/金额/币种）”；下面的校验关注“生成账本是否自洽、是否可稳定用于后续记账/报表”。"
)
TOTALS_VALIDATION_CAPTION = "总金额校验会对所有交易的 posting 金额按币种汇总，分别统计正数合计、负数合计与净额，并对比“原始 vs 恢复后”。"
BALANCE_VALIDATION_CAPTION = (
    "交易平衡校验会检查每笔交易在每个币种下 posting 金额之和是否为 0。"
    "它的目的不是再去对比原始交易的日期/备注/金额（这部分由“对账”负责），而是确保 AI 生成的每笔分录满足复式记账的借贷平衡；"
    "否则即使对账通过，下载后的账本仍可能在 Beancount/Fava 中报错或产生不可信的报表。"
    "若交易包含省略金额的 posting（隐式平衡），将标记为“无法校验”。"
)
ALLOW_RISKY_DOWNLOAD_KEY = "ai_process_allow_risky_download"
ALLOW_RISKY_DOWNLOAD_LABEL = "⚠️ 忽略校验异常仍允许下载（风险）"
ALLOW_RISKY_DOWNLOAD_HELP = (
    "默认情况下，当检测到解析警告、总金额不一致或交易不平衡时，会禁用下载，以避免保存错误账本。"
    "勾选后将允许继续下载（风险自担）。"
)

LOCAL_PATHS_ENABLE_KEY = "ai_process_enable_local_paths"
LOCAL_PATHS_ENABLE_PREV_KEY = "ai_process_enable_local_paths_prev"
LOCAL_PATHS_ENABLE_PERSIST_RESULT_KEY = "ai_process_enable_local_paths_persist_result"
LOCAL_PATHS_TITLE_LOCAL_HISTORY_NAMES_KEY = "ai_process_title_local_history_names"
LOCAL_PATHS_TITLE_LOCAL_ACCOUNT_NAME_KEY = "ai_process_title_local_account_name"
LOCAL_PATHS_TITLE_UPLOAD_HISTORY_NAMES_KEY = "ai_process_title_upload_history_names"
LOCAL_PATHS_TITLE_UPLOAD_ACCOUNT_NAME_KEY = "ai_process_title_upload_account_name"
LOCAL_HISTORY_PATHS_TEXT_KEY = "ai_process_history_paths_text"
LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY = "ai_process_account_definition_path_text"
EXTRA_PROMPT_KEY = "ai_process_extra_prompt"

HISTORY_UPLOAD_KEY = "ai_process_history_upload"
ACCOUNT_DEFINITION_UPLOAD_KEY = "ai_process_account_definition_upload"

LOCAL_PATHS_TITLE_MAX_FILENAMES = 3

LOCAL_PATHS_HELP = (
    "提示：浏览器上传控件无法在刷新后自动回填本机文件路径；"
    "如果你希望“下次不用再选文件夹”，请使用下面的“本机绝对路径”。"
)

LOCAL_HISTORY_PATHS_PLACEHOLDER = (
    "每行一个 .bean 的绝对路径，例如：\n"
    "/Users/you/Documents/bills/2026-01.bean\n"
    "/Users/you/Documents/bills/2026-02.bean"
)


def _format_metric_delta(
    current: int | float, previous: int | float | None
) -> str | None:
    if previous is None:
        return None
    try:
        current_f = float(current)
        previous_f = float(previous)
    except Exception:
        return None

    delta = current_f - previous_f
    if abs(delta) < 1e-9:
        return "0"

    if float(current).is_integer() and float(previous).is_integer():
        return f"{int(delta):+,.0f}"
    return f"{delta:+.2f}"


def _decode_uploaded_beancount(raw: bytes) -> str | None:
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8-sig")
        except Exception:
            return None


def _short_retry_error(text: str) -> str:
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return "（无）"
    if len(collapsed) <= AI_CALL_RETRY_ERROR_MAX_CHARS:
        return collapsed
    return collapsed[: AI_CALL_RETRY_ERROR_MAX_CHARS - 1] + "…"


@st.cache_data(show_spinner=False)
def _cached_read_beancount_file(path_str: str, mtime: float) -> str | None:
    # mtime 作为缓存 key 的一部分，文件变更时自动失效
    return read_beancount_file_for_ui(Path(path_str))


def _parse_multiline_paths(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        normalized = line.strip()
        if normalized:
            out.append(normalized)
    return out


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _format_filenames_for_title(filenames: list[str]) -> str:
    names = [str(x or "").strip() for x in (filenames or [])]
    names = [x for x in names if x]
    names = _dedupe_keep_order(names)
    if not names:
        return ""
    if len(names) <= LOCAL_PATHS_TITLE_MAX_FILENAMES:
        return "、".join(names)
    shown = "、".join(names[:LOCAL_PATHS_TITLE_MAX_FILENAMES])
    return f"{shown} 等 {len(names)} 个"


def _update_local_title_names_from_paths_text(paths_text: str) -> None:
    local_history_names = [
        Path(p).expanduser().name for p in _parse_multiline_paths(paths_text)
    ]
    st.session_state[LOCAL_PATHS_TITLE_LOCAL_HISTORY_NAMES_KEY] = local_history_names


def _update_local_title_account_name_from_path_text(path_text: str) -> None:
    normalized = str(path_text or "").strip()
    local_account_name = Path(normalized).expanduser().name if normalized else ""
    st.session_state[LOCAL_PATHS_TITLE_LOCAL_ACCOUNT_NAME_KEY] = local_account_name


def _update_upload_title_names_from_upload_widget() -> None:
    history_uploaded = st.session_state.get(HISTORY_UPLOAD_KEY) or []
    if not isinstance(history_uploaded, list):
        history_uploaded = []
    history_uploaded_names = [
        str(getattr(uf, "name", "") or "").strip() for uf in history_uploaded
    ]
    history_uploaded_names = [x for x in history_uploaded_names if x]
    st.session_state[LOCAL_PATHS_TITLE_UPLOAD_HISTORY_NAMES_KEY] = (
        history_uploaded_names
    )


def _update_upload_title_account_name_from_upload_widget() -> None:
    uploaded_account_definition = st.session_state.get(ACCOUNT_DEFINITION_UPLOAD_KEY)
    uploaded_account_name = str(
        getattr(uploaded_account_definition, "name", "") or ""
    ).strip()
    st.session_state[LOCAL_PATHS_TITLE_UPLOAD_ACCOUNT_NAME_KEY] = uploaded_account_name


def _format_decimal_for_ui(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized else "0"


def _build_totals_diff_rows(before: Any, after: Any) -> list[dict[str, str]]:
    before_totals = getattr(before, "totals", None) or {}
    after_totals = getattr(after, "totals", None) or {}
    currencies = sorted({*before_totals.keys(), *after_totals.keys()})
    rows: list[dict[str, str]] = []
    for currency in currencies:
        b = before_totals.get(currency)
        a = after_totals.get(currency)
        b_pos = getattr(b, "positive", 0) if b is not None else 0
        b_neg = getattr(b, "negative", 0) if b is not None else 0
        b_net = getattr(b, "net", 0) if b is not None else 0
        a_pos = getattr(a, "positive", 0) if a is not None else 0
        a_neg = getattr(a, "negative", 0) if a is not None else 0
        a_net = getattr(a, "net", 0) if a is not None else 0
        rows.append(
            {
                "币种": str(currency),
                "原始正数合计": _format_decimal_for_ui(b_pos),
                "恢复后正数合计": _format_decimal_for_ui(a_pos),
                "原始负数合计": _format_decimal_for_ui(b_neg),
                "恢复后负数合计": _format_decimal_for_ui(a_neg),
                "原始净额": _format_decimal_for_ui(b_net),
                "恢复后净额": _format_decimal_for_ui(a_net),
                "一致": "✅"
                if (b_pos == a_pos and b_neg == a_neg and b_net == a_net)
                else "❌",
            }
        )
    return rows


def _totals_reports_match(before: Any, after: Any) -> bool:
    before_totals = getattr(before, "totals", None) or {}
    after_totals = getattr(after, "totals", None) or {}
    currencies = {*(before_totals.keys()), *(after_totals.keys())}
    for currency in currencies:
        b = before_totals.get(currency)
        a = after_totals.get(currency)
        b_pos = getattr(b, "positive", 0) if b is not None else 0
        b_neg = getattr(b, "negative", 0) if b is not None else 0
        b_net = getattr(b, "net", 0) if b is not None else 0
        a_pos = getattr(a, "positive", 0) if a is not None else 0
        a_neg = getattr(a, "negative", 0) if a is not None else 0
        a_net = getattr(a, "net", 0) if a is not None else 0
        if not (b_pos == a_pos and b_neg == a_neg and b_net == a_net):
            return False
    return True


def _format_net_by_currency_for_ui(net_by_currency: Any) -> str:
    if not isinstance(net_by_currency, dict):
        return str(net_by_currency or "")
    parts: list[str] = []
    for currency in sorted(net_by_currency.keys()):
        parts.append(
            f"{currency}: {_format_decimal_for_ui(net_by_currency.get(currency))}"
        )
    return ", ".join(parts) if parts else "（无）"


def _format_unicode_char_for_ui(ch: str) -> str:
    normalized = str(ch or "")
    if not normalized:
        return "（空）"
    codepoint = f"U+{ord(normalized):04X}"
    name = unicodedata.name(normalized, "UNKNOWN")
    return f"'{normalized}' ({codepoint}, {name})"


def _txn_loose_key_for_ui(txn: Any) -> tuple[str, tuple[str, ...]]:
    date = str(getattr(txn, "date", "") or "")
    amounts = getattr(txn, "amounts", None) or ()
    try:
        amounts_sorted = tuple(sorted(str(x) for x in amounts))
    except Exception:
        amounts_sorted = (str(amounts),)
    return date, amounts_sorted


def _mark_text_diff_with_brackets_for_ui(before: str, after: str) -> tuple[str, str]:
    before_s = str(before or "")
    after_s = str(after or "")

    if before_s == after_s:
        return before_s, after_s

    matcher = difflib.SequenceMatcher(a=before_s, b=after_s)
    opcodes = matcher.get_opcodes()

    before_parts: list[str] = []
    after_parts: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            before_parts.append(before_s[i1:i2])
            after_parts.append(after_s[j1:j2])
            continue
        if tag == "insert":
            seg = after_s[j1:j2]
            after_parts.append(f"[{seg}]")
            continue
        if tag == "delete":
            seg = before_s[i1:i2]
            before_parts.append(f"[{seg}]")
            continue
        if tag == "replace":
            b_seg = before_s[i1:i2]
            a_seg = after_s[j1:j2]
            before_parts.append(f"[{b_seg}]")
            after_parts.append(f"[{a_seg}]")
            continue

    return "".join(before_parts), "".join(after_parts)


def _summarize_text_diff_for_ui(before: str, after: str) -> str:
    before_s = str(before or "")
    after_s = str(after or "")

    if before_s == after_s:
        return "结论：描述一致。"

    matcher = difflib.SequenceMatcher(a=before_s, b=after_s)
    opcodes = matcher.get_opcodes()

    inserts: list[str] = []
    deletes: list[str] = []
    replaces: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "insert":
            inserts.append(after_s[j1:j2])
        elif tag == "delete":
            deletes.append(before_s[i1:i2])
        elif tag == "replace":
            replaces.append((before_s[i1:i2], after_s[j1:j2]))

    insert_chars = sum(len(x) for x in inserts)
    delete_chars = sum(len(x) for x in deletes)
    replace_ops = len(replaces)

    if inserts and not deletes and not replaces:
        inserted = "".join(inserts)
        if insert_chars == 1:
            return f"结论：AI 在返回描述里多打了 1 个字：“{inserted}”。"
        return f"结论：AI 在返回描述里多打了 {insert_chars} 个字符：“{inserted}”。"

    if deletes and not inserts and not replaces:
        deleted = "".join(deletes)
        if delete_chars == 1:
            return f"结论：AI 在返回描述里少打了 1 个字：“{deleted}”。"
        return f"结论：AI 在返回描述里少打了 {delete_chars} 个字符：“{deleted}”。"

    if replaces and not inserts and not deletes:
        if replace_ops == 1:
            old, new = replaces[0]
            if len(old) == 1 and len(new) == 1:
                return f"结论：AI 把 “{old}” 改成了 “{new}”。"
            return f"结论：AI 把 “{old}” 改成了 “{new}”。"
        return f"结论：AI 改了 {replace_ops} 处文字（见下面 [] 标记）。"

    return "结论：AI 改动了描述（有多打/少打/替换混合），见下面 [] 标记。"


def _describe_text_diff_for_ui(before: str, after: str) -> list[str]:
    before_s = str(before or "")
    after_s = str(after or "")

    lines: list[str] = []
    if before_s == after_s:
        lines.append("描述一致。")
        return lines

    matcher = difflib.SequenceMatcher(a=before_s, b=after_s)
    opcodes = matcher.get_opcodes()

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        b_seg = before_s[i1:i2]
        a_seg = after_s[j1:j2]
        lines.append(
            f"{tag}: 原始[{i1}:{i2}] -> 返回[{j1}:{j2}]"
            f"（原始='{b_seg}'，返回='{a_seg}'）"
        )

        if tag == "replace" and len(b_seg) == len(a_seg):
            shown = min(len(b_seg), RECONCILE_DIAGNOSIS_MAX_CHARS_PER_SEGMENT)
            for offset in range(shown):
                b_ch = b_seg[offset]
                a_ch = a_seg[offset]
                if b_ch == a_ch:
                    continue
                lines.append(
                    f"  位置 {i1 + offset}: "
                    f"{_format_unicode_char_for_ui(b_ch)} -> {_format_unicode_char_for_ui(a_ch)}"
                )
            if len(b_seg) > shown:
                lines.append("  …（该片段过长，字符级明细已截断）")
            continue

        if b_seg:
            shown = min(len(b_seg), RECONCILE_DIAGNOSIS_MAX_CHARS_PER_SEGMENT)
            lines.append("  原始片段字符：")
            for offset in range(shown):
                lines.append(
                    f"    #{i1 + offset}: {_format_unicode_char_for_ui(b_seg[offset])}"
                )
            if len(b_seg) > shown:
                lines.append("    …（该片段过长，字符明细已截断）")

        if a_seg:
            shown = min(len(a_seg), RECONCILE_DIAGNOSIS_MAX_CHARS_PER_SEGMENT)
            lines.append("  返回片段字符：")
            for offset in range(shown):
                lines.append(
                    f"    #{j1 + offset}: {_format_unicode_char_for_ui(a_seg[offset])}"
                )
            if len(a_seg) > shown:
                lines.append("    …（该片段过长，字符明细已截断）")

    return lines


def _build_reconcile_diagnosis_advanced_text_for_ui_from_lists(
    missing: list[Any], added: list[Any]
) -> str:
    if not missing and not added:
        return ""

    missing_by_key: dict[tuple[str, tuple[str, ...]], list[Any]] = defaultdict(list)
    for txn in missing:
        missing_by_key[_txn_loose_key_for_ui(txn)].append(txn)

    added_by_key: dict[tuple[str, tuple[str, ...]], list[Any]] = defaultdict(list)
    for txn in added:
        added_by_key[_txn_loose_key_for_ui(txn)].append(txn)

    keys = sorted({*missing_by_key.keys(), *added_by_key.keys()})

    lines: list[str] = []
    lines.append("提示：下方“配对”仅用于解释差异点，不影响对账通过/失败的判定规则。")

    paired_groups = 0
    for date, amounts in keys:
        m_list = missing_by_key.get((date, amounts), [])
        a_list = added_by_key.get((date, amounts), [])
        if not m_list and not a_list:
            continue

        amounts_text = ", ".join(amounts) if amounts else "（无）"
        lines.append("")
        lines.append(f"日期: {date or '（未知）'}")
        lines.append(f"金额: {amounts_text}")

        if m_list and a_list:
            paired_groups += 1
            lines.append(
                f"状态: 缺失 {len(m_list)} 笔 + 异常新增 {len(a_list)} 笔（疑似同一组交易）"
            )

            # Greedy match within the group by description similarity (explanation only).
            unused_added = set(range(len(a_list)))
            for idx, m_txn in enumerate(m_list, 1):
                if not unused_added:
                    break
                m_desc = str(getattr(m_txn, "description", "") or "")
                best_j: int | None = None
                best_score = -1.0
                for j in sorted(unused_added):
                    a_desc = str(getattr(a_list[j], "description", "") or "")
                    score = difflib.SequenceMatcher(a=m_desc, b=a_desc).ratio()
                    if score > best_score:
                        best_score = score
                        best_j = j
                if best_j is None:
                    continue
                unused_added.remove(best_j)
                a_txn = a_list[best_j]
                a_desc = str(getattr(a_txn, "description", "") or "")

                lines.append("")
                lines.append(f"配对 #{idx}: 描述相似度 {best_score:.3f}")
                lines.append(f"  原始描述: {m_desc}")
                lines.append(f"  返回描述: {a_desc}")
                if m_desc != a_desc:
                    diff_lines = _describe_text_diff_for_ui(m_desc, a_desc)
                    lines.append("  描述差异：")
                    for dl in diff_lines:
                        lines.append(f"    {dl}")
                else:
                    lines.append(
                        "  描述一致（可能是重复交易导致的候选配对，仅供参考）。"
                    )

            if unused_added:
                lines.append("")
                lines.append(
                    f"未配对的异常新增: {len(unused_added)} 笔（同日期同金额，但未能与缺失逐笔配对）"
                )
                for j in sorted(unused_added):
                    a_desc = str(getattr(a_list[j], "description", "") or "")
                    lines.append(f'  - {date} * "{a_desc}"')

            if len(m_list) > len(a_list):
                lines.append("")
                lines.append(
                    f"未配对的缺失: {len(m_list) - len(a_list)} 笔（同日期同金额，但新增不足以配对）"
                )
                for m_txn in m_list[len(a_list) :]:
                    m_desc = str(getattr(m_txn, "description", "") or "")
                    lines.append(f'  - {date} * "{m_desc}"')

            continue

        if m_list:
            lines.append(
                f"状态: 仅缺失 {len(m_list)} 笔（未找到同日期同金额的异常新增候选）"
            )
            for txn in m_list:
                desc = str(getattr(txn, "description", "") or "")
                lines.append(f'  - {date} * "{desc}"')
            continue

        if a_list:
            lines.append(
                f"状态: 仅异常新增 {len(a_list)} 笔（未找到同日期同金额的缺失候选）"
            )
            for txn in a_list:
                desc = str(getattr(txn, "description", "") or "")
                lines.append(f'  - {date} * "{desc}"')
            continue

    if paired_groups == 0:
        lines.append("")
        lines.append(
            "本次未找到“同日期 + 同金额/币种”的缺失/新增配对；差异可能来自日期或金额/币种变化。"
        )

    return "\n".join(lines).strip() + "\n"


def _build_reconcile_diagnosis_simple_text_for_ui_from_lists(
    missing: list[Any], added: list[Any]
) -> str:
    if not missing and not added:
        return ""

    missing_by_key: dict[tuple[str, tuple[str, ...]], list[Any]] = defaultdict(list)
    for txn in missing:
        missing_by_key[_txn_loose_key_for_ui(txn)].append(txn)

    added_by_key: dict[tuple[str, tuple[str, ...]], list[Any]] = defaultdict(list)
    for txn in added:
        added_by_key[_txn_loose_key_for_ui(txn)].append(txn)

    keys = sorted({*missing_by_key.keys(), *added_by_key.keys()})

    lines: list[str] = []
    lines.append("提示：下面的内容只是在告诉你“哪几个字不一样”，不会改变对账结果。")
    lines.append("说明：我会把同一天、同金额的交易放在一起对比。")
    lines.append("      “原始/返回”里用 [] 圈起来的，就是不一样的地方。")

    paired_groups = 0
    for date, amounts in keys:
        m_list = missing_by_key.get((date, amounts), [])
        a_list = added_by_key.get((date, amounts), [])
        if not m_list and not a_list:
            continue

        amounts_text = ", ".join(amounts) if amounts else "（无）"
        lines.append("")
        lines.append(f"日期: {date or '（未知）'}")
        lines.append(f"金额: {amounts_text}")
        lines.append(f"原始里: {len(m_list)} 条；返回里: {len(a_list)} 条。")

        if m_list and a_list:
            paired_groups += 1

            unused_added = set(range(len(a_list)))
            for idx, m_txn in enumerate(m_list, 1):
                if not unused_added:
                    break

                m_desc = str(getattr(m_txn, "description", "") or "")
                best_j: int | None = None
                best_score = -1.0
                for j in sorted(unused_added):
                    a_desc = str(getattr(a_list[j], "description", "") or "")
                    score = difflib.SequenceMatcher(a=m_desc, b=a_desc).ratio()
                    if score > best_score:
                        best_score = score
                        best_j = j
                if best_j is None:
                    continue

                unused_added.remove(best_j)
                a_txn = a_list[best_j]
                a_desc = str(getattr(a_txn, "description", "") or "")

                before_marked, after_marked = _mark_text_diff_with_brackets_for_ui(
                    m_desc, a_desc
                )
                summary = _summarize_text_diff_for_ui(m_desc, a_desc)

                lines.append("")
                lines.append(f"对比 #{idx}: {summary}")
                lines.append(f"  原始: {before_marked}")
                lines.append(f"  返回: {after_marked}")

            if unused_added:
                lines.append("")
                lines.append(
                    f"另外还有 {len(unused_added)} 条“返回里多出来”的交易（同日期同金额）："
                )
                for j in sorted(unused_added):
                    a_desc = str(getattr(a_list[j], "description", "") or "")
                    lines.append(f'  - {date} * "{a_desc}"')

            if len(m_list) > len(a_list):
                lines.append("")
                lines.append(
                    f"另外还有 {len(m_list) - len(a_list)} 条“原始里有但返回里没了”的交易："
                )
                for m_txn in m_list[len(a_list) :]:
                    m_desc = str(getattr(m_txn, "description", "") or "")
                    lines.append(f'  - {date} * "{m_desc}"')

            continue

        if m_list and (not a_list):
            lines.append(
                "结论：这条在返回里没找到对应项（可能被删了，或日期/金额被改了）。"
            )
            for txn in m_list:
                desc = str(getattr(txn, "description", "") or "")
                lines.append(f'  - {date} * "{desc}"')
            continue

        if a_list and (not m_list):
            lines.append("结论：返回里多了一条（可能是 AI 额外生成/复制了一笔）。")
            for txn in a_list:
                desc = str(getattr(txn, "description", "") or "")
                lines.append(f'  - {date} * "{desc}"')
            continue

    if paired_groups == 0:
        lines.append("")
        lines.append(
            "本次没找到“同日期 + 同金额”的可对比对象；差异可能来自日期或金额/币种变化。"
        )

    return "\n".join(lines).strip() + "\n"


def _build_reconcile_diagnosis_texts_for_ui_from_lists(
    missing: list[Any], added: list[Any]
) -> tuple[str, str]:
    simple = _build_reconcile_diagnosis_simple_text_for_ui_from_lists(missing, added)
    advanced = _build_reconcile_diagnosis_advanced_text_for_ui_from_lists(
        missing, added
    )
    return simple, advanced


def _build_reconcile_diagnosis_texts_for_ui(reconcile_report: Any) -> tuple[str, str]:
    missing = getattr(reconcile_report, "missing", None) or []
    added = getattr(reconcile_report, "added", None) or []
    return _build_reconcile_diagnosis_texts_for_ui_from_lists(missing, added)


def _compute_multiset_reconcile_diff_for_ui(
    *, before_text: str, after_text: str
) -> tuple[list[Any], list[Any]]:
    """
    Compute missing/added transactions by fingerprint as a multiset (Counter).

    This is for UI diagnosis only and does not affect pass/fail rules.
    """
    reconciler = BeancountReconciler()
    before_txns = reconciler.parse_transactions(before_text or "")
    after_txns = reconciler.parse_transactions(after_text or "")

    before_fps = [t.fingerprint() for t in before_txns]
    after_fps = [t.fingerprint() for t in after_txns]
    before_counter = Counter(before_fps)
    after_counter = Counter(after_fps)
    missing_counts = before_counter - after_counter
    added_counts = after_counter - before_counter

    before_by_fp: dict[str, list[Any]] = defaultdict(list)
    for t in before_txns:
        before_by_fp[t.fingerprint()].append(t)

    after_by_fp: dict[str, list[Any]] = defaultdict(list)
    for t in after_txns:
        after_by_fp[t.fingerprint()].append(t)

    missing: list[Any] = []
    for fp in sorted(missing_counts.keys()):
        missing.extend(before_by_fp.get(fp, [])[: int(missing_counts[fp])])

    added: list[Any] = []
    for fp in sorted(added_counts.keys()):
        added.extend(after_by_fp.get(fp, [])[: int(added_counts[fp])])

    return missing, added


all_files = (
    scan_beancount_files_for_ui(BEANCOUNT_OUTPUT_DIR)
    if BEANCOUNT_OUTPUT_DIR.exists()
    else []
)


st.subheader("AI 处理的账单")

if not BEANCOUNT_OUTPUT_DIR.exists():
    st.warning("未找到 outputs/beancount 目录：你仍然可以上传本机 .bean 文件继续。")
    st.code(str(BEANCOUNT_OUTPUT_DIR))
elif not all_files:
    st.warning(
        "outputs/beancount 目录下未发现 .bean 文件：你仍然可以上传本机 .bean 文件继续。"
    )

latest_source_tab_outputs, latest_source_tab_upload = st.tabs(["工具导出", "本地文件"])

with latest_source_tab_outputs:
    selected_latest_output_info: Optional[Any] = None
    if all_files:
        output_option_to_info = {info.name: info for info in all_files}
        selected_latest_output_option = st.selectbox(
            "AI 处理的账单（outputs/beancount）",
            options=list(output_option_to_info.keys()),
            index=0,
            label_visibility="collapsed",
            key="ai_process_main_bill_outputs",
        )
        selected_latest_output_info = output_option_to_info[
            selected_latest_output_option
        ]
    else:
        st.info("当前 outputs/beancount 没有可选文件。")

with latest_source_tab_upload:
    uploaded_latest = st.file_uploader(
        "AI 处理的账单（上传 .bean）",
        type=["bean"],
        accept_multiple_files=False,
        help="上传后将优先使用上传文件作为 AI 处理的账单。",
        label_visibility="collapsed",
        key="ai_process_main_bill_upload",
    )

selected_history_infos: list = []
uploaded_history_files: list = []
uploaded_account_definition = None

ui_state_snap = get_ai_process_beancount_ui_state_ui_snapshot()
st.session_state.setdefault(LOCAL_HISTORY_PATHS_TEXT_KEY, "")
st.session_state.setdefault(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "")
st.session_state.setdefault(LOCAL_PATHS_ENABLE_PREV_KEY, False)
st.session_state.setdefault(LOCAL_PATHS_TITLE_LOCAL_HISTORY_NAMES_KEY, [])
st.session_state.setdefault(LOCAL_PATHS_TITLE_LOCAL_ACCOUNT_NAME_KEY, "")
st.session_state.setdefault(LOCAL_PATHS_TITLE_UPLOAD_HISTORY_NAMES_KEY, [])
st.session_state.setdefault(LOCAL_PATHS_TITLE_UPLOAD_ACCOUNT_NAME_KEY, "")

local_paths_enabled_preview = bool(
    st.session_state.get(
        LOCAL_PATHS_ENABLE_KEY,
        bool(ui_state_snap.enable_local_paths)
        if ui_state_snap.state == "ok"
        else False,
    )
)

if local_paths_enabled_preview and ui_state_snap.state == "ok":
    history_paths_text_preview = str(
        st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or ""
    )
    if (not history_paths_text_preview.strip()) and ui_state_snap.history_paths:
        history_paths_text_preview = "\n".join(ui_state_snap.history_paths or [])
        st.session_state[LOCAL_HISTORY_PATHS_TEXT_KEY] = history_paths_text_preview
    _update_local_title_names_from_paths_text(history_paths_text_preview)

    account_definition_path_text_preview = str(
        st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "") or ""
    )
    if (
        not account_definition_path_text_preview.strip()
    ) and ui_state_snap.account_definition_path:
        account_definition_path_text_preview = (
            ui_state_snap.account_definition_path or ""
        )
        st.session_state[LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY] = (
            account_definition_path_text_preview
        )
    _update_local_title_account_name_from_path_text(
        account_definition_path_text_preview
    )

local_history_names_preview = (
    st.session_state.get(LOCAL_PATHS_TITLE_LOCAL_HISTORY_NAMES_KEY, []) or []
)
local_account_name_preview = str(
    st.session_state.get(LOCAL_PATHS_TITLE_LOCAL_ACCOUNT_NAME_KEY, "") or ""
).strip()
history_uploaded_names_preview = (
    st.session_state.get(LOCAL_PATHS_TITLE_UPLOAD_HISTORY_NAMES_KEY, []) or []
)
account_uploaded_name_preview = str(
    st.session_state.get(LOCAL_PATHS_TITLE_UPLOAD_ACCOUNT_NAME_KEY, "") or ""
).strip()

local_paths_expander_title_parts: list[str] = []
if local_paths_enabled_preview:
    local_paths_expander_title_parts.append("本机路径：已启用")
    history_summary = _format_filenames_for_title(local_history_names_preview)
    if history_summary:
        local_paths_expander_title_parts.append(f"历史账单：{history_summary}")
    if local_account_name_preview:
        local_paths_expander_title_parts.append(
            f"账户定义：{local_account_name_preview}"
        )
else:
    history_summary = _format_filenames_for_title(history_uploaded_names_preview)
    if history_summary:
        local_paths_expander_title_parts.append(f"历史：{history_summary}")
    if account_uploaded_name_preview:
        local_paths_expander_title_parts.append(
            f"用户定义：{account_uploaded_name_preview}"
        )

local_paths_expander_title = "添加更多数据"
if local_paths_expander_title_parts:
    local_paths_expander_title += (
        "（" + " | ".join(local_paths_expander_title_parts) + "）"
    )

with st.expander(local_paths_expander_title, expanded=False):
    st.caption(LOCAL_PATHS_HELP)
    if ui_state_snap.state != "ok" and ui_state_snap.error_message:
        st.warning(f"读取已保存的本机路径失败：{ui_state_snap.error_message}")

    def _persist_local_paths_enabled_from_toggle() -> None:
        # Only persist the toggle state here. Keep extra_prompt unchanged (saved value),
        # so user edits won't be persisted unless they actually send to AI.
        snap = get_ai_process_beancount_ui_state_ui_snapshot()
        if snap.state != "ok":
            st.session_state[LOCAL_PATHS_ENABLE_PERSIST_RESULT_KEY] = {
                "ok": False,
                "message": "❌ 保存失败：读取 config.yaml 的 UI 状态失败",
            }
            return
        new_use_local_paths = bool(st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False))
        prev_use_local_paths = bool(
            st.session_state.get(LOCAL_PATHS_ENABLE_PREV_KEY, False)
        )
        if new_use_local_paths and (not prev_use_local_paths) and snap.state == "ok":
            # Hydrate from persisted config.yaml on the rising edge of enabling local paths,
            # so that refresh/reconnect won't get stuck with empty session_state values.
            if not str(
                st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or ""
            ).strip():
                st.session_state[LOCAL_HISTORY_PATHS_TEXT_KEY] = "\n".join(
                    snap.history_paths or []
                )
            if not str(
                st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "") or ""
            ).strip():
                st.session_state[LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY] = (
                    snap.account_definition_path or ""
                )
            _update_local_title_names_from_paths_text(
                str(st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or "")
            )
            _update_local_title_account_name_from_path_text(
                str(
                    st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "")
                    or ""
                )
            )
        saved_extra_prompt = str(snap.extra_prompt or "") if snap.state == "ok" else ""
        ret = save_ai_process_beancount_last_inputs_from_ui(
            enable_local_paths=bool(
                st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False)
            ),
            extra_prompt=saved_extra_prompt,
        )
        st.session_state[LOCAL_PATHS_ENABLE_PERSIST_RESULT_KEY] = {
            "ok": bool(ret.ok),
            "message": str(ret.message or ""),
        }

    use_local_paths = st.checkbox(
        "启用本机路径",
        value=local_paths_enabled_preview,
        help="勾选后，本次会话会从下方保存/填写的绝对路径读取文件内容",
        key=LOCAL_PATHS_ENABLE_KEY,
        on_change=_persist_local_paths_enabled_from_toggle,
    )
    persist_toggle_result = st.session_state.pop(
        LOCAL_PATHS_ENABLE_PERSIST_RESULT_KEY, None
    )
    if (
        isinstance(persist_toggle_result, dict)
        and (not persist_toggle_result.get("ok"))
        and persist_toggle_result.get("message")
    ):
        st.warning(str(persist_toggle_result["message"]))
    st.session_state[LOCAL_PATHS_ENABLE_PREV_KEY] = bool(use_local_paths)

    tab_reference, tab_accounts = st.tabs(
        ["历史账单（可多选）", "账户定义（Open语句）"]
    )

    with tab_reference:
        selected_history_infos = []
        if use_local_paths:
            uploaded_history_files = []

            st.write("本机绝对路径（可持久化，下次打开自动回填）")
            history_paths_text = st.text_area(
                "历史账单：本机绝对路径（每行一个）",
                height=140,
                placeholder=LOCAL_HISTORY_PATHS_PLACEHOLDER,
                key=LOCAL_HISTORY_PATHS_TEXT_KEY,
                label_visibility="collapsed",
                on_change=lambda: _update_local_title_names_from_paths_text(
                    str(st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or "")
                ),
            )
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("保存历史账单路径", key="ai_process_history_paths_save"):
                    ret = save_ai_process_beancount_history_paths_from_ui(
                        paths_text=history_paths_text
                    )
                    (st.success if ret.ok else st.error)(ret.message)
            with btn_col2:
                if st.button("清空历史账单路径", key="ai_process_history_paths_clear"):
                    ret = clear_ai_process_beancount_history_paths_from_ui()
                    if ret.ok:
                        st.session_state[LOCAL_HISTORY_PATHS_TEXT_KEY] = ""
                    (st.success if ret.ok else st.error)(ret.message)
        else:
            uploaded_history_files = (
                st.file_uploader(
                    "上传历史账单（已填充，.bean，可多选）",
                    type=["bean"],
                    accept_multiple_files=True,
                    help="可选：用于给 AI 提供已填充账户的示例。（刷新页面后仍需重新上传）",
                    key=HISTORY_UPLOAD_KEY,
                    label_visibility="collapsed",
                    on_change=_update_upload_title_names_from_upload_widget,
                )
                or []
            )

    with tab_accounts:
        if use_local_paths:
            uploaded_account_definition = None

            st.write("本机绝对路径（可持久化，下次打开自动回填）")
            account_definition_path_text = st.text_input(
                "账户定义：本机绝对路径（.bean）",
                placeholder="/Users/you/Documents/accounts.bean",
                key=LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY,
                label_visibility="collapsed",
                on_change=lambda: _update_local_title_account_name_from_path_text(
                    str(
                        st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "")
                        or ""
                    )
                ),
            )
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button(
                    "保存账户定义路径", key="ai_process_account_definition_path_save"
                ):
                    ret = save_ai_process_beancount_account_definition_path_from_ui(
                        path_text=account_definition_path_text
                    )
                    (st.success if ret.ok else st.error)(ret.message)
            with btn_col2:
                if st.button(
                    "清空账户定义路径", key="ai_process_account_definition_path_clear"
                ):
                    ret = clear_ai_process_beancount_account_definition_path_from_ui()
                    if ret.ok:
                        st.session_state[LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY] = ""
                    (st.success if ret.ok else st.error)(ret.message)
        else:
            uploaded_account_definition = st.file_uploader(
                "上传账户定义（.bean）",
                type=["bean"],
                accept_multiple_files=False,
                help="可选：包含 open 指令的账户表/主账本（用于提供完整账户列表）。（刷新页面后仍需重新上传）",
                label_visibility="collapsed",
                key=ACCOUNT_DEFINITION_UPLOAD_KEY,
                on_change=_update_upload_title_account_name_from_upload_widget,
            )

st.subheader("Prompt")

default_extra_prompt = (
    str(ui_state_snap.extra_prompt or "") if ui_state_snap.state == "ok" else ""
)
extra_prompt_preview = str(
    st.session_state.get(EXTRA_PROMPT_KEY, default_extra_prompt) or ""
).strip()
extra_rules_expander_title = "可选：额外规则"
if extra_prompt_preview:
    extra_rules_expander_title += "（已设置）"

with st.expander(extra_rules_expander_title, expanded=False):
    st.caption("提示：点击“发送到 AI”后，会缓存本次额外规则供下次使用")
    extra_prompt = st.text_area(
        "额外的自定义指示",
        value=default_extra_prompt,
        height=150,
        placeholder=(
            "在这里添加您的自定义规则或指示，例如：\n\n"
            "- 所有星巴克的消费都归类到 Expenses:Food:Cafe\n"
            "- 交通费用超过 100 元的归类到 Expenses:Transport:LongDistance\n"
            "- 优先使用 Expenses:Food:Restaurant 而不是 Expenses:Food:Takeout"
        ),
        help="AI 会在处理时参考这些自定义规则。留空则使用默认规则。",
        key=EXTRA_PROMPT_KEY,
        label_visibility="collapsed",
    )

with st.expander("高级设置", expanded=False):
    st.warning("落盘保存的映射包含真实金额，仅建议在本机可信环境使用。")
    persist_map = st.checkbox(
        "落盘保存脱敏映射（包含真实金额，敏感）",
        value=True,
        help="保存到 outputs/mask_maps/{run_id}.json，用于页面刷新/重启后仍可恢复金额。",
        key="ai_process_persist_mask_map",
    )
    strip_export_comments = st.checkbox(
        "清理导出注释（推荐）",
        value=True,
        help=(
            "发送给 AI 前移除 FinanceMailParser 导出头与 source/card_source 注释，减少噪音；"
            "下载结果也会保持不含这些标签。"
        ),
        key="ai_process_strip_export_comments",
    )
    masking_summary_placeholder = st.empty()
    masking_saved_path_placeholder = st.empty()

examples_per_transaction = st.slider(
    "每个 TODO 交易的示例数量",
    min_value=1,
    max_value=5,
    value=3,
    help="为每个待填充账户的交易提供多少个相似的历史交易作为参考（基于 TF-IDF 匹配）",
    key="ai_process_examples_per_transaction",
)

with st.spinner("正在读取文件并构建 Prompt..."):
    use_local_paths = bool(st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False))

    # 1) 确定“AI 处理的账单”：上传优先，其次 outputs 选择
    latest_name: str | None = None
    latest_content: str | None = None

    if uploaded_latest is not None:
        raw = uploaded_latest.getvalue()
        latest_fingerprint = hashlib.sha1(raw or b"").hexdigest()
        latest_content = _decode_uploaded_beancount(raw)
        latest_name = uploaded_latest.name
        if latest_content is None:
            st.error(f"上传文件无法以 UTF-8 解码：{uploaded_latest.name}")
            st.stop()
    else:
        if selected_latest_output_info is None:
            st.error("请先选择或上传一个 AI 处理的账单（.bean）。")
            st.stop()
            raise RuntimeError("Unreachable")  # For type checker
        latest_name = selected_latest_output_info.name
        latest_fingerprint = f"{selected_latest_output_info.name}:{selected_latest_output_info.mtime}:{selected_latest_output_info.size}"
        latest_content = _cached_read_beancount_file(
            str(selected_latest_output_info.path),
            selected_latest_output_info.mtime,
        )
        if latest_content is None:
            st.error(f"读取 AI 处理的账单失败：{selected_latest_output_info.name}")
            st.stop()
            raise RuntimeError("Unreachable")  # For type checker

    reference_files: list[tuple[str, str]] = []
    reference_fingerprints: list[str] = []

    # 2) 读取账户定义文件（可选）
    account_definition_content: str | None = None
    if not use_local_paths and uploaded_account_definition is not None:
        raw = uploaded_account_definition.getvalue()
        account_definition_content = _decode_uploaded_beancount(raw)
        if account_definition_content is None:
            st.warning(
                f"账户定义文件无法以 UTF-8 解码，将从历史交易中提取账户：{uploaded_account_definition.name}"
            )
    elif use_local_paths:
        account_definition_path = str(
            st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "") or ""
        ).strip()
        if account_definition_path:
            path = Path(account_definition_path).expanduser()
            try:
                stat = path.stat()
                if not path.is_file():
                    raise FileNotFoundError("not a file")
                account_definition_content = _cached_read_beancount_file(
                    str(path), float(stat.st_mtime)
                )
                if account_definition_content is None:
                    st.warning(f"读取账户定义失败（已忽略）：{path}")
            except Exception as e:
                st.warning(f"读取账户定义失败（已忽略）：{path}（{str(e)}）")

    # 3) 历史账单：outputs 多选 + 本机上传（两者合并）
    for info in selected_history_infos:
        content = _cached_read_beancount_file(str(info.path), info.mtime)
        if content is None:
            st.warning(f"读取历史账单失败，已跳过：{info.name}")
            continue
        reference_files.append((info.name, content))
        reference_fingerprints.append(f"{info.name}:{info.mtime}:{info.size}")

    if not use_local_paths:
        for uf in uploaded_history_files:
            raw = uf.getvalue()
            reference_fingerprints.append(
                f"{uf.name}:{hashlib.sha1(raw or b'').hexdigest()}"
            )
            decoded = _decode_uploaded_beancount(raw)
            if decoded is None:
                st.warning(f"上传历史账单无法以 UTF-8 解码，已跳过：{uf.name}")
                continue
            reference_files.append((uf.name, decoded))

    if use_local_paths:
        local_history_paths = _parse_multiline_paths(
            str(st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or "")
        )
        for path_str in local_history_paths:
            path = Path(path_str).expanduser()
            try:
                stat = path.stat()
                if not path.is_file():
                    raise FileNotFoundError("not a file")
                content = _cached_read_beancount_file(str(path), float(stat.st_mtime))
                if content is None:
                    st.warning(f"读取历史账单失败，已跳过：{path}")
                    continue
                reference_files.append((path.name, content))
                reference_fingerprints.append(
                    f"{path}:{float(stat.st_mtime)}:{int(stat.st_size)}"
                )
            except Exception as e:
                st.warning(f"读取历史账单失败，已跳过：{path}（{str(e)}）")

    # 4) 金额脱敏 + 5) 构建 Prompt（ui_plan.md 2.7.2 / 2.7.5）
    prep = prepare_ai_process_prompts(
        latest_name=str(latest_name),
        latest_content=latest_content or "",
        latest_fingerprint=latest_fingerprint,
        reference_files=reference_files,
        reference_fingerprints=reference_fingerprints,
        examples_per_transaction=examples_per_transaction,
        account_definition_content=account_definition_content,
        extra_prompt=extra_prompt.strip() if extra_prompt else None,
        persist_map=bool(persist_map),
        strip_export_comments=bool(strip_export_comments),
    )

    masked_latest_content = prep.masked_latest_content
    prompt_masked = prep.prompt_masked
    prompt_real = prep.prompt_real
    prompt_stats_v2 = prep.prompt_stats_v2

    masking_info = prep.amount_masking
    st.session_state["amount_masking"] = masking_info

    tokens_total = masking_info["tokens_total"]
    run_id = masking_info["run_id"]
    masking_summary_placeholder.caption(
        f"金额脱敏：{tokens_total} 处（run_id={run_id}）"
    )

    saved_map_path = masking_info["saved_path"]
    if saved_map_path:
        masking_saved_path_placeholder.caption("已保存脱敏映射：")
        masking_saved_path_placeholder.code(str(saved_map_path))

    if prep.mask_map_save_error:
        st.warning(f"脱敏映射落盘失败（不影响本次预览）：{prep.mask_map_save_error}")

show_real = st.checkbox(
    "显示真实金额（仅本地预览，不用于发送给 AI）",
    value=False,
    help="默认展示脱敏版本；勾选后会在页面上显示真实金额。",
    key="ai_process_show_real_amounts",
)

prompt_preview = prompt_real if show_real else prompt_masked
prompt_preview_label = (
    "真实金额 | 仅本地预览" if show_real else "脱敏版本 | 将发送给 AI"
)

prompt_stats = calculate_prompt_stats_v2(prompt_preview, prompt_stats_v2)
prompt_masked_hash = (
    hashlib.sha1((prompt_masked or "").encode("utf-8")).hexdigest()
    if prompt_masked
    else ""
)

previous_prompt_stats = st.session_state.get("ai_process_prompt_stats_snapshot") or {}
previous_tokens = previous_prompt_stats.get("tokens")
previous_match_quality_pct = previous_prompt_stats.get("match_quality_pct")
previous_lines = previous_prompt_stats.get("lines")
previous_account_categories = previous_prompt_stats.get("account_categories")
previous_todo_transactions = previous_prompt_stats.get("todo_transactions")
previous_example_transactions = previous_prompt_stats.get("example_transactions")

match_quality_pct: float | None = None
try:
    match_quality_mean = prompt_stats.get("match_quality_mean")
    if match_quality_mean is not None:
        match_quality_pct = float(match_quality_mean) * 100.0
except Exception:
    match_quality_pct = None

estimated_prompt_tokens = estimate_prompt_tokens_from_ui(prompt_preview)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "预计输入 Tokens（当前预览文本）",
        f"{estimated_prompt_tokens:,}" if estimated_prompt_tokens is not None else "—",
        delta=_format_metric_delta(estimated_prompt_tokens, previous_tokens)
        if estimated_prompt_tokens is not None
        else None,
    )
with col2:
    st.metric(
        "行数",
        f"{prompt_stats.get('lines', 0):,}",
        delta=_format_metric_delta(prompt_stats.get("lines", 0), previous_lines),
    )
with col3:
    _match_quality_help = (
        "匹配质量 = 所有 TODO 交易的 Top1 相似度均值 × 100%。\n"
        "相似度来自 TF-IDF + 余弦相似度（基于交易描述），Top1 表示最相似的一条历史交易。\n"
        "范围 0%~100%，越高表示示例越贴近；没有历史示例或没有 TODO 时显示 —。"
    )
    st.metric(
        "匹配质量",
        f"{match_quality_pct:.1f}%" if match_quality_pct is not None else "—",
        delta=_format_metric_delta(match_quality_pct, previous_match_quality_pct)
        if match_quality_pct is not None
        else None,
        help=_match_quality_help,
    )

col4, col5, col6 = st.columns(3)
with col4:
    st.metric(
        "可用账户",
        prompt_stats.get("account_categories", 0),
        delta=_format_metric_delta(
            prompt_stats.get("account_categories", 0), previous_account_categories
        ),
    )
with col5:
    st.metric(
        "TODO 交易",
        prompt_stats.get("todo_transactions", 0),
        delta=_format_metric_delta(
            prompt_stats.get("todo_transactions", 0), previous_todo_transactions
        ),
    )
with col6:
    st.metric(
        "示例交易",
        prompt_stats.get("example_transactions", 0),
        delta=_format_metric_delta(
            prompt_stats.get("example_transactions", 0), previous_example_transactions
        ),
    )

# 大小提示
if estimated_prompt_tokens is not None:
    if estimated_prompt_tokens > 25_000:
        st.warning(
            f"⚠️ Prompt 预计 {estimated_prompt_tokens:,} tokens（超过 25,000），可能影响 AI 处理效果或成本。"
        )
else:
    if prompt_stats.get("chars", 0) > 100_000:
        st.warning("⚠️ Prompt 超过 100KB，可能影响 AI 处理效果。")
    # tokens 无法估算时，不显示 success，避免和上方指标重复

with st.expander(f"Prompt 预览 | {prompt_preview_label}", expanded=False):
    st.code(prompt_preview, language="markdown")

st.session_state["ai_process_prompt_stats_snapshot"] = {
    "tokens": int(estimated_prompt_tokens)
    if estimated_prompt_tokens is not None
    else None,
    "chars": int(prompt_stats.get("chars", 0) or 0),
    "lines": int(prompt_stats.get("lines", 0) or 0),
    "match_quality_pct": float(match_quality_pct)
    if match_quality_pct is not None
    else None,
    "account_categories": int(prompt_stats.get("account_categories", 0) or 0),
    "todo_transactions": int(prompt_stats.get("todo_transactions", 0) or 0),
    "example_transactions": int(prompt_stats.get("example_transactions", 0) or 0),
}

st.divider()


st.subheader("发送到 AI")

redaction_check_result = check_prompt_redaction(prompt_masked or "")
redaction_checked_at = datetime.now().strftime(DATETIME_FMT_ISO)
if prompt_masked:
    _checked_at_suffix = f" ｜ 最新检查时间（本机）：{redaction_checked_at}"
    if redaction_check_result.error_message:
        st.info(
            f"Prompt 脱敏检查：未知（检查失败：{redaction_check_result.error_message}）{_checked_at_suffix}"
        )
    elif redaction_check_result.ok:
        st.success(f"Prompt 脱敏检查：通过（未发现疑似未脱敏金额）{_checked_at_suffix}")
    else:
        st.warning(
            f"Prompt 脱敏检查：疑似未完全脱敏（命中 {redaction_check_result.total_issues} 处）{_checked_at_suffix}"
        )
        st.caption(
            "提示：这可能是程序的 bug，没有脱敏完全。你仍可继续发送，但请确认风险。"
        )
        with st.expander("查看命中示例（已隐藏金额数字）", expanded=False):
            if redaction_check_result.sample_lines:
                st.code("\n".join(redaction_check_result.sample_lines))
            else:
                st.write("（暂无示例）")
else:
    st.info(
        f"Prompt 脱敏检查：—（暂无可发送的 Prompt） ｜ 最新检查时间（本机）：{redaction_checked_at}"
    )

# 检查 AI 配置
ai_snap = get_ai_config_ui_snapshot()

if not ai_snap.present:
    st.error("❌ 尚未配置 AI，请先前往「AI 配置」页面进行配置")
    st.stop()

if ai_snap.state == "missing_master_password":
    st.error(
        f"🔒 AI 配置已加密，但未设置环境变量 {ai_snap.master_password_env}，无法解锁。"
    )
    st.caption("请在启动 Streamlit 前设置该环境变量，然后重启应用。")
    st.stop()
elif ai_snap.state == "plaintext_secret":
    st.error(f"❌ {ai_snap.error_message}")
    st.caption("请前往「AI 配置」页面删除后重新设置。")
    st.stop()
elif ai_snap.state == "decrypt_failed":
    st.error(f"❌ {ai_snap.error_message}")
    st.caption("请确认主密码是否正确；若忘记主密码，只能删除配置后重新设置。")
    st.stop()
elif ai_snap.state != "ok":
    st.error(f"❌ AI 配置加载失败：{ai_snap.error_message}")
    st.stop()

st.info(f"📡 当前使用：{ai_snap.provider} | {ai_snap.model}")

# 发送按钮（点击后进入“意图发送”状态，避免在 dialog/重跑时重复触发）
send_button_clicked = st.button(
    "🤖 发送到 AI 处理",
    disabled=not prompt_masked,
    width="stretch",
    type="primary",
)

if send_button_clicked:
    st.session_state["ai_process_send_intent"] = True
    st.session_state["ai_process_force_send"] = False
    st.session_state["ai_process_send_prompt_hash"] = prompt_masked_hash


@st.dialog("脱敏检查提示")
def _redaction_confirm_dialog() -> None:
    st.warning("检测到可能未完全脱敏的金额片段。")
    st.write("这可能是程序的 bug，没有脱敏完全。你仍然可以继续发送，但请确认风险。")
    if redaction_check_result.sample_lines:
        with st.expander("命中示例（已隐藏金额数字）", expanded=False):
            st.code("\n".join(redaction_check_result.sample_lines))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("仍然发送", type="primary", width="stretch"):
            st.session_state["ai_process_force_send"] = True
            st.rerun()
    with col2:
        if st.button("取消", width="stretch"):
            st.session_state["ai_process_send_intent"] = False
            st.session_state["ai_process_force_send"] = False
            st.session_state.pop("ai_process_send_prompt_hash", None)
            st.rerun()


should_send = bool(st.session_state.get("ai_process_send_intent"))
force_send = bool(st.session_state.get("ai_process_force_send"))
pending_hash = st.session_state.get("ai_process_send_prompt_hash")

if should_send:
    can_send_now = False
    if pending_hash and pending_hash != prompt_masked_hash:
        st.warning("⚠️ Prompt 已发生变化：请重新点击发送。")
        st.session_state["ai_process_send_intent"] = False
        st.session_state["ai_process_force_send"] = False
        st.session_state.pop("ai_process_send_prompt_hash", None)
    elif (not redaction_check_result.ok) and (not force_send):
        _redaction_confirm_dialog()
    else:
        st.session_state["ai_process_send_intent"] = False
        st.session_state["ai_process_force_send"] = False
        st.session_state.pop("ai_process_send_prompt_hash", None)
        can_send_now = True

    if can_send_now:
        # Persist the last used UI inputs only when we are actually going to call AI.
        # This avoids frequent disk writes while the user is editing widgets.
        persist_ret = save_ai_process_beancount_last_inputs_from_ui(
            enable_local_paths=bool(
                st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False)
            ),
            extra_prompt=str(st.session_state.get(EXTRA_PROMPT_KEY, "") or ""),
        )
        if not persist_ret.ok:
            st.warning(f"保存 UI 状态失败（不影响发送）：{persist_ret.message}")
        with st.status("正在调用 AI...", expanded=True) as status:
            stage_placeholder = st.empty()
            elapsed_placeholder = st.empty()
            retry_placeholder = st.empty()
            progress_placeholder = st.empty()
            progress_bar = progress_placeholder.progress(AI_CALL_PROGRESS_PREPARING)

            stage_placeholder.write(f"阶段：{AI_CALL_STAGE_PREPARING}")
            elapsed_placeholder.write("已等待 0.0 秒")

            retry_updates: Queue[tuple[int, str]] = Queue()

            def _on_retry(retry_count: int, error_summary: str) -> None:
                # Runs in worker thread. Only push data; never call Streamlit here.
                retry_updates.put((retry_count, error_summary))

            start_time = time.perf_counter()

            def _do_call():
                return call_ai_completion(
                    prompt_masked=prompt_masked or "",
                    on_retry=_on_retry,
                )

            stage_placeholder.write(f"阶段：{AI_CALL_STAGE_WAITING}")
            progress_bar.progress(AI_CALL_PROGRESS_WAITING)

            last_retry_count = 0
            last_retry_error = ""

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_call)
                while not future.done():
                    elapsed = time.perf_counter() - start_time
                    elapsed_placeholder.write(f"已等待 {elapsed:.1f} 秒")

                    while True:
                        try:
                            retry_count, error_summary = retry_updates.get_nowait()
                        except Empty:
                            break
                        last_retry_count = retry_count
                        last_retry_error = error_summary

                    if last_retry_count > 0:
                        retry_placeholder.write(
                            f"重试：第 {last_retry_count} 次（最近错误：{_short_retry_error(last_retry_error)}）"
                        )
                        progress_value = min(
                            AI_CALL_PROGRESS_RETRY_BASE
                            + AI_CALL_PROGRESS_RETRY_STEP * last_retry_count,
                            AI_CALL_PROGRESS_RUNNING_MAX,
                        )
                        progress_bar.progress(progress_value)
                    else:
                        retry_placeholder.write("")
                        progress_bar.progress(AI_CALL_PROGRESS_WAITING)

                    time.sleep(AI_CALL_UI_REFRESH_INTERVAL_SECONDS)

                call_stats = future.result()

            elapsed = time.perf_counter() - start_time
            elapsed_placeholder.write(f"已等待 {elapsed:.1f} 秒")
            progress_bar.progress(1.0)

            # Avoid UI duplication: keep only the final status label after completion.
            stage_placeholder.empty()
            elapsed_placeholder.empty()
            retry_placeholder.empty()
            progress_placeholder.empty()

            # 保存结果到 session_state
            st.session_state["ai_result"] = {
                "stats": call_stats,
                "latest_name": latest_name,
                "prompt_masked_hash": prompt_masked_hash,
            }

            if call_stats.success:
                status.update(label="✅ AI 处理完成", state="complete")
            else:
                status.update(label="❌ AI 调用失败", state="error")

            # 触发一次重跑，让页面进入“结果视图”，避免同屏重复展示结果/错误。
            st.rerun()

# 显示 AI 结果（基于 session_state，而不是 send_button）
if "ai_result" in st.session_state:
    result = st.session_state["ai_result"]
    stats = result["stats"]
    latest_name = result["latest_name"]
    result_prompt_hash = result.get("prompt_masked_hash") or ""

    raw_masked_ai_response = str(stats.response or "")
    masked_ai_response_for_processing, ai_output_normalize_note = (
        extract_beancount_text_from_ai_output(raw_masked_ai_response)
    )

    if (
        result_prompt_hash
        and prompt_masked_hash
        and result_prompt_hash != prompt_masked_hash
    ):
        st.warning(
            "⚠️ 你已更改文件/参数：当前 Prompt 与上次发送给 AI 的 Prompt 可能不一致，建议重新发送。"
        )

    st.subheader("AI 结果")

    with st.expander(AI_CALL_RESULT_EXPANDER_TITLE, expanded=not stats.success):
        if stats.success:
            if ai_output_normalize_note:
                st.info(
                    f"检测到 Markdown 输出包裹：{ai_output_normalize_note}。"
                    "后续对账/恢复/下载将使用提取后的 Beancount 纯文本。"
                )
            st.code(masked_ai_response_for_processing or "", language="beancount")
            if ai_output_normalize_note:
                with st.expander("查看原始返回（可能包含 Markdown）", expanded=False):
                    st.code(raw_masked_ai_response or "", language="text")
        else:
            st.error(f"错误信息：{stats.error_message}")

    if stats.success:
        with st.spinner("正在对账..."):
            reconcile_report = reconcile_masked_beancount(
                before_masked=masked_latest_content,  # 发送前的最新账单（脱敏版本）
                after_masked=masked_ai_response_for_processing,  # AI 返回的脱敏文本（已规范化）
            )

        tab_stats, tab_reconcile, tab_restore = st.tabs(
            ["调用统计", "对账", "恢复金额 / 下载"]
        )

        with tab_stats:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("耗时", f"{stats.total_time:.2f} 秒")
            with col2:
                st.metric("重试次数", stats.retry_count)
            with col3:
                st.metric("输入 Tokens", f"{stats.prompt_tokens:,}")
            with col4:
                st.metric("输出 Tokens", f"{stats.completion_tokens:,}")

            st.write(f"总 Tokens：{stats.total_tokens:,}")

        with tab_reconcile:
            if reconcile_report.is_valid:
                st.success("✅ 对账通过：日期/描述/金额一致（不校验账户）")
                st.caption(RECONCILE_RULES_CAPTION)
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("发送前交易数", reconcile_report.total_before)
                with col2:
                    st.metric("返回后交易数", reconcile_report.total_after)
            else:
                st.error("❌ 对账失败：发现异常")
                st.caption(RECONCILE_RULES_CAPTION)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("发送前交易数", reconcile_report.total_before)
                with col2:
                    st.metric("返回后交易数", reconcile_report.total_after)
                with col3:
                    st.metric(
                        "差异数",
                        len(reconcile_report.missing) + len(reconcile_report.added),
                    )

                if reconcile_report.error_message:
                    st.warning(f"错误信息：{reconcile_report.error_message}")

                diagnosis_simple, diagnosis_advanced = (
                    _build_reconcile_diagnosis_texts_for_ui(reconcile_report)
                )
                if diagnosis_simple or diagnosis_advanced:
                    with st.expander(RECONCILE_DIAGNOSIS_TITLE, expanded=True):
                        st.caption(RECONCILE_DIAGNOSIS_CAPTION)
                        if diagnosis_simple:
                            st.code(diagnosis_simple, language="text")
                        if diagnosis_advanced:
                            with st.expander(
                                RECONCILE_DIAGNOSIS_ADVANCED_TITLE, expanded=False
                            ):
                                st.code(diagnosis_advanced, language="text")

                if reconcile_report.missing:
                    with st.expander(
                        f"⚠️ 缺失的交易（{len(reconcile_report.missing)} 笔）",
                        expanded=True,
                    ):
                        for txn in reconcile_report.missing:
                            st.code(
                                f'{txn.date} * "{txn.description}"\n'
                                f"  金额: {', '.join(txn.amounts)}\n"
                                f"  账户: {', '.join(txn.accounts)}",
                                language="text",
                            )

                if reconcile_report.added:
                    with st.expander(
                        f"⚠️ 异常新增的交易（{len(reconcile_report.added)} 笔）",
                        expanded=True,
                    ):
                        for txn in reconcile_report.added:
                            st.code(
                                f'{txn.date} * "{txn.description}"\n'
                                f"  金额: {', '.join(txn.amounts)}\n"
                                f"  账户: {', '.join(txn.accounts)}",
                                language="text",
                            )

                if reconcile_report.tampered:
                    with st.expander(
                        f"⚠️ 被篡改的交易（{len(reconcile_report.tampered)} 笔）",
                        expanded=True,
                    ):
                        for info in reconcile_report.tampered:
                            st.markdown(
                                f'**原始：** {info.before.date} * "{info.before.description}"'
                            )
                            st.markdown(
                                f'**修改后：** {info.after.date} * "{info.after.description}"'
                            )
                            st.markdown(f"**原因：** {info.reason}")
                            st.divider()

                st.warning("⚠️ 对账失败可能导致数据不完整，请谨慎处理。")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新发送给 AI", width="stretch"):
                        st.rerun()
                with col2:
                    st.button(
                        "✏️ 手动修复",
                        width="stretch",
                        disabled=True,
                        help="功能开发中",
                    )

        with tab_restore:
            st.caption(
                "提示：恢复金额后会再次对账（核对日期/描述/金额是否与原始账本一致，不校验账户变化）。"
            )
            ignore_reconcile_failure = False
            if not reconcile_report.is_valid:
                st.warning(
                    "对账未通过：默认不允许恢复金额。你可以选择忽略继续（风险自担）。"
                )
                ignore_reconcile_failure = st.checkbox(
                    "⚠️ 忽略对账失败并继续（风险）",
                    value=bool(st.session_state.get("ignore_reconcile_failure", False)),
                    key="ignore_reconcile_failure",
                    help=(
                        "勾选后将绕过“对账未通过时禁止恢复金额”的保护。"
                        "对账失败意味着 AI 返回的交易可能存在缺失/新增/内容变化；继续恢复金额可能产出不完整或错误账本。"
                        "建议优先重新发送给 AI 或手动检查差异后再继续。"
                    ),
                )
            else:
                # Risk override is only meaningful when reconcile failed; reset it on success.
                st.session_state.pop("ignore_reconcile_failure", None)

            restore_disabled = (
                not reconcile_report.is_valid and not ignore_reconcile_failure
            )
            if st.button("🔓 恢复金额", width="stretch", disabled=restore_disabled):
                try:
                    amount_masking_info = st.session_state.get("amount_masking")
                    if not amount_masking_info:
                        st.error("❌ 未找到脱敏映射，无法恢复金额")
                    else:
                        restored_content, filling_report = (
                            restore_amounts_and_reconcile_accounts(
                                amount_masking=amount_masking_info,
                                masked_ai_response=masked_ai_response_for_processing,
                                original_beancount_text=latest_content
                                if latest_content
                                else "",
                                strip_export_comments=bool(strip_export_comments),
                            )
                        )

                        st.success("✅ 金额恢复成功")

                        if filling_report.is_valid:
                            st.success("✅ 金额恢复对账通过")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("总交易数", filling_report.total_transactions)
                            with col2:
                                st.metric(
                                    "匹配成功", filling_report.matched_transactions
                                )
                        else:
                            st.error(
                                f"❌ 金额恢复对账失败：{filling_report.error_message}"
                            )

                        original_text = latest_content or ""
                        if not filling_report.is_valid:
                            missing, added = _compute_multiset_reconcile_diff_for_ui(
                                before_text=original_text,
                                after_text=restored_content,
                            )
                            diagnosis_simple, diagnosis_advanced = (
                                _build_reconcile_diagnosis_texts_for_ui_from_lists(
                                    missing, added
                                )
                            )
                            if diagnosis_simple or diagnosis_advanced:
                                with st.expander(
                                    RESTORE_RECONCILE_DIAGNOSIS_TITLE, expanded=True
                                ):
                                    st.caption(RESTORE_RECONCILE_DIAGNOSIS_CAPTION)
                                    if diagnosis_simple:
                                        st.code(diagnosis_simple, language="text")
                                    if diagnosis_advanced:
                                        with st.expander(
                                            RECONCILE_DIAGNOSIS_ADVANCED_TITLE,
                                            expanded=False,
                                        ):
                                            st.code(diagnosis_advanced, language="text")

                        before_totals = (
                            summarize_beancount_totals_by_currency_for_ui(original_text)
                            if original_text.strip()
                            else None
                        )
                        after_totals = summarize_beancount_totals_by_currency_for_ui(
                            restored_content
                        )
                        balance_report = (
                            summarize_beancount_transaction_balances_for_ui(
                                restored_content,
                                examples_max=3,
                            )
                        )

                        totals_match = (
                            _totals_reports_match(before_totals, after_totals)
                            if before_totals is not None
                            else True
                        )
                        has_unbalanced = bool(
                            getattr(balance_report, "unbalanced", 0) > 0
                        )
                        has_parse_warning = bool(
                            getattr(after_totals, "parse_error", None)
                            or getattr(balance_report, "parse_error", None)
                        )

                        st.markdown(f"#### {RESTORE_VALIDATION_TITLE}")
                        st.caption(RESTORE_VALIDATION_CAPTION)

                        with st.expander(TOTALS_VALIDATION_TITLE, expanded=False):
                            st.caption(TOTALS_VALIDATION_CAPTION)

                            if before_totals is None:
                                st.warning(
                                    "未获取原始账本内容，无法对比“原始 vs 恢复后”的总金额。"
                                )
                            else:
                                if before_totals.parse_error:
                                    st.warning(
                                        f"原始账本解析提示：{before_totals.parse_error}"
                                    )
                                if after_totals.parse_error:
                                    st.warning(
                                        f"恢复后账本解析提示：{after_totals.parse_error}"
                                    )

                                if (
                                    before_totals.postings_without_units
                                    or after_totals.postings_without_units
                                ):
                                    st.info(
                                        "注意：存在省略金额的 posting（隐式平衡），将不会计入汇总。"
                                    )

                                (st.success if totals_match else st.error)(
                                    "✅ 总金额一致（按币种汇总）"
                                    if totals_match
                                    else "❌ 总金额不一致（按币种汇总）"
                                )
                                st.dataframe(
                                    _build_totals_diff_rows(
                                        before_totals, after_totals
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )

                        with st.expander(BALANCE_VALIDATION_TITLE, expanded=False):
                            st.caption(BALANCE_VALIDATION_CAPTION)

                            if balance_report.parse_error:
                                st.warning(
                                    f"恢复后账本解析提示：{balance_report.parse_error}"
                                )

                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("交易数", balance_report.transactions_total)
                            with col2:
                                st.metric("平衡", balance_report.balanced)
                            with col3:
                                st.metric("不平衡", balance_report.unbalanced)
                            with col4:
                                st.metric("无法校验", balance_report.unknown)

                            if balance_report.examples:
                                with st.expander("示例：不平衡的交易", expanded=False):
                                    for ex in balance_report.examples:
                                        st.code(
                                            f'{ex.date} * "{ex.description}"\n'
                                            "  净额（按币种）: "
                                            f"{_format_net_by_currency_for_ui(ex.net_by_currency)}",
                                            language="text",
                                        )

                        download_block_reasons: list[str] = []
                        if has_parse_warning:
                            download_block_reasons.append("解析存在警告/错误")
                        if (before_totals is not None) and (not totals_match):
                            download_block_reasons.append("总金额按币种汇总不一致")
                        if has_unbalanced:
                            download_block_reasons.append("存在不平衡交易")

                        allow_risky_download = False
                        if download_block_reasons:
                            st.warning(
                                "检测到潜在风险，默认禁用下载："
                                + "，".join(download_block_reasons)
                            )
                            allow_risky_download = st.checkbox(
                                ALLOW_RISKY_DOWNLOAD_LABEL,
                                value=bool(
                                    st.session_state.get(
                                        ALLOW_RISKY_DOWNLOAD_KEY, False
                                    )
                                ),
                                key=ALLOW_RISKY_DOWNLOAD_KEY,
                                help=ALLOW_RISKY_DOWNLOAD_HELP,
                            )

                        download_disabled = bool(download_block_reasons) and (
                            not allow_risky_download
                        )

                        restored_content_tagged = (
                            add_review_tag_to_beancount_transactions(restored_content)
                        )
                        st.caption(
                            f"提示：所有 AI 处理过的交易已自动追加待核对标记 {BEANCOUNT_REVIEW_TAG_NEEDS_REVIEW}；"
                            "核对完成后可手动删除该标记。"
                        )
                        with st.expander("📄 处理结果（真实金额）", expanded=True):
                            st.code(restored_content_tagged, language="beancount")

                        st.download_button(
                            label="💾 下载处理后的 Beancount 文件",
                            data=restored_content_tagged,
                            file_name=f"ai_processed_{latest_name}",
                            mime="text/plain",
                            width="stretch",
                            disabled=download_disabled,
                        )
                except Exception as e:
                    st.error(f"❌ 恢复金额失败：{str(e)}")

    else:
        # AI 调用失败
        col1, col2 = st.columns(2)
        with col1:
            st.metric("耗时", f"{stats.total_time:.2f} 秒")
        with col2:
            st.metric("重试次数", stats.retry_count)
