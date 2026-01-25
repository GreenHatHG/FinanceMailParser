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

# 设置页面配置
st.set_page_config(
    page_title="FinanceMailParser",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("💰 FinanceMailParser")
st.write("金融账单邮件解析工具")
