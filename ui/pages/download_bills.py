"""
账单下载页面

提供日期范围选择、信用卡账单下载、进度显示等功能
"""

import streamlit as st
from datetime import datetime, timedelta
import logging
import io

from data_source.qq_email import QQEmailConfigManager
from run import (
    download_credit_card_emails,
    download_digital_payment_emails,
    calculate_date_range_for_quick_select,
)

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

# ==================== 两大功能区：信用卡 / 微信支付宝 ====================
tab_cc, tab_digital = st.tabs(["💳 信用卡账单", "✳️ 微信 / 支付宝账单（最新）"])

with tab_cc:
    st.subheader("💳 信用卡账单")
    st.caption("按日期范围下载信用卡电子账单（支持快捷选择/自定义日期范围）。")

    # ==================== 日期选择区域（仅信用卡） ====================
    st.markdown("### 选择下载范围")

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

    # ==================== 下载按钮和进度显示（信用卡） ====================
    st.markdown("### 开始下载")

    download_button = st.button(
        "🚀 开始下载信用卡账单",
        disabled=not start_date or not end_date,
        use_container_width=True,
        type="primary"
    )

    if download_button:
        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        log_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))

        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.addHandler(log_handler)

        try:
            with st.status("正在下载信用卡账单...", expanded=True) as status:
                progress_bar = st.progress(0.0)
                message_container = st.empty()

                def progress_callback(current: int, total: int, message: str):
                    progress = current / total
                    progress_bar.progress(progress)
                    message_container.text(message)

                result = download_credit_card_emails(
                    start_date=start_date,
                    end_date=end_date,
                    log_level='INFO',
                    progress_callback=progress_callback
                )

                status.update(
                    label=f"✅ 下载完成！共 {result['credit_card']} 封信用卡账单",
                    state="complete"
                )

                st.success(f"✅ 下载完成！共下载 {result['credit_card']} 封信用卡账单")
                st.info("💡 您可以前往 **查看账单** 页面查看已下载的账单")

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
            root_logger.removeHandler(log_handler)
            root_logger.setLevel(original_level)

with tab_digital:
    st.subheader("✳️ 微信 / 支付宝账单（最新）")
    st.caption("微信/支付宝只下载最新一封；若本地已存在CSV会自动跳过，避免重复下载导致链接失效。")

    col1, col2 = st.columns(2)
    with col1:
        alipay_pwd = st.text_input(
            "支付宝解压密码",
            type="password",
            help="用于解压支付宝账单ZIP（不保存到本地）",
            key="alipay_pwd",
        )

    with col2:
        wechat_pwd = st.text_input(
            "微信解压密码",
            type="password",
            help="用于解压微信账单ZIP（不保存到本地）",
            key="wechat_pwd",
        )

    digital_download_button = st.button(
        "🚀 下载微信/支付宝账单（最新）",
        use_container_width=True,
    )

    if digital_download_button:
        status_labels = {
            'downloaded': '已下载并解压',
            'skipped_existing_csv': '本地已存在CSV，已跳过下载',
            'extracted_existing_zip': '本地已存在ZIP，已成功解压',
            'failed_extract_existing_zip': '本地ZIP解压失败（建议确认密码或手动解压）',
            'not_found': '未找到匹配的账单邮件',
            'missing_password': '缺少解压密码（无法继续）',
            'failed': '处理失败（请查看日志）',
            'unknown': '未知状态',
        }

        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        log_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))

        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.addHandler(log_handler)

        try:
            with st.status("正在下载微信/支付宝账单...", expanded=True) as status:
                progress_bar = st.progress(0.0)
                message_container = st.empty()

                def progress_callback(current: int, total: int, message: str):
                    progress = 0.0 if total <= 0 else (current / total)
                    progress_bar.progress(max(0.0, min(progress, 1.0)))
                    message_container.text(message)

                result = download_digital_payment_emails(
                    log_level='INFO',
                    alipay_pwd=alipay_pwd or None,
                    wechat_pwd=wechat_pwd or None,
                    progress_callback=progress_callback,
                )

                alipay_status = result.get('alipay_status')
                wechat_status = result.get('wechat_status')
                alipay_downloaded = result.get('alipay', 0)
                wechat_downloaded = result.get('wechat', 0)

                status.update(
                    label=f"✅ 处理完成：支付宝 {alipay_downloaded}，微信 {wechat_downloaded}",
                    state="complete",
                )

                st.success(f"✅ 处理完成：支付宝 {alipay_downloaded} 个文件，微信 {wechat_downloaded} 个文件")
                st.info(
                    f"支付宝：{status_labels.get(alipay_status, str(alipay_status))}；"
                    f"微信：{status_labels.get(wechat_status, str(wechat_status))}"
                )

                final_log = log_stream.getvalue()
                if final_log:
                    with st.expander("📋 查看完整日志", expanded=False):
                        st.text_area(
                            "日志输出",
                            value=final_log,
                            height=300,
                            disabled=True,
                            key="final_log_digital",
                        )

        except Exception as e:
            st.error(f"❌ 下载失败：{str(e)}")
            error_log = log_stream.getvalue()
            if error_log:
                with st.expander("📋 查看错误日志", expanded=True):
                    st.text_area(
                        "日志输出",
                        value=error_log,
                        height=300,
                        disabled=True,
                        key="error_log_digital",
                    )
        finally:
            root_logger.removeHandler(log_handler)
            root_logger.setLevel(original_level)
