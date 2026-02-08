"""
账单下载页面

提供日期范围选择、信用卡账单下载、进度显示等功能
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, Any
import logging
import io

from constants import (
    DATE_FMT_ISO,
    TIME_FMT_HMS,
)
from models.digital_bill_status import (
    DIGITAL_BILL_STATUS_DOWNLOADED,
    DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP,
    DIGITAL_BILL_STATUS_FAILED,
    DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP,
    DIGITAL_BILL_STATUS_MISSING_PASSWORD,
    DIGITAL_BILL_STATUS_NOT_FOUND,
    DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV,
    DIGITAL_BILL_STATUS_UNKNOWN,
)
from app.services.bill_download_credit_card import download_credit_card_emails
from app.services.bill_download_digital import download_digital_payment_emails
from app.services.date_range import (
    calculate_date_range_for_quick_select,
    get_quick_select_options,
)
from app.services.email_config_facade import get_email_config_ui_snapshot

# 设置页面配置
st.set_page_config(page_title="下载账单", page_icon="📥", layout="wide")

st.title("📥 下载账单")
st.caption("从已经配置的邮箱中搜索并下载符合时间范围的账单邮件")
st.divider()

# ==================== 配置状态检查 ====================
st.subheader("邮件配置状态")

snap = get_email_config_ui_snapshot(provider_key="qq")
raw_email_for_hint = str(snap.email_raw or "").strip()

if not snap.present:
    st.error("❌ 尚未配置邮箱，请先前往「邮箱配置」页面进行配置")
    st.stop()

if snap.state == "missing_master_password":
    email_hint = f"（{raw_email_for_hint}）" if raw_email_for_hint else ""
    st.error(
        f"🔒 邮箱配置{email_hint}已加密，但未设置环境变量 {snap.master_password_env}，无法解锁。"
    )
    st.caption("请在启动 Streamlit 前设置该环境变量，然后重启应用。")
    st.stop()
elif snap.state == "plaintext_secret":
    st.error(f"❌ {snap.error_message}")
    st.caption("请前往「邮箱配置」页面删除后重新设置。")
    st.stop()
elif snap.state == "decrypt_failed":
    st.error(f"❌ {snap.error_message}")
    st.caption("请确认主密码是否正确；若忘记主密码，只能删除配置后重新设置。")
    st.stop()
elif snap.state != "ok":
    st.error(f"❌ 邮箱配置加载失败：{snap.error_message}")
    st.stop()

st.success(f"✅ 已配置邮箱：{snap.email}")

st.divider()
st.subheader("邮件时间筛选")

# ==================== 两大功能区：信用卡 / 微信支付宝 ====================
tab_cc, tab_digital = st.tabs(["💳 信用卡账单", "✳️ 微信 / 支付宝账单（最新）"])

with tab_cc:
    # ==================== 日期选择区域（仅信用卡） ====================
    st.caption("按邮件的发送时间筛选（非账单周期）。")

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

        # 根据选择计算日期范围
        try:
            start_date, end_date = calculate_date_range_for_quick_select(quick_option)
            st.info(
                f"📅 将下载：{start_date.strftime(DATE_FMT_ISO)} 至 {end_date.strftime(DATE_FMT_ISO)}（包含起止日期）"
            )
        except Exception as e:
            st.error(f"❌ 日期计算错误：{str(e)}")

    else:  # 自定义日期范围
        date_col1, date_col2 = st.columns(2)

        with date_col1:
            start_date_input = st.date_input(
                "开始",
                value=datetime.now() - timedelta(days=30),
                label_visibility="collapsed",
            )

        with date_col2:
            end_date_input = st.date_input(
                "结束", value=datetime.now(), label_visibility="collapsed"
            )

        # 验证日期范围
        if start_date_input and end_date_input:
            if start_date_input > end_date_input:
                st.error("❌ 开始日期不能晚于结束日期")
            else:
                # 转换为 datetime
                start_date = datetime.combine(start_date_input, datetime.min.time())
                end_date = datetime.combine(end_date_input, datetime.max.time())
                st.info(
                    f"📅 将下载：{start_date.strftime(DATE_FMT_ISO)} 至 {end_date.strftime(DATE_FMT_ISO)}（包含起止日期）"
                )

    # ==================== 下载按钮和进度显示（信用卡） ====================
    st.divider()
    download_button = st.button(
        "🚀 开始下载信用卡账单",
        disabled=not start_date or not end_date,
        use_container_width=True,
        type="primary",
    )
    st.caption("完成后可前往“查看账单”页面浏览已下载的账单。")

    if download_button:
        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        log_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s", datefmt=TIME_FMT_HMS
            )
        )

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

                if start_date is None or end_date is None:
                    st.error("日期范围不能为空")
                    st.stop()
                    raise RuntimeError("Unreachable")  # For type checker

                result: Dict[str, Any] = download_credit_card_emails(
                    start_date=start_date,
                    end_date=end_date,
                    log_level="INFO",
                    progress_callback=progress_callback,
                )

                status.update(
                    label=f"✅ 下载完成！共 {result['credit_card']} 封信用卡账单",
                    state="complete",
                )

                st.success(f"✅ 下载完成！共下载 {result['credit_card']} 封信用卡账单")

                final_log = log_stream.getvalue()
                if final_log:
                    with st.expander("📋 查看完整日志", expanded=False):
                        st.text_area(
                            "日志输出",
                            value=final_log,
                            height=300,
                            disabled=True,
                            key="final_log",
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
                        key="error_log",
                    )

        finally:
            root_logger.removeHandler(log_handler)
            root_logger.setLevel(original_level)

with tab_digital:
    st.caption(
        "仅下载最新一封；若本地已存在 CSV 会自动跳过，避免重复下载导致链接失效。"
    )

    pwd_col1, pwd_col2 = st.columns(2)
    with pwd_col1:
        alipay_pwd = st.text_input(
            "支付宝解压密码",
            type="password",
            help="用于解压支付宝账单 ZIP（不保存到本地）",
            key="alipay_pwd",
        )

    with pwd_col2:
        wechat_pwd = st.text_input(
            "微信解压密码",
            type="password",
            help="用于解压微信账单 ZIP（不保存到本地）",
            key="wechat_pwd",
        )

    # ==================== 下载按钮和进度显示（数字账单） ====================
    st.divider()
    digital_download_button = st.button(
        "🚀 下载微信/支付宝账单（最新）",
        use_container_width=True,
        type="primary",
    )
    st.caption("完成后可前往“查看账单”页面浏览已下载的账单。")

    if digital_download_button:
        status_labels: dict[str, str] = {
            str(DIGITAL_BILL_STATUS_DOWNLOADED): "已下载并解压",
            str(DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV): "本地已存在CSV，已跳过下载",
            str(
                DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP
            ): "本地已存在ZIP，已成功解压",
            str(
                DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP
            ): "本地ZIP解压失败（建议确认密码或手动解压）",
            str(DIGITAL_BILL_STATUS_NOT_FOUND): "未找到匹配的账单邮件",
            str(DIGITAL_BILL_STATUS_MISSING_PASSWORD): "缺少解压密码（无法继续）",
            str(DIGITAL_BILL_STATUS_FAILED): "处理失败（请查看日志）",
            str(DIGITAL_BILL_STATUS_UNKNOWN): "未知状态",
        }

        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        log_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s", datefmt=TIME_FMT_HMS
            )
        )

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

                digital_result: Dict[str, Any] = download_digital_payment_emails(
                    log_level="INFO",
                    alipay_pwd=alipay_pwd or None,
                    wechat_pwd=wechat_pwd or None,
                    progress_callback=progress_callback,
                )

                alipay_status = digital_result.get("alipay_status")
                wechat_status = digital_result.get("wechat_status")
                alipay_downloaded = digital_result.get("alipay", 0)
                wechat_downloaded = digital_result.get("wechat", 0)

                status.update(
                    label=f"✅ 处理完成：支付宝 {alipay_downloaded}，微信 {wechat_downloaded}",
                    state="complete",
                )

                st.success(
                    f"✅ 处理完成：支付宝 {alipay_downloaded} 个文件，微信 {wechat_downloaded} 个文件"
                )
                alipay_status_str = str(alipay_status or "")
                wechat_status_str = str(wechat_status or "")
                st.info(
                    f"支付宝：{status_labels.get(alipay_status_str, alipay_status_str)}；"
                    f"微信：{status_labels.get(wechat_status_str, wechat_status_str)}"
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
