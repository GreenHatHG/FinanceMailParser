"""
Application services (use-case layer).

UI 层应只依赖这里暴露的函数接口，而不是直接依赖历史入口脚本。
"""

from app.services.bill_download import (
    download_credit_card_emails,
    download_digital_payment_emails,
)
from app.services.bill_parse_export import parse_downloaded_bills_to_beancount
from app.services.date_range import (
    calculate_date_range_for_quick_select,
    get_quick_select_options,
)
from app.services.email_config import QQEmailConfigService
from app.services.ai_process_beancount import prepare_ai_process_prompts
from app.services.bill_view import load_bill_html, scan_credit_card_bills

__all__ = [
    "QQEmailConfigService",
    "calculate_date_range_for_quick_select",
    "download_credit_card_emails",
    "download_digital_payment_emails",
    "get_quick_select_options",
    "parse_downloaded_bills_to_beancount",
    "prepare_ai_process_prompts",
    "scan_credit_card_bills",
    "load_bill_html",
]
