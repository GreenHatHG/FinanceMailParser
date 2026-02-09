"""
QQ 邮箱相关配置管理

将 QQ 邮箱的“凭证读取 / 保存 / 删除 / 连通性测试”等逻辑放在 data_source 侧，
避免与通用的配置存取（ConfigManager）职责混杂，便于未来扩展更多邮箱提供商。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from financemailparser.infrastructure.config.config_manager import (
    ConfigManager,
    get_config_manager,
)
from financemailparser.infrastructure.config.secrets import (
    PlaintextSecretFoundError,
    SecretBox,
    SecretError,
    is_encrypted_value,
)
from financemailparser.infrastructure.data_source.qq_email.exceptions import LoginError
from financemailparser.infrastructure.data_source.qq_email.parser import QQEmailParser

logger = logging.getLogger(__name__)


class QQEmailConfigManager:
    """
    QQ 邮箱配置管理器

    配置存储结构（config.yaml）：
    email:
      qq:
        email: xxx@qq.com
        auth_code: ENC[v1|...]
    """

    SECTION = "email"
    PROVIDER_KEY = "qq"
    _AUTH_CODE_AAD = "email.qq.auth_code"

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self._config_manager = config_manager or get_config_manager()

    def config_exists(self) -> bool:
        """
        检查 QQ 邮箱配置是否存在且可用（包含解密校验）。
        """
        try:
            return self.load_config_strict() is not None
        except Exception:
            return False

    def config_present(self) -> bool:
        """
        检查 QQ 邮箱配置是否“存在于文件中”（不要求可解密）。

        用途：UI 展示状态、允许删除等场景。
        """
        qq_config = self._config_manager.get_value(self.SECTION, self.PROVIDER_KEY)
        if not isinstance(qq_config, dict):
            return False

        raw_email = qq_config.get("email")
        raw_auth_code = qq_config.get("auth_code")
        email = str(raw_email).strip() if raw_email is not None else ""
        auth_code = str(raw_auth_code).strip() if raw_auth_code is not None else ""
        return bool(email) and bool(auth_code)

    def save_config(self, email: str, auth_code: str) -> None:
        """
        保存 QQ 邮箱配置到 config.yaml
        """
        if not email or not email.strip():
            raise ValueError("邮箱地址不能为空")
        if not auth_code or not auth_code.strip():
            raise ValueError("授权码不能为空")

        encrypted_auth_code = SecretBox.encrypt(
            auth_code.strip(), aad=self._AUTH_CODE_AAD
        )
        qq_config = {"email": email.strip(), "auth_code": encrypted_auth_code}
        self._config_manager.set_value(self.SECTION, self.PROVIDER_KEY, qq_config)

    def load_config_strict(self) -> Dict[str, str]:
        """
        从 config.yaml 加载 QQ 邮箱配置（严格模式，会尝试解密并在失败时抛出异常）。

        Raises:
            MasterPasswordNotSetError: 未设置主密码环境变量
            PlaintextSecretFoundError: 发现明文敏感信息
            SecretDecryptionError: 解密失败（密码错误或数据损坏）
        """
        qq_config = self._config_manager.get_value(self.SECTION, self.PROVIDER_KEY)
        if not isinstance(qq_config, dict):
            raise ValueError("未找到 QQ 邮箱配置")

        raw_email = qq_config.get("email")
        raw_auth_code = qq_config.get("auth_code")
        email = str(raw_email).strip() if raw_email is not None else ""
        auth_code_enc = str(raw_auth_code).strip() if raw_auth_code is not None else ""
        if not (email and auth_code_enc):
            raise ValueError("QQ 邮箱配置不完整")

        if not is_encrypted_value(auth_code_enc):
            raise PlaintextSecretFoundError(
                "检测到 QQ 邮箱授权码以明文存储于 config.yaml。请删除配置后重新设置。"
            )

        auth_code = SecretBox.decrypt(auth_code_enc, aad=self._AUTH_CODE_AAD)
        return {"email": email, "auth_code": auth_code}

    def load_config(self) -> Optional[Dict[str, str]]:
        """
        从 config.yaml 加载 QQ 邮箱配置（宽松模式：失败返回 None）。
        """
        try:
            return self.load_config_strict()
        except SecretError as e:
            logger.error(f"加载 QQ 邮箱配置失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"加载 QQ 邮箱配置失败: {str(e)}")
            return None

    def delete_config(self) -> bool:
        """
        删除 config.yaml 中的 QQ 邮箱配置
        """
        return self._config_manager.delete_value(self.SECTION, self.PROVIDER_KEY)

    def test_connection(self, email: str, auth_code: str) -> Tuple[bool, str]:
        """
        测试 QQ 邮箱连接
        """
        try:
            parser = QQEmailParser(email, auth_code)
            parser.login()
            parser.close()
            logger.info("邮箱连接测试成功")
            return True, "连接成功！"

        except LoginError as e:
            error_msg = str(e).lower()
            if "authentication failed" in error_msg:
                return False, "授权码错误，请检查是否正确复制"
            if "nodename nor servname" in error_msg:
                return False, "网络连接失败，请检查网络设置"
            if "protocol error" in error_msg:
                return False, "IMAP 服务未开启，请在 QQ 邮箱设置中开启"
            return False, f"登录失败：{str(e)}"

        except Exception as e:
            logger.error(f"测试连接时出错: {str(e)}", exc_info=True)
            return False, f"未知错误：{str(e)}"

    def get_email_config(self) -> Tuple[Optional[str], Optional[str]]:
        """
        获取 QQ 邮箱配置（仅从配置文件读取）
        """
        try:
            saved = self.load_config_strict()
            logger.debug("使用配置文件配置")
            return saved["email"], saved["auth_code"]
        except SecretError as e:
            # Make CLI/UI error messages more actionable.
            raise ValueError(str(e)) from e
        except Exception:
            saved = None

        logger.debug("未找到邮箱配置")
        return None, None
