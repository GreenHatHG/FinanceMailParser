"""
AI 配置管理页面

提供 AI 提供商、模型、API Key 等配置的管理功能
"""

import streamlit as st

from financemailparser.application.ai.config_facade import (
    delete_ai_config_from_ui,
    get_ai_config_ui_snapshot,
    get_ai_provider_choices_for_ui,
    save_ai_config_from_ui,
    test_ai_config_from_ui,
)

# 设置页面配置
st.set_page_config(page_title="AI 配置", page_icon="🤖")

st.title("🤖 AI 配置管理")

snap = get_ai_config_ui_snapshot()
provider_choices = list(get_ai_provider_choices_for_ui())


# ==================== 当前配置状态区域 ====================
st.subheader("当前配置状态")

if not snap.present:
    st.warning("❌ 尚未配置 AI")
else:
    if snap.unlocked and snap.provider and snap.model:
        st.success(f"✅ 已配置 AI：{snap.provider} | {snap.model}")
    elif snap.state == "missing_master_password":
        st.warning(
            f"🔒 检测到已加密的 AI 配置，但未设置环境变量 {snap.master_password_env}，无法解锁。"
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
st.subheader("AI 配置")

# 预填充现有配置（非敏感字段无需解密；敏感字段只做掩码展示）
existing_provider = snap.provider_default or "openai"
existing_model = snap.model_default or ""
existing_api_key_masked = snap.api_key_masked or ""
existing_base_url = snap.base_url_default or ""
existing_timeout = int(snap.timeout_default)
existing_max_retries = int(snap.max_retries_default)
existing_retry_interval = int(snap.retry_interval_default)

with st.form("ai_config_form"):
    # 提供商选择
    provider = st.selectbox(
        "AI 提供商",
        provider_choices,
        index=provider_choices.index(existing_provider)
        if existing_provider in provider_choices
        else 0,
        help="选择你要使用的 AI 提供商",
    )

    # 模型名称
    model = st.text_input(
        "模型名称",
        value=existing_model,
        placeholder="例如：gpt-4o, gemini-pro, claude-sonnet-4.5",
        help="输入模型名称。注意：Gemini 模型会自动添加 'gemini/' 前缀",
    )

    # API Key（带掩码）
    api_key = st.text_input(
        "API Key",
        value=existing_api_key_masked,
        type="password",
        placeholder="sk-xxx 或 AIzaSyxxx",
        help=(
            "输入 API 密钥。"
            "如果你已经保存过 API Key，这里会显示部分掩码；保持不变表示沿用已保存的 API Key。"
        ),
    )

    # 高级选项（折叠）
    with st.expander("⚙️ 高级选项"):
        base_url = st.text_input(
            "Base URL（可选）",
            value=existing_base_url,
            placeholder="https://api.openai.com/v1",
            help="自定义 API 端点（用于代理或私有部署）。留空使用默认端点。",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            timeout = st.number_input(
                "超时时间（秒）",
                min_value=10,
                max_value=1800,
                value=existing_timeout,
                help="API 请求超时时间",
            )
        with col2:
            max_retries = st.number_input(
                "最大重试次数",
                min_value=0,
                max_value=10,
                value=existing_max_retries,
                help="失败后的最大重试次数",
            )
        with col3:
            retry_interval = st.number_input(
                "重试间隔（秒）",
                min_value=1,
                max_value=60,
                value=existing_retry_interval,
                help=(
                    "重试等待的基准/最小时间。实际等待采用指数退避并带抖动（jitter），"
                    "会在该值基础上逐次增加并随机化（上限约 60 秒）。"
                ),
            )

    # 操作按钮（三列布局）
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
    if provider and model and api_key:
        result = save_ai_config_from_ui(
            provider=provider,
            model=model,
            api_key_input=api_key,
            api_key_masked_placeholder=existing_api_key_masked,
            base_url=base_url,
            timeout=int(timeout),
            max_retries=int(max_retries),
            retry_interval=int(retry_interval),
        )
        if result.ok:
            st.success("✅ 配置保存成功！")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error(result.message)
    else:
        st.warning("⚠️ 请填写完整信息（提供商、模型、API Key）")

# 测试连接
if test_button:
    if provider and model and api_key:
        with st.spinner("正在测试连接..."):
            result = test_ai_config_from_ui(
                provider=provider,
                model=model,
                api_key_input=api_key,
                api_key_masked_placeholder=existing_api_key_masked,
                base_url=base_url,
                timeout=int(timeout),
            )
            if result.ok:
                st.success(result.message)
            else:
                st.error(result.message)
    else:
        st.warning("⚠️ 请填写完整信息（提供商、模型、API Key）")

# 删除配置
if delete_button:
    if snap.present:
        result = delete_ai_config_from_ui()
        if result.ok:
            st.success("✅ 配置已删除")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error(result.message)
    else:
        st.info("ℹ️ 当前没有 AI 配置")

st.divider()
