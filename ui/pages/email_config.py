"""
邮箱配置管理页面

提供邮箱地址和授权码的配置、测试连接、删除等功能
"""

import streamlit as st

from data_source.qq_email import QQEmailConfigManager
from config import ConfigManager
from config.secrets import (
    MASTER_PASSWORD_ENV,
    MasterPasswordNotSetError,
    PlaintextSecretFoundError,
    SecretDecryptionError,
    master_password_is_set,
)

# 设置页面配置
st.set_page_config(page_title="邮箱配置", page_icon="📧")

st.title("📧 邮箱配置管理")
st.caption("目前只支持配置QQ邮箱")
st.divider()

# 初始化 QQEmailConfigManager
qq_config_manager = QQEmailConfigManager()

def mask_secret(value: str, head: int = 2, tail: int = 2) -> str:
    """
    对敏感信息做部分掩码展示（不影响真实值的存储）。

    示例：
    - "abcdefg" -> "ab***fg"
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

raw_email_for_hint = ""
try:
    raw_qq = ConfigManager().get_value("email", "qq") or {}
    if isinstance(raw_qq, dict):
        raw_email_for_hint = str(raw_qq.get("email", "") or "").strip()
except Exception:
    raw_email_for_hint = ""

if not qq_config_manager.config_present():
    st.warning("❌ 尚未配置邮箱")
else:
    try:
        config = qq_config_manager.load_config_strict()
        st.success(f"✅ 已配置邮箱：{config['email']}")
    except MasterPasswordNotSetError:
        email_hint = f"：{raw_email_for_hint}" if raw_email_for_hint else ""
        st.warning(
            f"🔒 检测到已加密的邮箱配置{email_hint}，但未设置环境变量 {MASTER_PASSWORD_ENV}，无法解锁。"
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
st.subheader("邮箱配置")

# 预填充现有配置
existing_email = ""
existing_auth_code_real = ""
existing_auth_code_masked = ""
try:
    raw_qq = ConfigManager().get_value("email", "qq") or {}
    if isinstance(raw_qq, dict):
        existing_email = str(raw_qq.get("email", "") or "").strip()
except Exception:
    pass

try:
    decrypted = qq_config_manager.load_config_strict()
    existing_auth_code_real = decrypted.get("auth_code") or ""
    existing_auth_code_masked = mask_secret(existing_auth_code_real)
except Exception:
    pass

with st.form("email_config_form"):
    # 邮箱地址输入框
    email = st.text_input(
        "邮箱地址",
        value=existing_email,
        placeholder="your_email@qq.com",
        help="请输入您的 QQ 邮箱地址"
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
        )
    )

    # 创建三列布局
    col1, col2, col3 = st.columns(3)

    with col1:
        save_button = st.form_submit_button("💾 保存配置", use_container_width=True)

    with col2:
        test_button = st.form_submit_button("🔌 测试连接", use_container_width=True)

    with col3:
        delete_button = st.form_submit_button("🗑️ 删除配置", use_container_width=True, type="secondary")

# ==================== 按钮事件处理 ====================

# 保存配置
if save_button:
    if not master_password_is_set():
        st.error(f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法保存加密配置。")
        st.stop()

    effective_auth_code = auth_code
    if existing_auth_code_real and auth_code == existing_auth_code_masked:
        effective_auth_code = existing_auth_code_real

    if email and effective_auth_code:
        try:
            qq_config_manager.save_config(email, effective_auth_code)
            st.success("✅ 配置保存成功！")
            st.rerun()  # 刷新页面以显示最新状态
        except ValueError as e:
            st.error(f"❌ 输入错误：{str(e)}")
        except Exception as e:
            st.error(f"❌ 保存失败：{str(e)}")
    else:
        st.warning("⚠️ 请填写完整信息")

# 测试连接
if test_button:
    if not master_password_is_set():
        st.error(f"❌ 未设置环境变量 {MASTER_PASSWORD_ENV}，无法读取加密配置。")
        st.stop()

    effective_auth_code = auth_code
    if existing_auth_code_real and auth_code == existing_auth_code_masked:
        effective_auth_code = existing_auth_code_real

    if email and effective_auth_code:
        with st.spinner("正在测试连接..."):
            success, message = qq_config_manager.test_connection(email, effective_auth_code)
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
    else:
        st.warning("⚠️ 请填写完整信息")

# 删除配置
if delete_button:
    if qq_config_manager.config_present():
        success = qq_config_manager.delete_config()
        if success:
            st.success("✅ 配置已删除")
            st.rerun()  # 刷新页面以显示最新状态
        else:
            st.error("❌ 删除失败")
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
