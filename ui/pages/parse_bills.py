"""
解析账单页面（ui_plan.md 2.6）

将本地已下载的账单（信用卡/微信/支付宝）解析并导出为 Beancount。
"""

from datetime import datetime, timedelta
import contextlib
import io
import logging

import streamlit as st

from constants import EMAILS_DIR
from run import calculate_date_range_for_quick_select, parse_downloaded_bills_to_beancount


st.set_page_config(page_title="解析账单", page_icon="🧾", layout="wide")
st.title("🧾 解析所有已下载账单")

if not EMAILS_DIR.exists():
    st.warning("未找到 emails 目录，请先到「下载账单」页面下载账单。")
    st.stop()

st.caption("当前只支持导出 Beancount（账户为占位符，后续再做智能填充）。")
st.divider()

# ==================== 日志级别 ====================
log_level = st.selectbox(
    "日志级别",
    ["INFO", "DEBUG"],
    index=0,
    help="如果你觉得“完整日志”不够多，切到 DEBUG 会看到更多细节；同时会捕获代码里的 print 输出。",
)

# ==================== 时间范围（账单产生时间） ====================
st.subheader("选择解析范围（按交易发生日期）")
selection_mode = st.radio("选择方式", ["快捷选择", "自定义日期范围"], horizontal=True)

start_date = None
end_date = None

if selection_mode == "快捷选择":
    quick_option = st.selectbox("选择时间范围", ["本月", "上月", "最近三个月"])
    try:
        start_date, end_date = calculate_date_range_for_quick_select(quick_option)
        st.info(
            f"将解析并筛选交易：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}（包含起止日期）"
        )
    except Exception as e:
        st.error(f"日期计算错误：{str(e)}")
else:
    col1, col2 = st.columns(2)
    with col1:
        start_date_input = st.date_input(
            "开始日期",
            value=datetime.now() - timedelta(days=30),
            help="按交易发生日期筛选（包含当天）",
        )
    with col2:
        end_date_input = st.date_input(
            "结束日期",
            value=datetime.now(),
            help="结束日期（包含当天）",
        )

    if start_date_input and end_date_input:
        if start_date_input > end_date_input:
            st.error("开始日期不能晚于结束日期")
        else:
            start_date = datetime.combine(start_date_input, datetime.min.time())
            end_date = datetime.combine(end_date_input, datetime.max.time())
            st.info(
                f"将解析并筛选交易：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}（包含起止日期）"
            )

st.divider()

parse_button = st.button(
    "🚀 开始解析并导出 Beancount",
    disabled=not start_date or not end_date,
    use_container_width=True,
    type="primary",
)

if parse_button:
    log_stream = io.StringIO()
    log_handler = logging.StreamHandler(log_stream)
    log_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    ))
    log_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.addHandler(log_handler)

    try:
        with st.status("正在解析账单并生成 Beancount...", expanded=True) as status:
            progress_bar = st.progress(0.0)
            message_container = st.empty()

            def progress_callback(current: int, total: int, message: str):
                progress = 0.0 if total <= 0 else (current / total)
                progress_bar.progress(max(0.0, min(progress, 1.0)))
                message_container.text(message)

            with contextlib.redirect_stdout(log_stream), contextlib.redirect_stderr(log_stream):
                result = parse_downloaded_bills_to_beancount(
                    start_date=start_date,
                    end_date=end_date,
                    log_level=log_level,
                    progress_callback=progress_callback,
                )

            stats = result.get("stats", {}) or {}
            beancount_text = result.get("beancount_text", "") or ""
            output_path = result.get("output_path")

            # 进度区收口：避免把“最终完成提示”与下面的成功提示重复展示
            message_container.empty()

            status.update(label="✅ 解析完成", state="complete")

            st.success(
                f"完成：解析目录 {stats.get('folders_parsed', 0)}/{stats.get('folders_total', 0)}，"
                f"共生成 {stats.get('txns_total', 0)} 条交易"
            )
            if output_path:
                st.caption("已写入文件：")
                st.code(output_path)

            st.download_button(
                label="⬇️ 下载 Beancount 文件",
                data=beancount_text.encode("utf-8"),
                file_name=f"transactions_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.bean",
                mime="text/plain",
                use_container_width=True,
            )

            with st.expander("预览", expanded=False):
                preview = "\n".join(beancount_text.splitlines())
                st.text_area("Beancount 预览", value=preview, height=650, disabled=True)

            final_log = log_stream.getvalue()
            if final_log:
                with st.expander("📋 查看完整日志", expanded=False):
                    st.text_area("日志输出", value=final_log, height=650, disabled=True)

    except Exception as e:
        st.error(f"解析失败：{str(e)}")
        error_log = log_stream.getvalue()
        if error_log:
            with st.expander("📋 查看错误日志", expanded=True):
                st.text_area("日志输出", value=error_log, height=300, disabled=True)
    finally:
        root_logger.removeHandler(log_handler)
        root_logger.setLevel(original_level)
