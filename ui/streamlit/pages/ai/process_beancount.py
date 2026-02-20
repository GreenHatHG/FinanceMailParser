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

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Optional, Any

import streamlit as st

from financemailparser.application.ai.process_beancount import (
    call_ai_completion,
    prepare_ai_process_prompts,
    read_beancount_file_for_ui,
    reconcile_masked_beancount,
    scan_beancount_files_for_ui,
    restore_amounts_and_reconcile_accounts,
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

LOCAL_PATHS_ENABLE_KEY = "ai_process_enable_local_paths"
LOCAL_PATHS_ENABLE_PREV_KEY = "ai_process_enable_local_paths_prev"
LOCAL_HISTORY_PATHS_TEXT_KEY = "ai_process_history_paths_text"
LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY = "ai_process_account_definition_path_text"

LOCAL_PATHS_HELP = (
    "提示：浏览器上传控件无法在刷新后自动回填本机文件路径；"
    "如果你希望“下次不用再选文件夹”，请使用下面的“本机绝对路径”。\n\n"
    "为保守起见：本机路径默认不自动读取；需要在本次会话勾选“启用本机路径”后才会从磁盘读取。"
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

with st.expander("添加更多数据", expanded=False):
    st.caption(LOCAL_PATHS_HELP)
    if ui_state_snap.state != "ok" and ui_state_snap.error_message:
        st.warning(f"读取已保存的本机路径失败：{ui_state_snap.error_message}")
    use_local_paths = st.checkbox(
        "启用本机路径（本次会话）",
        value=False,
        help="勾选后，本次会话会从下方保存/填写的绝对路径读取文件内容；刷新页面后需要重新勾选。",
        key=LOCAL_PATHS_ENABLE_KEY,
    )
    prev_use_local_paths = bool(
        st.session_state.get(LOCAL_PATHS_ENABLE_PREV_KEY, False)
    )
    if use_local_paths and not prev_use_local_paths and ui_state_snap.state == "ok":
        # Hydrate from persisted config.yaml on the rising edge of enabling local paths,
        # so that refresh/reconnect won't get stuck with empty session_state values.
        if not str(
            st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "") or ""
        ).strip():
            st.session_state[LOCAL_HISTORY_PATHS_TEXT_KEY] = "\n".join(
                ui_state_snap.history_paths or []
            )
        if not str(
            st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "") or ""
        ).strip():
            st.session_state[LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY] = (
                ui_state_snap.account_definition_path or ""
            )
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
                    key="ai_process_history_upload",
                    label_visibility="collapsed",
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
                key="ai_process_account_definition_upload",
            )

if uploaded_latest is not None:
    latest_summary = f"{uploaded_latest.name}（上传）"
elif selected_latest_output_info is not None:
    latest_summary = f"{selected_latest_output_info.name}（工具导出）"
else:
    latest_summary = "未选择"

local_history_paths = _parse_multiline_paths(
    st.session_state.get(LOCAL_HISTORY_PATHS_TEXT_KEY, "")
)
local_history_total = (
    len(local_history_paths)
    if bool(st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False))
    else 0
)
use_local_paths_summary = bool(st.session_state.get(LOCAL_PATHS_ENABLE_KEY, False))
history_total = (
    len(selected_history_infos) + local_history_total
    if use_local_paths_summary
    else (len(selected_history_infos) + len(uploaded_history_files))
)

summary_parts = [f"AI 处理的账单：{latest_summary}"]
if history_total > 0:
    summary_parts.append(f"历史账单（完整数据）：{history_total}")
if uploaded_account_definition is not None:
    summary_parts.append("账户定义：已上传")
else:
    local_account_definition_path = str(
        st.session_state.get(LOCAL_ACCOUNT_DEFINITION_PATH_TEXT_KEY, "") or ""
    ).strip()
    if use_local_paths_summary and local_account_definition_path:
        summary_parts.append("账户定义：本机路径（已启用）")
st.write(" ｜ ".join(summary_parts))

st.divider()


st.subheader("Prompt")

with st.expander("可选：额外规则", expanded=False):
    extra_prompt = st.text_area(
        "额外的自定义指示",
        value="",
        height=150,
        placeholder=(
            "在这里添加您的自定义规则或指示，例如：\n\n"
            "- 所有星巴克的消费都归类到 Expenses:Food:Cafe\n"
            "- 交通费用超过 100 元的归类到 Expenses:Transport:LongDistance\n"
            "- 优先使用 Expenses:Food:Restaurant 而不是 Expenses:Food:Takeout"
        ),
        help="AI 会在处理时参考这些自定义规则。留空则使用默认规则。",
        key="ai_process_extra_prompt",
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

# 显示 AI 结果（基于 session_state，而不是 send_button）
if "ai_result" in st.session_state:
    result = st.session_state["ai_result"]
    stats = result["stats"]
    latest_name = result["latest_name"]
    result_prompt_hash = result.get("prompt_masked_hash") or ""

    if (
        result_prompt_hash
        and prompt_masked_hash
        and result_prompt_hash != prompt_masked_hash
    ):
        st.warning(
            "⚠️ 你已更改文件/参数：当前 Prompt 与上次发送给 AI 的 Prompt 可能不一致，建议重新发送。"
        )

    st.subheader("AI 结果")

    if stats.success:
        with st.spinner("正在对账..."):
            reconcile_report = reconcile_masked_beancount(
                before_masked=masked_latest_content,  # 发送前的最新账单（脱敏版本）
                after_masked=stats.response,  # AI 返回的脱敏文本
            )

        tab_stats, tab_response, tab_reconcile, tab_restore = st.tabs(
            ["调用统计", "返回内容（脱敏）", "对账", "恢复金额 / 下载"]
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

        with tab_response:
            st.code(stats.response, language="beancount")

        with tab_reconcile:
            if reconcile_report.is_valid:
                st.success("✅ 对账通过：交易完整无篡改")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("发送前交易数", reconcile_report.total_before)
                with col2:
                    st.metric("返回后交易数", reconcile_report.total_after)
            else:
                st.error("❌ 对账失败：发现异常")
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
            if not reconcile_report.is_valid:
                st.warning(
                    "对账未通过：默认不允许恢复金额。你可以选择忽略继续（风险自担）。"
                )

            ignore_reconcile_failure = st.checkbox(
                "⚠️ 忽略对账失败并继续（风险）",
                value=bool(st.session_state.get("ignore_reconcile_failure", False)),
                key="ignore_reconcile_failure",
            )

            restore_disabled = (
                not reconcile_report.is_valid and not ignore_reconcile_failure
            )
            if st.button("🔓 恢复金额", width="stretch", disabled=restore_disabled):
                try:
                    masking_info = st.session_state.get("amount_masking")
                    if not masking_info:
                        st.error("❌ 未找到脱敏映射，无法恢复金额")
                    else:
                        restored_content, filling_report = (
                            restore_amounts_and_reconcile_accounts(
                                amount_masking=masking_info,
                                masked_ai_response=stats.response or "",
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

                        with st.expander("📄 处理结果（真实金额）", expanded=True):
                            st.code(restored_content, language="beancount")

                        st.download_button(
                            label="💾 下载处理后的 Beancount 文件",
                            data=restored_content,
                            file_name=f"ai_processed_{latest_name}",
                            mime="text/plain",
                            width="stretch",
                        )
                except Exception as e:
                    st.error(f"❌ 恢复金额失败：{str(e)}")

    else:
        # AI 调用失败
        st.error(f"错误信息：{stats.error_message}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("耗时", f"{stats.total_time:.2f} 秒")
        with col2:
            st.metric("重试次数", stats.retry_count)
