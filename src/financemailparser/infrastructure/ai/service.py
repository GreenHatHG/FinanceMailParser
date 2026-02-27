"""
AI 服务层

封装 litellm 调用、重试逻辑、Token 统计等功能
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

import litellm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
    RetryCallState,
)

from financemailparser.infrastructure.ai.config import AIConfigManager

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
        on_retry: Callable[[int, str], None] | None = None,
    ) -> CallStats:
        """
        调用 AI 完成任务

        Args:
            prompt: 用户 prompt
            system_prompt: 系统 prompt（可选）
            on_retry: 可选回调（发生重试前调用），参数为 (retry_count, error_summary)

        Returns:
            CallStats: 调用统计信息
        """
        start_time = time.time()
        self._retry_count = 0

        try:
            config = self.config_manager.load_config_strict()
        except Exception as e:
            return CallStats(
                success=False,
                response=None,
                total_time=time.time() - start_time,
                retry_count=0,
                error_message=str(e),
            )

        provider = config.provider
        model = config.model
        max_retries = config.max_retries
        retry_interval = config.retry_interval

        # 构建消息
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            kwargs = config.to_litellm_completion_kwargs(messages=messages)
        except Exception as e:
            return CallStats(
                success=False,
                response=None,
                total_time=time.time() - start_time,
                retry_count=0,
                error_message=str(e),
            )

        # 定义重试装饰器
        @retry(
            stop=stop_after_attempt(max_retries + 1),  # +1 因为第一次不算重试
            wait=wait_random_exponential(
                multiplier=retry_interval,
                min=retry_interval,
                max=60,
            ),
            retry=retry_if_exception_type(Exception),
            reraise=True,
            before_sleep=lambda retry_state: self._log_retry(retry_state, on_retry),
        )
        def _call_with_retry():
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

    def _log_retry(
        self,
        retry_state: RetryCallState,
        on_retry: Callable[[int, str], None] | None = None,
    ) -> None:
        """
        记录重试日志

        Args:
            retry_state: 重试状态
            on_retry: 可选回调
        """
        self._retry_count += 1
        attempt_number = retry_state.attempt_number
        exception = retry_state.outcome.exception() if retry_state.outcome else None

        logger.warning(
            f"AI 调用失败，正在进行第 {attempt_number} 次重试... 错误：{exception}"
        )

        if on_retry is None:
            return

        exc_type = type(exception).__name__ if exception is not None else "UnknownError"
        exc_msg = str(exception).strip() if exception is not None else ""
        summary = f"{exc_type}: {exc_msg}" if exc_msg else exc_type
        try:
            on_retry(self._retry_count, summary)
        except Exception:
            # Best-effort: never let UI callback break the retry loop.
            logger.debug("on_retry callback failed", exc_info=True)
