"""
邮箱配置管理页面

提供邮箱地址和授权码的配置、测试连接、删除等功能
"""

import streamlit as st

from app.services.ui_config_facade import (
    delete_email_config_from_ui,
    get_email_config_ui_snapshot,
    save_email_config_from_ui,
    test_email_config_from_ui,
)

# 设置页面配置
st.set_page_config(page_title="邮箱配置", page_icon="📧")

st.title("📧 邮箱配置管理")
st.caption("目前只支持配置QQ邮箱")
st.divider()

snap = get_email_config_ui_snapshot(provider_key="qq")


# ==================== 当前配置状态区域 ====================
st.subheader("当前配置状态")

existing_email = str(snap.email_raw or "").strip()
existing_auth_code_masked = str(snap.auth_code_masked or "")

if not snap.present:
    st.warning("❌ 尚未配置邮箱")
else:
    if snap.unlocked and snap.email:
        st.success(f"✅ 已配置邮箱：{snap.email}")
    elif snap.state == "missing_master_password":
        email_hint = f"：{existing_email}" if existing_email else ""
        st.warning(
            f"🔒 检测到已加密的邮箱配置{email_hint}，但未设置环境变量 {snap.master_password_env}，无法解锁。"
        )
        st.caption("请在启动 Streamlit 前设置该环境变量，然后重启应用。")
    elif snap.state == "plaintext_secret":
        st.error(f"❌ {snap.error_message}")
        st.warning("⚠️ 建议删除配置后重新设置")
    elif snap.state == "decrypt_failed":
        st.error(f"❌ {snap.error_message}")
        st.warning("⚠️ 若忘记主密码，只能删除配置后重新设置")
    else:
        st.error(f"❌ 配置加载失败：{snap.error_message}")
        st.warning("⚠️ 建议删除配置后重新设置")

st.divider()

# ==================== 配置表单区域 ====================
st.subheader("邮箱配置")

# 预填充现有配置

with st.form("email_config_form"):
    # 邮箱地址输入框
    email = st.text_input(
        "邮箱地址",
        value=existing_email,
        placeholder="your_email@qq.com",
        help="请输入您的 QQ 邮箱地址",
    )

    # 授权码输入框
    auth_code = st.text_input(
        "授权码",
        value=existing_auth_code_masked,
        type="password",
        placeholder="请输入授权码",
        help=(
            "请输入 QQ 邮箱的 IMAP 授权码（不是 QQ 密码）。"
            "如果你已经保存过授权码，这里会显示部分掩码；保持不变表示沿用已保存的授权码。"
        ),
    )

    # 创建三列布局
    col1, col2, col3 = st.columns(3)

    with col1:
        save_button = st.form_submit_button("💾 保存配置", use_container_width=True)

    with col2:
        test_button = st.form_submit_button("🔌 测试连接", use_container_width=True)

    with col3:
        delete_button = st.form_submit_button(
            "🗑️ 删除配置", use_container_width=True, type="secondary"
        )

# ==================== 按钮事件处理 ====================

# 保存配置
if save_button:
    if email and auth_code:
        result = save_email_config_from_ui(
            email=email,
            auth_code_input=auth_code,
            auth_code_masked_placeholder=existing_auth_code_masked,
            provider_key="qq",
        )
        if result.ok:
            st.success("✅ 配置保存成功！")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error(result.message)
    else:
        st.warning("⚠️ 请填写完整信息")

# 测试连接
if test_button:
    if email and auth_code:
        with st.spinner("正在测试连接..."):
            result = test_email_config_from_ui(
                email=email,
                auth_code_input=auth_code,
                auth_code_masked_placeholder=existing_auth_code_masked,
                provider_key="qq",
            )
            if result.ok:
                st.success(result.message)
            else:
                st.error(result.message)
    else:
        st.warning("⚠️ 请填写完整信息")

# 删除配置
if delete_button:
    if snap.present:
        result = delete_email_config_from_ui(provider_key="qq")
        if result.ok:
            st.success("✅ 配置已删除")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error(result.message)
    else:
        st.info("ℹ️ 当前没有邮箱配置")

st.divider()

# ==================== 帮助信息区域 ====================
with st.expander("❓ 如何获取 QQ 邮箱授权码？"):
    st.markdown("""
    1. 登录 QQ 邮箱网页版（https://mail.qq.com）
    2. 进入「设置」→「账户」
    3. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
    4. 开启「IMAP/SMTP服务」
    5. 点击「生成授权码」，按提示操作（需要手机验证）
    6. 将生成的授权码复制到上方输入框

    **注意**：授权码不是 QQ 密码，是一串随机字符！
    """)
