"""
FinanceMailParser - Streamlit 主入口

金融账单邮件解析工具的 Web 界面
"""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PAGES_DIR = Path(__file__).resolve().parent / "pages"


def render_home() -> None:
    st.title("💰 FinanceMailParser")
    st.write("金融账单邮件解析工具")
    st.markdown("#### 核心流程")
    st.markdown(
        "- 首次使用：邮箱配置 → 下载账单 → 查看账单 → 解析账单 → AI 配置 → AI 处理\n"
        "- 日常使用：下载账单 → 查看账单 → 解析账单 → AI 处理（需要时）"
    )
    st.divider()
    st.caption("补充说明")
    st.caption(
        "- 解析范围：微信、支付宝，以及信用卡（建设、招商、光大、农业、工商）\n"
        "- 下载来源：仅 QQ 邮箱账单；信用卡按日期范围筛选，微信/支付宝仅取最新一封\n"
        "- 导出/AI 处理：可将上述账单导出为 Beancount，并用于 AI 处理流程\n"
        "- 设计理念：工具聚焦支出记录，不覆盖收入；工具用于降低记录压力；整体接受“模糊的正确”，忽略极致的精准记账记录"
    )


# 设置页面配置
st.set_page_config(
    page_title="FinanceMailParser",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

home_page = st.Page(render_home, title="首页", icon="🏠", default=True)
email_config_page = st.Page(
    str(PAGES_DIR / "email_config.py"),
    title="邮箱配置",
    icon="📧",
)
expenses_account_rules_page = st.Page(
    str(PAGES_DIR / "expenses_account_rules.py"),
    title="消费账户规则",
    icon="🏷️",
)
transaction_filter_rules_page = st.Page(
    str(PAGES_DIR / "transaction_filter_rules.py"),
    title="交易过滤规则",
    icon="🚫",
)
download_bills_page = st.Page(
    str(PAGES_DIR / "download_bills.py"),
    title="下载账单",
    icon="📥",
)
view_bills_page = st.Page(
    str(PAGES_DIR / "view_bills.py"),
    title="查看账单",
    icon="📄",
)
parse_bills_page = st.Page(
    str(PAGES_DIR / "parse_bills.py"),
    title="解析账单",
    icon="🧾",
)
ai_config_page = st.Page(
    str(PAGES_DIR / "ai_config.py"),
    title="AI 配置",
    icon="🤖",
)
ai_process_page = st.Page(
    str(PAGES_DIR / "ai_process_beancount.py"),
    title="AI 处理",
    icon="🤖",
)

pages = [
    home_page,
    email_config_page,
    expenses_account_rules_page,
    transaction_filter_rules_page,
    download_bills_page,
    view_bills_page,
    parse_bills_page,
    ai_config_page,
    ai_process_page,
]

current_page = st.navigation(pages, position="hidden")

with st.sidebar:
    st.page_link(home_page, label="首页", icon="🏠")
    with st.expander("准备", expanded=True):
        st.page_link(email_config_page, label="邮箱配置", icon="📧")
    with st.expander("偏好", expanded=True):
        st.page_link(expenses_account_rules_page, label="消费账户规则", icon="🏷️")
        st.page_link(transaction_filter_rules_page, label="交易过滤规则", icon="🚫")
    with st.expander("账单处理", expanded=True):
        st.page_link(download_bills_page, label="下载账单", icon="📥")
        st.page_link(view_bills_page, label="查看账单", icon="📄")
        st.page_link(parse_bills_page, label="解析账单", icon="🧾")
    with st.expander("AI 处理", expanded=True):
        st.page_link(ai_config_page, label="AI 配置", icon="🤖")
        st.page_link(ai_process_page, label="AI 处理", icon="🤖")

current_page.run()
