"""
AI 配置管理

管理 AI 提供商的配置信息，包括 API Key、模型名称、超时设置等
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Tuple

from config import ConfigManager

logger = logging.getLogger(__name__)


class AIConfigManager:
    """
    AI 配置管理器

    配置存储结构（config.yaml）：
    ai:
      provider: openai
      model: gpt-4
      api_key: sk-xxx
      base_url: ""
      timeout: 600
      max_retries: 3
      retry_interval: 2
    """

    # 环境变量名称
    ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
    ENV_GEMINI_API_KEY = "GEMINI_API_KEY"
    ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
    ENV_AZURE_API_KEY = "AZURE_API_KEY"

    SECTION = "ai"

    # 默认值
    DEFAULT_TIMEOUT = 600
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_INTERVAL = 2

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self._config_manager = config_manager or ConfigManager()

    def config_exists(self) -> bool:
        """
        检查 AI 配置是否存在（仅检查配置文件，不包含环境变量）
        """
        ai_config = self._config_manager.get_section(self.SECTION)
        if not isinstance(ai_config, dict):
            return False

        provider = ai_config.get("provider", "").strip()
        model = ai_config.get("model", "").strip()
        api_key = ai_config.get("api_key", "").strip()

        return bool(provider) and bool(model) and bool(api_key)

    def save_config(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_interval: int = DEFAULT_RETRY_INTERVAL,
    ) -> None:
        """
        保存 AI 配置到 config.yaml

        Args:
            provider: AI 提供商（openai, gemini, anthropic, azure, custom）
            model: 模型名称
            api_key: API 密钥
            base_url: 自定义 API 端点（可选）
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）

        Raises:
            ValueError: 参数验证失败
        """
        if not provider or not provider.strip():
            raise ValueError("AI 提供商不能为空")
        if not model or not model.strip():
            raise ValueError("模型名称不能为空")
        if not api_key or not api_key.strip():
            raise ValueError("API Key 不能为空")

        if timeout < 10:
            raise ValueError("超时时间不能小于 10 秒")
        if max_retries < 0:
            raise ValueError("最大重试次数不能为负数")
        if retry_interval < 1:
            raise ValueError("重试间隔不能小于 1 秒")

        ai_config = {
            "provider": provider.strip(),
            "model": model.strip(),
            "api_key": api_key.strip(),
            "base_url": base_url.strip() if base_url else "",
            "timeout": timeout,
            "max_retries": max_retries,
            "retry_interval": retry_interval,
        }

        self._config_manager.set_section(self.SECTION, ai_config)
        logger.info(f"AI 配置已保存：{provider} / {model}")

    def load_config(self) -> Optional[Dict]:
        """
        从 config.yaml 加载 AI 配置

        Returns:
            配置字典，如果不存在返回 None
        """
        try:
            ai_config = self._config_manager.get_section(self.SECTION)
            if not isinstance(ai_config, dict):
                return None

            provider = ai_config.get("provider", "").strip()
            model = ai_config.get("model", "").strip()
            api_key = ai_config.get("api_key", "").strip()

            if not (provider and model and api_key):
                return None

            return {
                "provider": provider,
                "model": model,
                "api_key": api_key,
                "base_url": ai_config.get("base_url", "").strip(),
                "timeout": ai_config.get("timeout", self.DEFAULT_TIMEOUT),
                "max_retries": ai_config.get("max_retries", self.DEFAULT_MAX_RETRIES),
                "retry_interval": ai_config.get("retry_interval", self.DEFAULT_RETRY_INTERVAL),
            }
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

    def test_connection(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str = "",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Tuple[bool, str]:
        """
        测试 AI 连接

        发送一个简单的 prompt 验证配置是否正确

        Args:
            provider: AI 提供商
            model: 模型名称
            api_key: API 密钥
            base_url: 自定义 API 端点
            timeout: 超时时间

        Returns:
            (是否成功, 消息)
        """
        try:
            import litellm

            # 根据 provider 构建正确的 model 名称（显式指定提供商前缀）
            full_model = model
            if provider == "openai" and not model.startswith("openai/"):
                full_model = f"openai/{model}"
            elif provider == "gemini" and not model.startswith("gemini/"):
                full_model = f"gemini/{model}"
            elif provider == "azure" and not model.startswith("azure/"):
                full_model = f"azure/{model}"
            elif provider == "anthropic" and not model.startswith("anthropic/"):
                full_model = f"anthropic/{model}"

            # 构建请求参数
            kwargs = {
                "model": full_model,
                "messages": [{"role": "user", "content": "Hello"}],
                "api_key": api_key,
                "timeout": timeout,
                "max_tokens": 10,  # 限制 token 数量以节省成本
            }

            if base_url:
                kwargs["base_url"] = base_url

            # 调用 AI
            response = litellm.completion(**kwargs)

            logger.info("AI 连接测试成功")
            return True, "连接成功！"

        except Exception as e:
            error_msg = str(e).lower()

            # 根据不同的错误类型返回友好的提示
            if "authentication" in error_msg or "api key" in error_msg or "unauthorized" in error_msg:
                return False, f"API Key 错误，请检查是否正确复制\n\n详细错误：{str(e)}"
            elif "rate limit" in error_msg:
                return False, f"API 速率限制，请稍后再试\n\n详细错误：{str(e)}"
            elif "timeout" in error_msg:
                return False, f"连接超时，请检查网络或增加超时时间\n\n详细错误：{str(e)}"
            elif "not found" in error_msg and "model" in error_msg:
                return False, f"模型不存在，请检查模型名称是否正确\n\n详细错误：{str(e)}"
            else:
                logger.error(f"测试连接时出错: {str(e)}", exc_info=True)
                return False, f"连接失败：{str(e)}"

    def get_ai_config(self) -> Optional[Dict]:
        """
        获取 AI 配置（优先使用环境变量中的 API Key）

        读取优先级：
        1. 配置文件 + 环境变量 API Key（如果存在）
        2. 配置文件
        3. None

        Returns:
            配置字典，如果不存在返回 None
        """
        config = self.load_config()
        if not config:
            logger.debug("未找到 AI 配置")
            return None

        # 根据 provider 检查对应的环境变量
        provider = config["provider"]
        env_api_key = None

        if provider == "openai":
            env_api_key = os.getenv(self.ENV_OPENAI_API_KEY)
        elif provider == "gemini":
            env_api_key = os.getenv(self.ENV_GEMINI_API_KEY)
        elif provider == "anthropic":
            env_api_key = os.getenv(self.ENV_ANTHROPIC_API_KEY)
        elif provider == "azure":
            env_api_key = os.getenv(self.ENV_AZURE_API_KEY)

        if env_api_key:
            logger.debug(f"使用环境变量中的 {provider.upper()} API Key")
            config["api_key"] = env_api_key
        else:
            logger.debug("使用配置文件中的 API Key")

        return config
