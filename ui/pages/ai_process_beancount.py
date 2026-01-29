"""
AI 智能处理 Beancount 账单（ui_plan.md 2.7.1）

功能：
- 自动选择最新 Beancount 文件（outputs/beancount）
- 支持多选历史文件作为参考库
- 构建并预览 Prompt（本次不做后端 AI 调用）
"""

from __future__ import annotations

from pathlib import Path
import re

import streamlit as st

from constants import BEANCOUNT_OUTPUT_DIR
from utils.beancount_file_manager import scan_beancount_files
from utils.beancount_file_manager import read_beancount_file
from utils.prompt_builder import build_ai_prompt, calculate_prompt_stats


st.set_page_config(page_title="AI 处理 Beancount", page_icon="🤖", layout="wide")
st.title("🤖 AI 智能处理 Beancount 账单")
st.caption("选择最新账单和历史参考文件，构建 AI 处理 Prompt（本页面不调用后端 AI）。")
st.divider()

_DATE_RANGE_RE = re.compile(r"(?P<start>\d{8})_(?P<end>\d{8})")


def _format_yyyymmdd(value: str) -> str | None:
    if not value or len(value) != 8:
        return None
    yyyy, mm, dd = value[:4], value[4:6], value[6:8]
    return f"{yyyy}-{mm}-{dd}"


def _format_date_range_from_filename(filename: str) -> str:
    match = _DATE_RANGE_RE.search(filename or "")
    if not match:
        return "未知"
    start = _format_yyyymmdd(match.group("start"))
    end = _format_yyyymmdd(match.group("end"))
    if start and end:
        return f"{start} 至 {end}"
    return "未知"


def _format_size_bytes(size: int) -> str:
    try:
        size_f = float(size)
    except Exception:
        return "未知"
    if size_f < 1024:
        return f"{int(size_f)} B"
    size_f /= 1024
    if size_f < 1024:
        return f"{size_f:.1f} KB"
    size_f /= 1024
    return f"{size_f:.1f} MB"


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


@st.cache_data(show_spinner=False)
def _cached_read_beancount_file(path_str: str, mtime: float) -> str | None:
    # mtime 作为缓存 key 的一部分，文件变更时自动失效
    return read_beancount_file(Path(path_str))


all_files = scan_beancount_files(BEANCOUNT_OUTPUT_DIR) if BEANCOUNT_OUTPUT_DIR.exists() else []


st.subheader("📂 文件选择")

if not BEANCOUNT_OUTPUT_DIR.exists():
    st.warning("未找到 outputs/beancount 目录：你仍然可以上传本机 .bean 文件继续。")
    st.code(str(BEANCOUNT_OUTPUT_DIR))
elif not all_files:
    st.warning("outputs/beancount 目录下未发现 .bean 文件：你仍然可以上传本机 .bean 文件继续。")

st.markdown("#### ✅ 最新账单（默认选择最新，也可手动选择/上传）")
latest_source_tab_outputs, latest_source_tab_upload = st.tabs(["从 outputs 选择", "从本机上传"])

with latest_source_tab_outputs:
    if all_files:
        output_option_to_info = {
            f"{info.name} ({info.format_size()} | {info.format_date_range()})": info
            for info in all_files
        }
        selected_latest_output_option = st.selectbox(
            "选择最新账单（来自 outputs/beancount）",
            options=list(output_option_to_info.keys()),
            index=0,
        )
        selected_latest_output_info = output_option_to_info[selected_latest_output_option]
    else:
        selected_latest_output_info = None
        st.info("当前 outputs/beancount 没有可选文件。")

with latest_source_tab_upload:
    uploaded_latest = st.file_uploader(
        "上传最新账单（.bean）",
        type=["bean"],
        accept_multiple_files=False,
        help="选择你本机上的 .bean 文件作为“最新账单”。上传后将优先使用上传文件。",
    )

st.markdown("#### 📚 历史账单（可选多个作为参考，也可从本机上传）")
history_source_tab_outputs, history_source_tab_upload = st.tabs(["从 outputs 多选", "从本机批量上传"])

