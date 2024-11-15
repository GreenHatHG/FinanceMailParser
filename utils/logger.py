import logging
from typing import Optional


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """
    配置并返回一个logger实例
    
    Args:
        name: logger名称，如果为None则使用root logger
        
    Returns:
        配置好的logger实例
    """
    logger = logging.getLogger(name)

    # 如果logger已经有处理器，说明已经配置过，直接返回
    if logger.handlers:
        return logger

    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    # 配置控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

    return logger
