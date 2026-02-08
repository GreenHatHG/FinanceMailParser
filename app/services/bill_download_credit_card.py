from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, Optional

from constants import DATE_FMT_COMPACT, DATE_FMT_ISO
from config.business_rules import get_email_subject_keywords
from data_source.qq_email import QQEmailConfigManager, QQEmailParser
from data_source.qq_email.email_processor import save_email_content
from data_source.qq_email.utils import create_storage_structure
from utils.logger import set_global_log_level

logger = logging.getLogger(__name__)


def _subject_contains_any_keyword(subject: str, keywords: list[str]) -> bool:
    """
    Case-insensitive substring match.

    Kept in app layer to avoid coupling data_source to business rules.
    """
    subject_norm = str(subject or "").lower()
    for keyword in keywords or []:
        kw = str(keyword or "").strip().lower()
        if kw and kw in subject_norm:
            return True
    return False


def download_credit_card_emails(
    start_date: datetime,
    end_date: datetime,
    log_level: str = "INFO",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, int]:
    """
    从QQ邮箱下载信用卡账单

    Args:
        start_date: 开始日期
        end_date: 结束日期
        log_level: 日志级别
        progress_callback: 进度回调函数 (current_step, total_steps, message)

    Returns:
        下载统计信息 {'credit_card': count}
    """
    set_global_log_level(log_level)
    logger.info("开始下载信用卡账单...")
    logger.info(
        "日期范围: %s 到 %s",
        start_date.strftime(DATE_FMT_ISO),
        end_date.strftime(DATE_FMT_ISO),
    )

    qq_config_manager = QQEmailConfigManager()
    email, password = qq_config_manager.get_email_config()
    if not email or not password:
        logger.error("未配置邮箱信息，请先配置邮箱")
        raise ValueError("未配置邮箱信息")

    parser = QQEmailParser(email, password)

    if progress_callback:
        progress_callback(0, 100, "正在连接邮箱...")

    if not parser.login():
        logger.error("登录失败")
        raise ConnectionError("登录失败")

    if progress_callback:
        progress_callback(10, 100, "连接成功")

    try:
        subject_keywords = get_email_subject_keywords()
        credit_card_keywords = subject_keywords.get("credit_card", []) or []

        email_dir = create_storage_structure()

        if progress_callback:
            progress_callback(15, 100, "正在搜索邮件...")

        email_list = parser.get_email_list(start_date, end_date)
        logger.info("找到 %s 封邮件", len(email_list))

        if progress_callback:
            progress_callback(20, 100, f"找到 {len(email_list)} 封邮件")

        saved_count = 0
        total_emails = len(email_list)
        if total_emails == 0:
            if progress_callback:
                progress_callback(100, 100, "未找到信用卡账单")
            logger.info("未找到信用卡账单")
            return {"credit_card": 0}

        for idx, email_data in enumerate(email_list):
            progress = 20 + int((idx + 1) / total_emails * 80)
            if progress_callback:
                progress_callback(
                    progress,
                    100,
                    f"正在处理邮件 {idx + 1}/{total_emails}: {email_data['subject'][:30]}...",
                )

            if _subject_contains_any_keyword(
                email_data.get("subject", ""), credit_card_keywords
            ):
                date_str = email_data["date"].strftime(DATE_FMT_COMPACT)
                safe_subject = "".join(
                    c
                    for c in email_data["subject"]
                    if c.isalnum() or c in (" ", "-", "_")
                )[:50]
                email_folder = email_dir / f"{date_str}_{safe_subject}"
                save_email_content(email_folder, email_data, email_data["raw_message"])
                saved_count += 1
                logger.info("已保存信用卡账单: %s", email_data["subject"])

        if progress_callback:
            progress_callback(100, 100, f"下载完成！共 {saved_count} 封信用卡账单")

        logger.info("下载完成，共保存 %s 封信用卡账单", saved_count)
        return {"credit_card": saved_count}

    except Exception as e:
        logger.error("下载信用卡账单时出错: %s", str(e), exc_info=True)
        raise
    finally:
        parser.close()
