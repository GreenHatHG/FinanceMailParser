"""
AI 智能处理 Beancount 账单（ui_plan.md 2.7.1）

功能：
- 自动选择最新 Beancount 文件（outputs/beancount）
- 支持多选历史文件作为参考库
- 构建并预览 Prompt（本次不做后端 AI 调用）
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re

import streamlit as st

from constants import BEANCOUNT_OUTPUT_DIR, PROJECT_ROOT
from utils.beancount_file_manager import scan_beancount_files
from utils.beancount_file_manager import read_beancount_file
from utils.amount_masking import AmountMasker
from utils.prompt_builder_v2 import build_smart_ai_prompt, calculate_prompt_stats_v2
from utils.beancount_validator import reconcile_beancount, BeancountReconciler


st.set_page_config(page_title="AI 处理 Beancount", page_icon="🤖", layout="wide")
st.title("🤖 AI 智能处理 Beancount 账单")
st.caption("选择最新账单和历史参考文件，构建 AI 处理 Prompt，并发送给 AI 填充消费账户。")
st.divider()

_DATE_RANGE_RE = re.compile(r"(?P<start>\d{8})_(?P<end>\d{8})")
MASK_MAP_DIR = PROJECT_ROOT / "outputs" / "mask_maps"


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

st.markdown("#### 📋 账户定义文件（可选，推荐）")
uploaded_account_definition = st.file_uploader(
    "上传账户定义文件（包含 open 指令的 .bean 文件）",
    type=["bean"],
    accept_multiple_files=False,
    help=(
        "**推荐上传**：包含所有账户 open 指令的 Beancount 文件（通常是主账本文件）。\n\n"
        "示例格式：\n"
        "```\n"
        "2024-01-01 open Expenses:Food:Restaurant\n"
        "2024-01-01 open Expenses:Transport:Taxi\n"
        "```\n\n"
        "如果不上传，将从历史交易文件中提取账户（只能获得已使用过的账户）。"
    ),
)

st.divider()


st.subheader("⚙️ Prompt 构建选项")

# 示例数量配置
examples_per_transaction = st.slider(
    "每个 TODO 交易的示例数量",
    min_value=1,
    max_value=5,
    value=3,
    help="为每个待填充账户的交易提供多少个相似的历史交易作为参考（基于 TF-IDF 匹配）",
)

# 自定义 Prompt
extra_prompt = st.text_area(
    "额外的自定义指示（可选）",
    value="",
    height=150,
    placeholder=(
        "在这里添加您的自定义规则或指示，例如：\n\n"
        "- 所有星巴克的消费都归类到 Expenses:Food:Cafe\n"
        "- 交通费用超过 100 元的归类到 Expenses:Transport:LongDistance\n"
        "- 优先使用 Expenses:Food:Restaurant 而不是 Expenses:Food:Takeout"
    ),
    help="AI 会在处理时参考这些自定义规则。留空则使用默认规则。",
)

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
        latest_fingerprint = hashlib.sha1(raw or b"").hexdigest()
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
        latest_fingerprint = f"{selected_latest_output_info.name}:{selected_latest_output_info.mtime}:{selected_latest_output_info.size}"
        latest_content = _cached_read_beancount_file(str(selected_latest_output_info.path), selected_latest_output_info.mtime)
        latest_display_size = selected_latest_output_info.format_size()
        latest_display_range = selected_latest_output_info.format_date_range()
        if latest_content is None:
            st.error(f"读取最新账单失败：{selected_latest_output_info.name}")
            st.stop()

    reference_files: list[tuple[str, str]] = []
    reference_fingerprints: list[str] = []

    # 2) 读取账户定义文件（可选）
    account_definition_content: str | None = None
    if uploaded_account_definition is not None:
        raw = uploaded_account_definition.getvalue()
        account_definition_content = _decode_uploaded_beancount(raw)
        if account_definition_content is None:
            st.warning(f"账户定义文件无法以 UTF-8 解码，将从历史交易中提取账户：{uploaded_account_definition.name}")

    # 3) 历史账单：outputs 多选 + 本机上传（两者合并）
    for info in selected_history_infos:
        content = _cached_read_beancount_file(str(info.path), info.mtime)
        if content is None:
            st.error(f"读取历史账单失败，已跳过：{info.name}")
            continue
        reference_files.append((info.name, content))
        reference_fingerprints.append(f"{info.name}:{info.mtime}:{info.size}")

    for uf in uploaded_history_files:
        raw = uf.getvalue()
        reference_fingerprints.append(f"{uf.name}:{hashlib.sha1(raw or b'').hexdigest()}")
        decoded = _decode_uploaded_beancount(raw)
        if decoded is None:
            st.error(f"上传历史账单无法以 UTF-8 解码，已跳过：{uf.name}")
            continue
        reference_files.append((uf.name, decoded))

    # 3) 金额脱敏（ui_plan.md 2.7.2）
    # - 默认对“最新账单 + 所有历史参考账单”统一脱敏，保证 Prompt 中不出现真实金额
    # - 脱敏映射会存入 session_state（可选落盘），为后续 2.7.3（AI 返回后恢复金额）做准备
    signature_payload = {
        "latest": {"name": str(latest_name), "fingerprint": latest_fingerprint},
        "refs": sorted(reference_fingerprints),
    }
    signature = json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)
    run_id = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]

    masker = AmountMasker(run_id=run_id)
    masked_latest_content = masker.mask_text(latest_content) or ""
    masked_reference_files: list[tuple[str, str]] = []
    for fn, fc in reference_files:
        masked_reference_files.append((fn, masker.mask_text(fc) or ""))

    amount_stats = masker.stats()
    st.caption(f"金额脱敏：{amount_stats.tokens_total} 处（run_id={amount_stats.run_id}）")

    persist_map = st.checkbox(
        "落盘保存脱敏映射（包含真实金额，敏感）",
        value=True,
        help="保存到 outputs/mask_maps/{run_id}.json，用于页面刷新/重启后仍可恢复金额。",
    )
    saved_map_path: str | None = None
    if persist_map and amount_stats.tokens_total > 0:
        try:
            MASK_MAP_DIR.mkdir(parents=True, exist_ok=True)
            path = MASK_MAP_DIR / f"{amount_stats.run_id}.json"
            payload = {"run_id": amount_stats.run_id, "mapping": masker.mapping}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_map_path = str(path)
            st.caption("已保存脱敏映射：")
            st.code(saved_map_path)
        except Exception as e:
            st.warning(f"脱敏映射落盘失败（不影响本次预览）：{str(e)}")

    st.session_state["amount_masking"] = {
        "run_id": amount_stats.run_id,
        "tokens_total": amount_stats.tokens_total,
        "mapping": dict(masker.mapping),
        "saved_path": saved_map_path,
    }

    # 构建 Prompt（使用 v2 智能优化）
    prompt_masked, prompt_stats_v2 = build_smart_ai_prompt(
        latest_file_name=str(latest_name),
        latest_file_content=masked_latest_content,
        reference_files=masked_reference_files,
        examples_per_transaction=examples_per_transaction,
        account_definition_text=account_definition_content,
        extra_prompt=extra_prompt.strip() if extra_prompt else None,
    )
    prompt_real, _ = build_smart_ai_prompt(
        latest_file_name=str(latest_name),
        latest_file_content=latest_content,
        reference_files=reference_files,
        examples_per_transaction=examples_per_transaction,
        account_definition_text=account_definition_content,
        extra_prompt=extra_prompt.strip() if extra_prompt else None,
    )

show_real = st.checkbox(
    "显示真实金额（仅本地预览，不用于发送给 AI）",
    value=False,
    help="默认展示脱敏版本；勾选后会在页面上显示真实金额。",
)
prompt = prompt_real if show_real else prompt_masked

# 计算统计信息
stats = calculate_prompt_stats_v2(prompt, prompt_stats_v2)

# 显示统计信息
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("字符数", f"{stats.get('chars', 0):,}")
with col2:
    st.metric("行数", f"{stats.get('lines', 0):,}")
with col3:
    st.metric("文件数", stats.get('files', 0))

col4, col5, col6 = st.columns(3)
with col4:
    st.metric("可用账户", stats.get('account_categories', 0))
with col5:
    st.metric("TODO 交易", stats.get('todo_transactions', 0))
with col6:
    st.metric("示例交易", stats.get('example_transactions', 0))

# 大小提示
if stats.get("chars", 0) > 100_000:
    st.warning("⚠️ Prompt 超过 100KB，可能影响 AI 处理效果。")
else:
    st.success(f"✅ Prompt 大小：{stats.get('chars', 0):,} 字符（已优化）")

with st.expander("📝 预览 Prompt（右上角可复制）", expanded=False):
    st.code(prompt, language="markdown")

st.divider()


st.subheader("🚀 发送到 AI 处理")

# 检查 AI 配置
from ai.config import AIConfigManager
from ai.service import AIService

ai_config_manager = AIConfigManager()

if not ai_config_manager.config_exists():
    st.error("❌ 尚未配置 AI，请先前往「AI 配置」页面进行配置")
    st.stop()

config = ai_config_manager.load_config()
if config:
    st.info(f"📡 当前使用：{config['provider']} | {config['model']}")
else:
    st.error("❌ AI 配置加载失败")
    st.stop()

# 发送按钮
send_button = st.button(
    "🤖 发送到 AI 处理",
    disabled=not prompt_masked,
    use_container_width=True,
    type="primary",
)

if send_button:
    ai_service = AIService(ai_config_manager)

    with st.status("正在调用 AI...", expanded=True) as status:
        import time as time_module

        start_time = time_module.time()

        # 调用 AI（使用脱敏后的 prompt）
        stats = ai_service.call_completion(prompt_masked)

        # 保存结果到 session_state
        st.session_state["ai_result"] = {
            "stats": stats,
            "latest_name": latest_name,
        }

        if stats.success:
            status.update(label="✅ AI 处理完成", state="complete")
        else:
            status.update(label="❌ AI 调用失败", state="error")

# 显示 AI 结果（基于 session_state，而不是 send_button）
if "ai_result" in st.session_state:
    result = st.session_state["ai_result"]
    stats = result["stats"]
    latest_name = result["latest_name"]

    if stats.success:
        # 展示统计信息
        st.subheader("📊 调用统计")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("耗时", f"{stats.total_time:.2f} 秒")
        with col2:
            st.metric("重试次数", stats.retry_count)
        with col3:
            st.metric("输入 Tokens", f"{stats.prompt_tokens:,}")
        with col4:
            st.metric("输出 Tokens", f"{stats.completion_tokens:,}")

        st.caption(f"总 Tokens: {stats.total_tokens:,}")

        # 展示 AI 返回内容（脱敏版本）
        st.subheader("📄 AI 处理结果（脱敏版本）")
        st.code(stats.response, language="beancount")

        # 对账功能（ui_plan.md 2.7.4）
        st.divider()
        st.subheader("🔍 对账检查")
        st.caption("检查 AI 返回的内容是否完整、是否有篡改")

        with st.spinner("正在对账..."):
            # 调用对账函数
            reconcile_report = reconcile_beancount(
                    before_text=masked_latest_content,  # 发送前的最新账单（脱敏版本）
                    after_text=stats.response           # AI 返回的脱敏文本
                )

            # 展示对账结果
            if reconcile_report.is_valid:
                st.success("✅ 对账通过！交易完整无篡改")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("发送前交易数", reconcile_report.total_before)
                with col2:
                    st.metric("返回后交易数", reconcile_report.total_after)
            else:
                st.error("❌ 对账失败！发现异常")

                # 展示统计信息
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("发送前交易数", reconcile_report.total_before)
                with col2:
                    st.metric("返回后交易数", reconcile_report.total_after)
                with col3:
                    st.metric("差异数", len(reconcile_report.missing) + len(reconcile_report.added))

                # 展示详细差异
                if reconcile_report.error_message:
                    st.warning(f"错误信息：{reconcile_report.error_message}")

                if reconcile_report.missing:
                    with st.expander(f"⚠️ 缺失的交易（{len(reconcile_report.missing)} 笔）", expanded=True):
                        for txn in reconcile_report.missing:
                            st.code(
                                f"{txn.date} * \"{txn.description}\"\n"
                                f"  金额: {', '.join(txn.amounts)}\n"
                                f"  账户: {', '.join(txn.accounts)}",
                                language="text"
                            )

                if reconcile_report.added:
                    with st.expander(f"⚠️ 异常新增的交易（{len(reconcile_report.added)} 笔）", expanded=True):
                        for txn in reconcile_report.added:
                            st.code(
                                f"{txn.date} * \"{txn.description}\"\n"
                                f"  金额: {', '.join(txn.amounts)}\n"
                                f"  账户: {', '.join(txn.accounts)}",
                                language="text"
                            )

                if reconcile_report.tampered:
                    with st.expander(f"⚠️ 被篡改的交易（{len(reconcile_report.tampered)} 笔）", expanded=True):
                        for info in reconcile_report.tampered:
                            st.markdown(f"**原始：** {info.before.date} * \"{info.before.description}\"")
                            st.markdown(f"**修改后：** {info.after.date} * \"{info.after.description}\"")
                            st.markdown(f"**原因：** {info.reason}")
                            st.divider()

                # 提供处理选项
                st.warning("⚠️ 建议：对账失败可能导致数据不完整，请谨慎处理")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("🔄 重新发送给 AI", use_container_width=True):
                        st.rerun()
                with col2:
                    st.button("✏️ 手动修复", use_container_width=True, disabled=True, help="功能开发中")
                with col3:
                    ignore_and_continue = st.checkbox("⚠️ 忽略并继续（风险）", value=False)

            st.divider()

            # 恢复金额
            st.subheader("🔓 恢复真实金额")
            st.caption("将 AI 返回的脱敏金额恢复为真实金额")

            # 如果对账失败且用户未选择忽略，禁用恢复按钮
            restore_disabled = not reconcile_report.is_valid and not st.session_state.get("ignore_reconcile_failure", False)
            if not reconcile_report.is_valid:
                if st.session_state.get("ignore_reconcile_failure", False) or locals().get("ignore_and_continue", False):
                    st.session_state["ignore_reconcile_failure"] = True
                    restore_disabled = False

            if st.button("🔓 恢复金额", use_container_width=True, disabled=restore_disabled):
                try:
                    # 从 session_state 获取脱敏映射
                    masking_info = st.session_state.get("amount_masking")
                    if not masking_info or not masking_info.get("mapping"):
                        st.error("❌ 未找到脱敏映射，无法恢复金额")
                    else:
                        # 创建 masker 并恢复金额
                        restore_masker = AmountMasker(run_id=masking_info["run_id"])
                        restore_masker.mapping = masking_info["mapping"]

                        restored_content = restore_masker.unmask_text(stats.response)

                        st.success("✅ 金额恢复成功！")

                        # 第二次对账：检查账户填充是否正确
                        st.divider()
                        st.subheader("🔍 金额恢复对账")
                        st.caption("检查恢复金额后的日期、金额、描述是否与原始一致")

                        with st.spinner("正在对账..."):
                            # 获取原始未脱敏的内容
                            original_content = latest_content

                            # 调用账户填充对账函数
                            reconciler = BeancountReconciler()
                            filling_report = reconciler.reconcile_account_filling(
                                original_text=original_content,
                                restored_text=restored_content
                            )

                        if filling_report.is_valid:
                            st.success("✅ 金额恢复对账通过")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("总交易数", filling_report.total_transactions)
                            with col2:
                                st.metric("匹配成功", filling_report.matched_transactions)
                        else:
                            st.error(f"❌ 金额恢复对账失败：{filling_report.error_message}")

                        st.divider()

                        st.subheader("📄 AI 处理结果（真实金额）")
                        st.code(restored_content, language="beancount")

                        # 提供下载按钮
                        st.download_button(
                            label="💾 下载处理后的 Beancount 文件",
                            data=restored_content,
                            file_name=f"ai_processed_{latest_name}",
                            mime="text/plain",
                            use_container_width=True,
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
