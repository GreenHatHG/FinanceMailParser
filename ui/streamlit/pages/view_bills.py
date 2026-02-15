"""
账单查看页面

显示已下载的信用卡账单列表，支持查看账单详情
支持信用卡、支付宝、微信账单的统一展示
"""

import json

import streamlit as st

from financemailparser.application.billing.bill_queries import (
    load_bill_html,
    load_digital_bill_dataframe,
    scan_credit_card_bills,
)
from financemailparser.shared.constants import DATE_FMT_ISO, EMAILS_DIR

# 设置页面配置
st.set_page_config(page_title="查看账单", page_icon="📄", layout="wide")

st.title("📄 查看账单")
st.caption("查看从邮箱中下载的账单")
st.divider()


# ==================== 扫描账单 ====================
bills = scan_credit_card_bills(on_warning=st.warning)

# 加载支付宝/微信账单
alipay_result = load_digital_bill_dataframe(EMAILS_DIR / "alipay", "alipay")
wechat_result = load_digital_bill_dataframe(EMAILS_DIR / "wechat", "wechat")

alipay_df = alipay_result[0] if alipay_result else None
wechat_df = wechat_result[0] if wechat_result else None

has_any_data = bool(bills) or alipay_df is not None or wechat_df is not None

if not has_any_data:
    st.info("📭 暂无已下载的账单")
    st.markdown("请前往 **下载账单** 页面下载信用卡账单")
    st.stop()

# ==================== 统计信息 ====================
st.subheader("账单统计")

metric_cols = st.columns(4)

with metric_cols[0]:
    st.metric("信用卡账单数", len(bills))

with metric_cols[1]:
    banks = set(bill.bank for bill in bills)
    st.metric("银行数量", len(banks))

with metric_cols[2]:
    st.metric("支付宝交易数", len(alipay_df) if alipay_df is not None else 0)

with metric_cols[3]:
    st.metric("微信交易数", len(wechat_df) if wechat_df is not None else 0)

st.divider()

# ==================== 筛选器 ====================
st.subheader("筛选条件")

# 构建可用的账单分类选项（仅展示有数据的）
available_categories = []
if bills:
    available_categories.append("信用卡")
if alipay_df is not None:
    available_categories.append("支付宝")
if wechat_df is not None:
    available_categories.append("微信")

filter_col1, filter_col2, filter_col3 = st.columns(3)

with filter_col1:
    selected_categories = st.multiselect(
        "账单分类", options=available_categories, default=available_categories
    )

# 信用卡相关筛选器（仅在选中信用卡时显示）
selected_banks = []
date_range = None

if "信用卡" in selected_categories and bills:
    with filter_col2:
        all_banks = sorted(set(bill.bank for bill in bills))
        selected_banks = st.multiselect(
            "选择银行", options=all_banks, default=all_banks
        )

    with filter_col3:
        min_date = min(bill.date for bill in bills).date()
        max_date = max(bill.date for bill in bills).date()

        date_range = st.date_input(
            "选择日期范围",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

st.divider()

# ==================== 信用卡账单列表 ====================
if "信用卡" in selected_categories and bills:
    # 应用筛选
    filtered_bills = bills

    if selected_banks:
        filtered_bills = [
            bill for bill in filtered_bills if bill.bank in selected_banks
        ]

    if date_range and len(date_range) == 2:
        start_date, end_date = date_range
        filtered_bills = [
            bill
            for bill in filtered_bills
            if start_date <= bill.date.date() <= end_date
        ]

    st.subheader("信用卡账单")
    st.info(f"📊 找到 {len(filtered_bills)} 条信用卡账单")

    if not filtered_bills:
        st.warning("没有符合条件的信用卡账单")
    else:
        for bill in filtered_bills:
            with st.expander(
                f"📄 {bill.date.strftime(DATE_FMT_ISO)} - {bill.bank} - {bill.subject}"
            ):
                # 读取 HTML 内容
                try:
                    html_content = load_bill_html(html_path=bill.html_path)

                    # 创建按钮行
                    col1, col2 = st.columns([1, 5])

                    with col1:
                        # 在新标签页打开按钮：使用 JavaScript + Blob URL
                        html_escaped = json.dumps(html_content)
                        button_html = f"""
                        <button onclick="openInNewTab()" style="
                            padding: 0.5rem 1rem;
                            background-color: #FF4B4B;
                            color: white;
                            border: none;
                            border-radius: 0.25rem;
                            cursor: pointer;
                            font-size: 14px;
                        ">🔗 新标签页打开</button>

                        <script>
                        function openInNewTab() {{
                            const htmlContent = {html_escaped};
                            const blob = new Blob([htmlContent], {{type: 'text/html'}});
                            const url = URL.createObjectURL(blob);
                            window.open(url, '_blank');
                        }}
                        </script>
                        """
                        st.components.v1.html(button_html, height=50)

                    with col2:
                        # 下载按钮
                        st.download_button(
                            label="📥 下载 HTML 文件",
                            data=html_content,
                            file_name=f"{bill.folder_name}.html",
                            mime="text/html",
                        )

                    st.divider()

                    # 显示 HTML 内容
                    st.components.v1.html(html_content, height=600, scrolling=True)

                except Exception as e:
                    st.error(f"读取账单内容失败：{str(e)}")

# ==================== 支付宝账单 ====================
if "支付宝" in selected_categories and alipay_df is not None:
    st.subheader("支付宝账单")
    st.info(f"📊 共 {len(alipay_df)} 条支付宝交易记录")
    st.dataframe(alipay_df, width="stretch")

# ==================== 微信账单 ====================
if "微信" in selected_categories and wechat_df is not None:
    st.subheader("微信账单")
    st.info(f"📊 共 {len(wechat_df)} 条微信交易记录")
    st.dataframe(wechat_df, width="stretch")
