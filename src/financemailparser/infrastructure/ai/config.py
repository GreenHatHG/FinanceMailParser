"""
AI 配置管理

管理 AI 提供商的配置信息，包括 API Key、模型名称、超时设置等
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, ClassVar, Mapping, Optional, Tuple

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
from financemailparser.infrastructure.ai.providers import ensure_litellm_model_prefix

logger = logging.getLogger(__name__)


def _norm_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


@dataclass(frozen=True, slots=True)
class AIConfig:
    """
    Decrypted AI config used across app layers.

    Notes:
    - `api_key` is plaintext in-memory (decrypted). Persisting must encrypt it via `to_persisted_section`.
    - Validation rules mirror UI/service expectations to fail fast on bad inputs.
    """

    DEFAULT_TIMEOUT: ClassVar[int] = 600
    DEFAULT_MAX_RETRIES: ClassVar[int] = 3
    DEFAULT_RETRY_INTERVAL: ClassVar[int] = 2

    provider: str
    model: str
    api_key: str
    base_url: str = ""
    timeout: int = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_interval: int = DEFAULT_RETRY_INTERVAL

    def __post_init__(self) -> None:
        provider = _norm_str(self.provider)
        model = _norm_str(self.model)
        api_key = _norm_str(self.api_key)
        base_url = _norm_str(self.base_url)

        timeout = _coerce_int(self.timeout, self.DEFAULT_TIMEOUT)
        max_retries = _coerce_int(self.max_retries, self.DEFAULT_MAX_RETRIES)
        retry_interval = _coerce_int(self.retry_interval, self.DEFAULT_RETRY_INTERVAL)

        if not provider:
            raise ValueError("AI 提供商不能为空")
        if not model:
            raise ValueError("模型名称不能为空")
        if not api_key:
            raise ValueError("API Key 不能为空")

        if timeout < 10:
            raise ValueError("超时时间不能小于 10 秒")
        if max_retries < 0:
            raise ValueError("最大重试次数不能为负数")
        if retry_interval < 1:
            raise ValueError("重试间隔不能小于 1 秒")

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "retry_interval", retry_interval)

    @classmethod
    def from_section_strict(
        cls, section: Mapping[str, Any], *, api_key_aad: str
    ) -> "AIConfig":
        provider = _norm_str(section.get("provider", ""))
        model = _norm_str(section.get("model", ""))
        api_key_enc = _norm_str(section.get("api_key"))

        if not (provider and model and api_key_enc):
            raise ValueError("AI 配置不完整")

        if not is_encrypted_value(api_key_enc):
            raise PlaintextSecretFoundError(
                "检测到 AI API Key 以明文存储于 config.yaml。请删除配置后重新设置。"
            )

        api_key = SecretBox.decrypt(api_key_enc, aad=api_key_aad)

        timeout = _coerce_int(
            section.get("timeout", cls.DEFAULT_TIMEOUT), cls.DEFAULT_TIMEOUT
        )
        max_retries = _coerce_int(
            section.get("max_retries", cls.DEFAULT_MAX_RETRIES), cls.DEFAULT_MAX_RETRIES
        )
        retry_interval = _coerce_int(
            section.get("retry_interval", cls.DEFAULT_RETRY_INTERVAL),
            cls.DEFAULT_RETRY_INTERVAL,
        )

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=_norm_str(section.get("base_url", "")),
            timeout=timeout,
            max_retries=max_retries,
            retry_interval=retry_interval,
        )

    def to_persisted_section(self, *, api_key_aad: str) -> dict[str, Any]:
        # Encrypt API Key before persisting.
        encrypted_api_key = SecretBox.encrypt(self.api_key, aad=api_key_aad)
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": encrypted_api_key,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
        }

    def litellm_model_name(self) -> str:
        """
        Build the correct model name for litellm (explicit provider prefix when needed).
        """
        return ensure_litellm_model_prefix(self.provider, self.model) or self.model

    def to_litellm_completion_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """
        Build a kwargs dict for `litellm.completion(**kwargs)` based on this config.

        Centralizing this reduces duplication across service/test paths and avoids
        drift when adding new litellm parameters in the future.
        """
        kwargs: dict[str, Any] = {
            "model": self.litellm_model_name(),
            "messages": messages,
            "api_key": self.api_key,
            "timeout": self.timeout,
        }

        if self.base_url:
            kwargs["base_url"] = self.base_url

        if max_tokens is not None:
            kwargs["max_tokens"] = int(max_tokens)

        if extra:
            kwargs.update(extra)

        return kwargs


class AIConfigManager:
    """
    AI 配置管理器

    配置存储结构（config.yaml）：
    ai:
      provider: openai
      model: gpt-4
      api_key: ENC[v1|...]
      base_url: ""
      timeout: 600
      max_retries: 3
      retry_interval: 2
    """

    SECTION = "ai"
    _API_KEY_AAD = "ai.api_key"

    # 默认值
    DEFAULT_TIMEOUT = AIConfig.DEFAULT_TIMEOUT
    DEFAULT_MAX_RETRIES = AIConfig.DEFAULT_MAX_RETRIES
    DEFAULT_RETRY_INTERVAL = AIConfig.DEFAULT_RETRY_INTERVAL

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self._config_manager = config_manager or get_config_manager()

    def config_present(self) -> bool:
        """
        检查 AI 配置是否“存在于文件中”（不要求可解密）。

        用途：UI 展示状态、允许删除等场景。
        """
        ai_config = self._config_manager.get_section(self.SECTION)
        if not isinstance(ai_config, dict):
            return False

        provider = _norm_str(ai_config.get("provider", ""))
        model = _norm_str(ai_config.get("model", ""))
        api_key = _norm_str(ai_config.get("api_key"))

        return bool(provider) and bool(model) and bool(api_key)

    def save_config(self, config: AIConfig) -> None:
        """
        保存 AI 配置到 config.yaml

        Args:
            config: 解密态配置对象（内存中包含明文 api_key）

        Raises:
            ValueError: 参数验证失败
        """
        ai_config = config.to_persisted_section(api_key_aad=self._API_KEY_AAD)
        self._config_manager.set_section(self.SECTION, ai_config)
        logger.info(f"AI 配置已保存：{config.provider} / {config.model}")

    def load_config_strict(self) -> AIConfig:
        """
        从 config.yaml 加载 AI 配置（严格模式，会尝试解密并在失败时抛出异常）。

        Raises:
            MasterPasswordNotSetError: 未设置主密码环境变量
            PlaintextSecretFoundError: 发现明文敏感信息
            SecretDecryptionError: 解密失败（密码错误或数据损坏）
        """
        ai_config = self._config_manager.get_section(self.SECTION)
        if not isinstance(ai_config, dict):
            raise ValueError("未找到 AI 配置")

        return AIConfig.from_section_strict(ai_config, api_key_aad=self._API_KEY_AAD)

    def load_config(self) -> Optional[AIConfig]:
        """
        从 config.yaml 加载 AI 配置（宽松模式：失败返回 None）。
        """
        try:
            return self.load_config_strict()
        except SecretError as e:
            logger.error(f"加载 AI 配置失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"加载 AI 配置失败: {str(e)}")
            return None

    def delete_config(self) -> bool:
        """
        删除 config.yaml 中的 AI 配置

        Returns:
            是否删除成功
        """
        return self._config_manager.delete_section(self.SECTION)

    def test_connection(self, config: AIConfig) -> Tuple[bool, str]:
        """
        测试 AI 连接

        发送一个简单的 prompt 验证配置是否正确

        Args:
            config: 解密态配置对象（内存中包含明文 api_key）

        Returns:
            (是否成功, 消息)
        """
        try:
            import litellm

            # 构建请求参数（限制 token 数量以节省成本）
            kwargs = config.to_litellm_completion_kwargs(
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
            )

            # 调用 AI
            litellm.completion(**kwargs)

            logger.info("AI 连接测试成功")
            return True, "连接成功！"

        except Exception as e:
            error_msg = str(e).lower()

            # 根据不同的错误类型返回友好的提示
            if (
                "authentication" in error_msg
                or "api key" in error_msg
                or "unauthorized" in error_msg
            ):
                return False, f"API Key 错误，请检查是否正确复制\n\n详细错误：{str(e)}"
            elif "rate limit" in error_msg:
                return False, f"API 速率限制，请稍后再试\n\n详细错误：{str(e)}"
            elif "timeout" in error_msg:
                return (
                    False,
                    f"连接超时，请检查网络或增加超时时间\n\n详细错误：{str(e)}",
                )
            elif "not found" in error_msg and "model" in error_msg:
                return (
                    False,
                    f"模型不存在，请检查模型名称是否正确\n\n详细错误：{str(e)}",
                )
            else:
                logger.error(f"测试连接时出错: {str(e)}", exc_info=True)
                return False, f"连接失败：{str(e)}"
