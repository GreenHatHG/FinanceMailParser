"""
日志捕获工具

用于在 Streamlit 应用中捕获和显示后端日志
"""

import logging
from typing import Callable, List
from threading import Lock


class StreamlitLogHandler(logging.Handler):
    """
    自定义日志处理器，将日志消息发送到回调函数

    用于在 Streamlit 应用中实时捕获和显示后端日志
    """

    def __init__(self, callback: Callable[[str], None], level=logging.INFO):
        """
        初始化日志处理器

        Args:
            callback: 日志消息回调函数
            level: 日志级别
        """
        super().__init__(level)
        self.callback = callback
        self.lock = Lock()

    def emit(self, record):
        """
        发送日志记录

        Args:
            record: 日志记录对象
        """
        try:
            log_entry = self.format(record)
            with self.lock:
                self.callback(log_entry)
        except Exception:
            self.handleError(record)


class LogCapture:
    """
    日志捕获器，用于收集日志消息

    线程安全的日志收集器，支持追加、获取和清空日志
    """

    def __init__(self, max_lines: int = 1000):
        """
        初始化日志捕获器

        Args:
            max_lines: 最大日志行数，超过后自动删除旧日志
        """
        self.logs: List[str] = []
        self.max_lines = max_lines
        self.lock = Lock()

    def append(self, message: str):
        """
        追加日志消息

        Args:
            message: 日志消息
        """
        with self.lock:
            self.logs.append(message)
            # 限制日志行数，避免内存溢出
            if len(self.logs) > self.max_lines:
                self.logs = self.logs[-self.max_lines :]

    def get_logs(self) -> str:
        """
        获取所有日志（换行符连接）

        Returns:
            所有日志消息，用换行符连接
        """
        with self.lock:
            return "\n".join(self.logs)

    def clear(self):
        """清空日志"""
        with self.lock:
            self.logs.clear()
