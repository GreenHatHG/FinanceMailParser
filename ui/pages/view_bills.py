"""
账单查看页面

显示已下载的信用卡账单列表，支持查看账单详情
"""

import streamlit as st
import json

from app.services import load_bill_html, scan_credit_card_bills
from constants import DATE_FMT_ISO

# 设置页面配置
st.set_page_config(page_title="查看账单", page_icon="📄", layout="wide")

st.title("📄 查看账单")
st.caption("查看从邮箱中下载的账单")
st.divider()


# ==================== 扫描账单 ====================
bills = scan_credit_card_bills(on_warning=st.warning)

if not bills:
    st.info("📭 暂无已下载的账单")
    st.markdown("请前往 **下载账单** 页面下载信用卡账单")
    st.stop()

# ==================== 统计信息 ====================
st.subheader("账单统计")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("账单总数", len(bills))

with col2:
    banks = set(bill["bank"] for bill in bills)
    st.metric("银行数量", len(banks))

st.divider()

# ==================== 筛选器 ====================
st.subheader("筛选条件")

col1, col2 = st.columns(2)

with col1:
    # 银行筛选
    all_banks = sorted(set(bill["bank"] for bill in bills))
    selected_banks = st.multiselect("选择银行", options=all_banks, default=all_banks)

with col2:
    # 日期范围筛选
    if bills:
        min_date = min(bill["date"] for bill in bills).date()
        max_date = max(bill["date"] for bill in bills).date()

        date_range = st.date_input(
            "选择日期范围",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

# 应用筛选
filtered_bills = bills

if selected_banks:
    filtered_bills = [bill for bill in filtered_bills if bill["bank"] in selected_banks]

if date_range and len(date_range) == 2:
    start_date, end_date = date_range
    filtered_bills = [
        bill for bill in filtered_bills if start_date <= bill["date"].date() <= end_date
    ]

st.info(f"📊 找到 {len(filtered_bills)} 条账单")

st.divider()

# ==================== 账单列表 ====================
st.subheader("账单列表")

if not filtered_bills:
    st.warning("没有符合条件的账单")
else:
    # 使用 expander 显示每个账单
    for bill in filtered_bills:
        with st.expander(
            f"📄 {bill['date'].strftime(DATE_FMT_ISO)} - {bill['bank']} - {bill['subject']}"
        ):
            # 读取 HTML 内容
            try:
                html_content = load_bill_html(
                    html_path=bill["html_path"],
                    on_warning=st.warning,
                )

                # 创建按钮行
                col1, col2 = st.columns([1, 5])

                with col1:
                    # 在新标签页打开按钮
                    # 使用 JavaScript 和 Blob URL
                    # 转义 HTML 内容
                    html_escaped = json.dumps(html_content)

                    # 创建带 JavaScript 的按钮
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
                        file_name=f"{bill['folder_name']}.html",
                        mime="text/html",
                    )

                st.divider()

                # 显示 HTML 内容
                st.components.v1.html(html_content, height=600, scrolling=True)

            except Exception as e:
                st.error(f"读取账单内容失败：{str(e)}")
