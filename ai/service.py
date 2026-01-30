"""
AI 服务层

封装 litellm 调用、重试逻辑、Token 统计等功能
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import litellm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
    RetryCallState,
)

from ai.config import AIConfigManager

logger = logging.getLogger(__name__)


@dataclass
class CallStats:
    """AI 调用统计信息"""

    success: bool  # 是否成功
    response: Optional[str]  # AI 返回内容
    total_time: float  # 总耗时（秒）
    retry_count: int  # 实际重试次数
    error_message: Optional[str]  # 错误信息
    # Token 统计
    prompt_tokens: int = 0  # 输入 token 数
    completion_tokens: int = 0  # 输出 token 数
    total_tokens: int = 0  # 总 token 数


class AIService:
    """
    AI 服务

    封装 litellm 调用、重试逻辑、Token 统计
    """

    def __init__(self, config_manager: AIConfigManager):
        """
        初始化 AI 服务

        Args:
            config_manager: AI 配置管理器
        """
        self.config_manager = config_manager
        self._retry_count = 0  # 用于跟踪重试次数

    def call_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> CallStats:
        """
        调用 AI 完成任务

        Args:
            prompt: 用户 prompt
            system_prompt: 系统 prompt（可选）

        Returns:
            CallStats: 调用统计信息
        """
        start_time = time.time()
        self._retry_count = 0

        try:
            config = self.config_manager.get_ai_config()
        except Exception as e:
            return CallStats(
                success=False,
                response=None,
                total_time=time.time() - start_time,
                retry_count=0,
                error_message=str(e),
            )

        if not config:
            return CallStats(
                success=False,
                response=None,
                total_time=time.time() - start_time,
                retry_count=0,
                error_message="未找到 AI 配置，请先配置 AI",
            )

        provider = config["provider"]
        model = config["model"]
        api_key = config["api_key"]
        base_url = config.get("base_url", "")
        timeout = config.get("timeout", 600)
        max_retries = config.get("max_retries", 3)
        retry_interval = config.get("retry_interval", 2)

        # 构建正确的模型名称（显式指定提供商前缀）
        full_model = model
        if provider == "openai" and not model.startswith("openai/"):
            full_model = f"openai/{model}"
        elif provider == "gemini" and not model.startswith("gemini/"):
            full_model = f"gemini/{model}"
        elif provider == "azure" and not model.startswith("azure/"):
            full_model = f"azure/{model}"
        elif provider == "anthropic" and not model.startswith("anthropic/"):
            full_model = f"anthropic/{model}"

        # 构建消息
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 定义重试装饰器
        @retry(
            stop=stop_after_attempt(max_retries + 1),  # +1 因为第一次不算重试
            wait=wait_fixed(retry_interval),
            retry=retry_if_exception_type(
                (
                    litellm.Timeout,
                    litellm.RateLimitError,
                    litellm.ServiceUnavailableError,
                    litellm.APIConnectionError,
                )
            ),
            reraise=True,
            before_sleep=lambda retry_state: self._log_retry(retry_state),
        )
        def _call_with_retry():
            kwargs = {
                "model": full_model,
                "messages": messages,
                "api_key": api_key,
                "timeout": timeout,
            }

            if base_url:
                kwargs["base_url"] = base_url

            return litellm.completion(**kwargs)

        try:
            # 调用 AI（带重试）
            response = _call_with_retry()

            # 提取响应内容
            content = response.choices[0].message.content

            # 提取 usage 信息
            usage = response.usage if hasattr(response, "usage") else None
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            total_time = time.time() - start_time

            logger.info(
                f"AI 调用成功：{provider}/{model}，"
                f"耗时 {total_time:.2f}s，"
                f"重试 {self._retry_count} 次，"
                f"tokens {total_tokens}"
            )

            return CallStats(
                success=True,
                response=content,
                total_time=total_time,
                retry_count=self._retry_count,
                error_message=None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

        except Exception as e:
            total_time = time.time() - start_time
            error_msg = str(e)

            logger.error(f"AI 调用失败：{error_msg}", exc_info=True)

            return CallStats(
                success=False,
                response=None,
                total_time=total_time,
                retry_count=self._retry_count,
                error_message=error_msg,
            )

    def _log_retry(self, retry_state: RetryCallState) -> None:
        """
        记录重试日志

        Args:
            retry_state: 重试状态
        """
        self._retry_count += 1
        attempt_number = retry_state.attempt_number
        exception = retry_state.outcome.exception() if retry_state.outcome else None

        logger.warning(
            f"AI 调用失败，正在进行第 {attempt_number} 次重试... 错误：{exception}"
        )
