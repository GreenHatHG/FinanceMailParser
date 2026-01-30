"""
AI 配置管理页面

提供 AI 提供商、模型、API Key 等配置的管理功能
"""

import streamlit as st

from ai.config import AIConfigManager
from config import ConfigManager
from config.secrets import (
    MASTER_PASSWORD_ENV,
    MasterPasswordNotSetError,
    PlaintextSecretFoundError,
    SecretDecryptionError,
    master_password_is_set,
)

# 设置页面配置
st.set_page_config(page_title="AI 配置", page_icon="🤖")

st.title("🤖 AI 配置管理")

# 初始化 AIConfigManager
ai_config_manager = AIConfigManager()


def mask_secret(value: str, head: int = 4, tail: int = 4) -> str:
    """
    对敏感信息做部分掩码展示（不影响真实值的存储）。

    示例：
    - "sk-abcdefghijk" -> "sk-a***ijk"
    - "1234" -> "****"
    """
    if not value:
        return ""

    value = str(value)
    if len(value) <= head + tail:
        return "*" * len(value)

    return f"{value[:head]}***{value[-tail:]}"


# ==================== 当前配置状态区域 ====================
st.subheader("当前配置状态")

if not ai_config_manager.config_present():
    st.warning("❌ 尚未配置 AI")
else:
    try:
        config = ai_config_manager.load_config_strict()
        st.success(f"✅ 已配置 AI：{config['provider']} | {config['model']}")
    except MasterPasswordNotSetError:
        st.warning(
            f"🔒 检测到已加密的 AI 配置，但未设置环境变量 {MASTER_PASSWORD_ENV}，无法解锁。"
        )
        st.caption("请在启动 Streamlit 前设置该环境变量，然后重启应用。")
    except PlaintextSecretFoundError as e:
        st.error(f"❌ {str(e)}")
        st.warning("⚠️ 建议删除配置后重新设置")
    except SecretDecryptionError as e:
        st.error(f"❌ {str(e)}")
        st.warning("⚠️ 若忘记主密码，只能删除配置后重新设置")
    except Exception as e:
        st.error(f"❌ 配置加载失败：{str(e)}")
        st.warning("⚠️ 建议删除配置后重新设置")

st.divider()

# ==================== 配置表单区域 ====================
st.subheader("AI 配置")

# 预填充现有配置
existing_provider = "openai"
existing_model = ""
existing_api_key_real = ""
existing_api_key_masked = ""
existing_base_url = ""
existing_timeout = AIConfigManager.DEFAULT_TIMEOUT
existing_max_retries = AIConfigManager.DEFAULT_MAX_RETRIES
existing_retry_interval = AIConfigManager.DEFAULT_RETRY_INTERVAL

try:
    # Non-secret fields can be prefilled without decryption.
    raw_ai = ConfigManager().get_section(AIConfigManager.SECTION) or {}
    if isinstance(raw_ai, dict):
        existing_provider = str(
            raw_ai.get("provider", existing_provider) or existing_provider
        )
        existing_model = str(raw_ai.get("model", existing_model) or existing_model)
        existing_base_url = str(
            raw_ai.get("base_url", existing_base_url) or existing_base_url
        )
        existing_timeout = int(
            raw_ai.get("timeout", existing_timeout) or existing_timeout
        )
        existing_max_retries = int(
            raw_ai.get("max_retries", existing_max_retries) or existing_max_retries
        )
        existing_retry_interval = int(
            raw_ai.get("retry_interval", existing_retry_interval)
            or existing_retry_interval
        )
except Exception:
    pass

try:
    # Only show masked secret if we can decrypt it (requires env var).
    decrypted = ai_config_manager.load_config_strict()
    existing_api_key_real = decrypted.get("api_key", "") or ""
    existing_api_key_masked = mask_secret(existing_api_key_real)
except Exception:
    pass

with st.form("ai_config_form"):
    # 提供商选择
    provider = st.selectbox(
        "AI 提供商",
        ["openai", "gemini", "anthropic", "azure", "custom"],
        index=["openai", "gemini", "anthropic", "azure", "custom"].index(
            existing_provider
        )
        if existing_provider in ["openai", "gemini", "anthropic", "azure", "custom"]
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
                help="每次重试之间的等待时间",
            )

    # 操作按钮（三列布局）
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
    if not master_password_is_set():
        st.error(f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法保存加密配置。")
        st.stop()

    effective_api_key = api_key
    if existing_api_key_real and api_key == existing_api_key_masked:
        effective_api_key = existing_api_key_real

    if provider and model and effective_api_key:
        try:
            ai_config_manager.save_config(
                provider=provider,
                model=model,
                api_key=effective_api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                retry_interval=retry_interval,
            )
            st.success("✅ 配置保存成功！")
            st.rerun()  # 刷新页面以显示最新状态
        except ValueError as e:
            st.error(f"❌ 输入错误：{str(e)}")
        except Exception as e:
            st.error(f"❌ 保存失败：{str(e)}")
    else:
        st.warning("⚠️ 请填写完整信息（提供商、模型、API Key）")

# 测试连接
if test_button:
    if not master_password_is_set():
        st.error(f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法读取加密配置。")
        st.stop()

    effective_api_key = api_key
    if existing_api_key_real and api_key == existing_api_key_masked:
        effective_api_key = existing_api_key_real

    if provider and model and effective_api_key:
        with st.spinner("正在测试连接..."):
            success, message = ai_config_manager.test_connection(
                provider=provider,
                model=model,
                api_key=effective_api_key,
                base_url=base_url,
                timeout=timeout,
            )
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
    else:
        st.warning("⚠️ 请填写完整信息（提供商、模型、API Key）")

# 删除配置
if delete_button:
    if ai_config_manager.config_present():
        success = ai_config_manager.delete_config()
        if success:
            st.success("✅ 配置已删除")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error("❌ 删除失败")
    else:
        st.info("ℹ️ 当前没有 AI 配置")

st.divider()