with history_source_tab_outputs:
    history_candidates = []
    if all_files:
        history_candidates = list(all_files)
    if selected_latest_output_info is not None:
        history_candidates = [f for f in history_candidates if f.name != selected_latest_output_info.name]

    if not history_candidates:
        selected_history_infos = []
        st.info("当前 outputs/beancount 没有可选的历史文件。")
    else:
        history_option_to_info = {
            f"{info.name} ({info.format_size()} | {info.format_date_range()})": info
            for info in history_candidates
        }
        selected_history_options = st.multiselect(
            "选择历史账单文件（来自 outputs/beancount）",
            options=list(history_option_to_info.keys()),
            default=[],
            help="可选择多个历史 Beancount 文件作为参考，帮助 AI 学习你的账户命名习惯。",
        )
        selected_history_infos = [history_option_to_info[o] for o in selected_history_options]

with history_source_tab_upload:
    uploaded_history_files = st.file_uploader(
        "上传历史账单（可多选 .bean）",
        type=["bean"],
        accept_multiple_files=True,
        help="上传的文件将被加入参考库（历史账单）。",
    ) or []

st.divider()


st.subheader("📝 Prompt 预览")
with st.spinner("正在读取文件并构建 Prompt..."):
    # 1) 确定“最新账单”：上传优先，其次 outputs 选择
    latest_name: str | None = None
    latest_content: str | None = None
    latest_display_size: str | None = None
    latest_display_range: str | None = None

    if uploaded_latest is not None:
        raw = uploaded_latest.getvalue()
        latest_content = _decode_uploaded_beancount(raw)
        latest_name = uploaded_latest.name
        latest_display_size = _format_size_bytes(len(raw or b""))
        latest_display_range = _format_date_range_from_filename(uploaded_latest.name)
        if latest_content is None:
            st.error(f"上传文件无法以 UTF-8 解码：{uploaded_latest.name}")
            st.stop()
    else:
        if selected_latest_output_info is None:
            st.error("请先选择或上传一个“最新账单（.bean）”。")
            st.stop()
        latest_name = selected_latest_output_info.name
        latest_content = _cached_read_beancount_file(str(selected_latest_output_info.path), selected_latest_output_info.mtime)
        latest_display_size = selected_latest_output_info.format_size()
        latest_display_range = selected_latest_output_info.format_date_range()
        if latest_content is None:
            st.error(f"读取最新账单失败：{selected_latest_output_info.name}")
            st.stop()

    reference_files: list[tuple[str, str]] = []
    # 2) 历史账单：outputs 多选 + 本机上传（两者合并）
    for info in selected_history_infos:
        content = _cached_read_beancount_file(str(info.path), info.mtime)
        if content is None:
            st.error(f"读取历史账单失败，已跳过：{info.name}")
            continue
        reference_files.append((info.name, content))

    for uf in uploaded_history_files:
        raw = uf.getvalue()
        decoded = _decode_uploaded_beancount(raw)
        if decoded is None:
            st.error(f"上传历史账单无法以 UTF-8 解码，已跳过：{uf.name}")
            continue
        reference_files.append((uf.name, decoded))

    prompt = build_ai_prompt(
        latest_file_name=str(latest_name),
        latest_file_content=latest_content,
        reference_files=reference_files,
    )

stats = calculate_prompt_stats(prompt)
st.caption(f"统计：{stats.get('chars', 0):,} 字符 | {stats.get('lines', 0):,} 行 | {stats.get('files', 0)} 个文件")
if stats.get("chars", 0) > 100_000:
    st.warning("Prompt 超过 100KB，可能影响 AI 处理效果（本页面不会限制长度）。")

with st.expander("📝 预览 Prompt（右上角可复制）", expanded=False):
    st.code(prompt, language="markdown")

st.divider()


st.subheader("🚀 操作")

st.button("🤖 发送给 AI（开发中）", disabled=True, use_container_width=True)
st.caption("功能开发中：本次不实现后端 AI 调用。")
