"""
解析账单页面（ui_plan.md 2.6）

将本地已下载的账单（信用卡/微信/支付宝）解析并导出为 Beancount。
"""

from datetime import datetime, timedelta
from typing import Dict, Any
import logging

import streamlit as st

from financemailparser.shared.constants import (
    DATE_FMT_COMPACT,
    DATE_FMT_ISO,
    EMAILS_DIR,
    TIME_FMT_HMS,
)
from financemailparser.application.billing.parse_export import (
    parse_downloaded_bills_to_beancount,
)
from financemailparser.application.common.date_range import (
    calculate_date_range_for_quick_select,
    get_quick_select_options,
)
from financemailparser.application.billing.beancount_history import (
    count_transactions,
    get_beancount_file_content,
    list_beancount_history,
    remove_beancount_file,
)

from ui.streamlit.log_utils import (
    capture_root_logger,
    make_progress_callback,
    render_log_expander,
)


st.set_page_config(page_title="解析账单", page_icon="🧾", layout="wide")
st.title("🧾 解析账单")

if not EMAILS_DIR.exists():
    st.error("❌ 未找到 emails 目录，请先到「下载账单」页面下载账单。")
    st.stop()

st.caption("将本地已下载的账单（信用卡/微信/支付宝）解析并导出为 Beancount。")
st.caption("当前只支持导出 Beancount（账户为占位符，后续可做智能填充）。")
st.divider()

# UI is organized to match "下载账单" page: range -> advanced -> action -> result.
st.subheader("解析范围")
st.caption("按交易发生日期筛选（不是邮件发送时间）。")
selection_mode = st.radio(
    "选择方式",
    ["快捷选择", "自定义日期范围"],
    horizontal=True,
    label_visibility="collapsed",
)

start_date = None
end_date = None

if selection_mode == "快捷选择":
    quick_option = st.selectbox(
        "选择时间范围",
        get_quick_select_options(),
        label_visibility="collapsed",
    )
    try:
        start_date, end_date = calculate_date_range_for_quick_select(quick_option)
    except Exception as e:
        st.error(f"❌ 日期计算错误：{str(e)}")
else:
    col1, col2 = st.columns(2)
    with col1:
        start_date_input = st.date_input(
            "开始",
            value=datetime.now() - timedelta(days=30),
            help="按交易发生日期筛选（包含当天）",
            label_visibility="collapsed",
        )
    with col2:
        end_date_input = st.date_input(
            "结束",
            value=datetime.now(),
            help="结束日期（包含当天）",
            label_visibility="collapsed",
        )

    if start_date_input and end_date_input:
        if start_date_input > end_date_input:
            st.error("❌ 开始日期不能晚于结束日期")
        else:
            start_date = datetime.combine(start_date_input, datetime.min.time())
            end_date = datetime.combine(end_date_input, datetime.max.time())

if start_date and end_date:
    st.info(
        f"📅 将解析并筛选交易：{start_date.strftime(DATE_FMT_ISO)} 至 {end_date.strftime(DATE_FMT_ISO)}（包含起止日期）"
    )

with st.expander("高级设置", expanded=False):
    log_level = st.selectbox(
        "日志级别",
        ["INFO", "DEBUG"],
        index=0,
        help="如果你觉得“完整日志”不够多，切到 DEBUG 会看到更多细节；同时会捕获代码里的 print 输出。",
    )

st.divider()
st.subheader("执行解析")
parse_button = st.button(
    "🚀 开始解析并导出 Beancount",
    disabled=not start_date or not end_date,
    use_container_width=True,
    type="primary",
)
st.caption("成功后优先展示摘要与下载；预览与完整日志默认折叠，可按需展开。")

if parse_button:
    with capture_root_logger(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt=TIME_FMT_HMS,
        handler_level=logging.DEBUG,
        redirect_stdio=True,
    ) as log_stream:
        try:
            with st.status("正在解析账单并生成 Beancount...", expanded=True) as status:
                progress_bar = st.progress(0.0)
                message_container = st.empty()
                progress_callback = make_progress_callback(
                    progress_bar, message_container
                )

                if start_date is None or end_date is None:
                    st.error("日期范围不能为空")
                    st.stop()
                    raise RuntimeError("Unreachable")  # For type checker

                result: Dict[str, Any] = parse_downloaded_bills_to_beancount(
                    start_date=start_date,
                    end_date=end_date,
                    log_level=log_level,
                    progress_callback=progress_callback,
                )

                stats: Dict[str, Any] = result.get("stats", {}) or {}
                beancount_text: str = str(result.get("beancount_text", "") or "")
                output_path = result.get("output_path")

                # 进度区收口：避免把“最终完成提示”与下面的成功提示重复展示
                message_container.empty()

                status.update(label="✅ 解析完成", state="complete")

                st.success(
                    f"完成：解析目录 {stats.get('folders_parsed', 0)}/{stats.get('folders_total', 0)}，"
                    f"共生成 {stats.get('txns_total', 0)} 条交易"
                )

                if start_date and end_date:
                    st.download_button(
                        label="⬇️ 下载 Beancount 文件",
                        data=beancount_text.encode("utf-8"),
                        file_name=f"transactions_{start_date.strftime(DATE_FMT_COMPACT)}_{end_date.strftime(DATE_FMT_COMPACT)}.bean",
                        mime="text/plain",
                        use_container_width=True,
                    )

                if output_path:
                    st.caption("已写入文件：")
                    st.code(output_path)

                with st.expander("预览", expanded=False):
                    preview = "\n".join(beancount_text.splitlines())
                    st.text_area(
                        "Beancount 预览", value=preview, height=650, disabled=True
                    )

                render_log_expander(
                    expander_title="📋 查看完整日志",
                    log_text=log_stream.getvalue(),
                    expanded=False,
                    height=450,
                )

        except Exception as e:
            st.error(f"❌ 解析失败：{str(e)}")
            render_log_expander(
                expander_title="📋 查看错误日志",
                log_text=log_stream.getvalue(),
                expanded=True,
                height=300,
            )

# ==================== 历史解析结果 ====================
st.divider()
st.subheader("📂 历史解析结果")
st.caption("以下是之前解析生成的 Beancount 文件，刷新页面后仍可查看和下载。")

history_items = list_beancount_history()

if not history_items:
    st.info("📭 暂无历史解析结果")
else:
    st.info(f"共 {len(history_items)} 个文件")

    for item in history_items:
        with st.expander(
            f"📄 {item.info.name}（{item.size_kb:.1f} KB · {item.modified_time_str}）"
        ):
            content = get_beancount_file_content(item.info.path)
            if content is None:
                st.error("读取文件内容失败")
                continue

            txn_count = count_transactions(content)
            st.caption(f"交易数约 {txn_count} 条 · 文件路径：{item.info.path}")

            col1, col2 = st.columns([1, 1])
            with col1:
                st.download_button(
                    label="⬇️ 下载",
                    data=content.encode("utf-8"),
                    file_name=item.info.name,
                    mime="text/plain",
                    key=f"download_{item.info.name}",
                )
            with col2:
                if st.button(
                    "🗑️ 删除",
                    key=f"delete_{item.info.name}",
                ):
                    if remove_beancount_file(item.info.path):
                        st.rerun()
                    else:
                        st.error("删除文件失败")

            st.text_area(
                "预览",
                value=content,
                height=400,
                disabled=True,
                key=f"preview_{item.info.name}",
                label_visibility="collapsed",
            )
