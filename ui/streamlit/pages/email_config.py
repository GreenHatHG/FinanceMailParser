"""
邮箱配置管理页面

提供邮箱地址和授权码的配置、测试连接、删除等功能
"""

import streamlit as st

from financemailparser.application.settings.email_facade import (
    delete_email_config_from_ui,
    get_email_config_ui_snapshot,
    get_email_provider_spec,
    save_email_config_from_ui,
    test_email_config_from_ui,
)

# 设置页面配置
st.set_page_config(page_title="邮箱配置", page_icon="📧")

st.title("📧 邮箱配置管理")
st.caption("目前只支持配置QQ邮箱")
st.divider()

provider_key = "qq"
spec = get_email_provider_spec(provider_key=provider_key)
snap = get_email_config_ui_snapshot(provider_key=provider_key)


# ==================== 当前配置状态区域 ====================
st.subheader("当前配置状态")

masked_placeholders = dict(snap.secret_masked or {})

if not snap.present:
    st.warning("❌ 尚未配置邮箱")
else:
    if snap.unlocked and snap.email:
        st.success(f"✅ 已配置邮箱：{snap.email}")
    elif snap.state == "missing_master_password":
        email_hint = f"：{snap.email_raw}" if snap.email_raw else ""
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

with st.form("email_config_form"):
    input_values: dict[str, str] = {}
    for field in spec.fields:
        if field.secret:
            default_value = str((snap.secret_masked or {}).get(field.key, "") or "")
            suffix = (
                "如果你已经保存过，该字段会显示部分掩码；保持不变表示沿用已保存值。"
            )
            help_text = (field.help + " " if field.help else "") + suffix
            widget_type = "password"
        else:
            default_value = str((snap.raw_values or {}).get(field.key, "") or "")
            help_text = field.help or ""
            widget_type = "default"

        value = st.text_input(
            field.label,
            value=default_value,
            help=help_text,
            type=widget_type,  # "default" | "password"
        )
        input_values[field.key] = value

    # 创建三列布局
    col1, col2, col3 = st.columns(3)

    with col1:
        save_button = st.form_submit_button("💾 保存配置", width="stretch")

    with col2:
        test_button = st.form_submit_button("🔌 测试连接", width="stretch")

    with col3:
        delete_button = st.form_submit_button(
            "🗑️ 删除配置", width="stretch", type="secondary"
        )

# ==================== 按钮事件处理 ====================

# 保存配置
if save_button:
    result = save_email_config_from_ui(
        provider_key=provider_key,
        values=input_values,
        masked_placeholders=masked_placeholders,
    )
    if result.ok:
        st.success("✅ 配置保存成功！")
        st.rerun()  # 刷新页面以显示最新状态
    else:
        st.error(result.message)

# 测试连接
if test_button:
    with st.spinner("正在测试连接..."):
        result = test_email_config_from_ui(
            provider_key=provider_key,
            values=input_values,
            masked_placeholders=masked_placeholders,
        )
        if result.ok:
            st.success(result.message)
        else:
            st.error(result.message)

# 删除配置
if delete_button:
    if snap.present:
        result = delete_email_config_from_ui(provider_key=provider_key)
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
