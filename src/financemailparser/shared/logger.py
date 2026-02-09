import logging
from typing import Union


def set_global_log_level(level: Union[str, int]) -> None:
    """
    设置全局日志级别

    Args:
        level: 日志级别，可以是字符串('DEBUG', 'INFO'等)或logging模块的级别常量
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper())

    # 设置根日志器的级别
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 如果没有处理器，添加一个默认的控制台处理器
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 确保处理器的级别也被正确设置
    for handler in root_logger.handlers:
        handler.setLevel(level)
