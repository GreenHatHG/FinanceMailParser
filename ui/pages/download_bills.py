"""
账单下载页面

提供日期范围选择、信用卡账单下载、进度显示等功能
"""

import streamlit as st
from datetime import datetime, timedelta
import logging
import io

from data_source.qq_email import QQEmailConfigManager
from run import download_credit_card_emails, calculate_date_range_for_quick_select

# 设置页面配置
st.set_page_config(page_title="下载账单", page_icon="📥")

st.title("📥 下载账单")

# ==================== 配置状态检查 ====================
st.subheader("配置状态")

qq_config_manager = QQEmailConfigManager()
if not qq_config_manager.config_exists():
    st.error("❌ 尚未配置邮箱，请先前往「邮箱配置」页面进行配置")
    st.stop()
else:
    config = qq_config_manager.load_config()
    st.success(f"✅ 已配置邮箱：{config['email']}")

st.divider()

# ==================== 日期选择区域 ====================
st.subheader("选择下载范围")

selection_mode = st.radio(
    "选择方式",
    ["快捷选择", "自定义日期范围"],
    horizontal=True
)

start_date = None
end_date = None

if selection_mode == "快捷选择":
    quick_option = st.selectbox(
        "选择时间范围",
        ["本月", "上月", "最近三个月"]
    )

    # 根据选择计算日期范围
    try:
        start_date, end_date = calculate_date_range_for_quick_select(quick_option)
        st.info(f"📅 将下载：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        st.error(f"❌ 日期计算错误：{str(e)}")

else:  # 自定义日期范围
    col1, col2 = st.columns(2)

    with col1:
        start_date_input = st.date_input(
            "开始日期",
            value=datetime.now() - timedelta(days=30),
            help="选择开始日期"
        )

    with col2:
        end_date_input = st.date_input(
            "结束日期",
            value=datetime.now(),
            help="选择结束日期"
        )

    # 验证日期范围
    if start_date_input and end_date_input:
        if start_date_input > end_date_input:
            st.error("❌ 开始日期不能晚于结束日期")
        else:
            # 转换为 datetime
            start_date = datetime.combine(start_date_input, datetime.min.time())
            end_date = datetime.combine(end_date_input, datetime.max.time())
            st.info(f"📅 将下载：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")

st.divider()

# ==================== 下载按钮和进度显示 ====================
st.subheader("开始下载")

# 下载按钮
download_button = st.button(
    "🚀 开始下载信用卡账单",
    disabled=not start_date or not end_date,
    use_container_width=True,
    type="primary"
)

# ==================== 下载逻辑 ====================
if download_button:
    # 创建日志捕获器
    log_stream = io.StringIO()
    log_handler = logging.StreamHandler(log_stream)
    log_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    ))

    # 添加到根日志记录器
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.addHandler(log_handler)

    try:
        # 使用 st.status 显示进度
        with st.status("正在下载信用卡账单...", expanded=True) as status:
            # 创建进度条和消息容器
            progress_bar = st.progress(0.0)
            message_container = st.empty()

            # 定义进度回调
            def progress_callback(current: int, total: int, message: str):
                progress = current / total
                progress_bar.progress(progress)
                message_container.text(message)

            # 执行下载
            result = download_credit_card_emails(
                start_date=start_date,
                end_date=end_date,
                log_level='INFO',
                progress_callback=progress_callback
            )

            # 更新状态为完成
            status.update(
                label=f"✅ 下载完成！共 {result['credit_card']} 封信用卡账单",
                state="complete"
            )

            # 显示成功消息和跳转链接
            st.success(f"✅ 下载完成！共下载 {result['credit_card']} 封信用卡账单")
            st.info("💡 您可以前往 **查看账单** 页面查看已下载的账单")

            # 显示最终日志
            final_log = log_stream.getvalue()
            if final_log:
                with st.expander("📋 查看完整日志", expanded=False):
                    st.text_area(
                        "日志输出",
                        value=final_log,
                        height=300,
                        disabled=True,
                        key="final_log"
                    )

    except Exception as e:
        st.error(f"❌ 下载失败：{str(e)}")

        # 显示错误日志
        error_log = log_stream.getvalue()
        if error_log:
            with st.expander("📋 查看错误日志", expanded=True):
                st.text_area(
                    "日志输出",
                    value=error_log,
                    height=300,
                    disabled=True,
                    key="error_log"
                )

    finally:
        # 移除日志处理器
        root_logger.removeHandler(log_handler)
        root_logger.setLevel(original_level)

