from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from financemailparser.domain.models.digital_bill_status import (
    DIGITAL_BILL_STATUS_DOWNLOADED,
    DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP,
    DIGITAL_BILL_STATUS_FAILED,
    DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP,
    DIGITAL_BILL_STATUS_MISSING_PASSWORD,
    DIGITAL_BILL_STATUS_NOT_FOUND,
    DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV,
    DIGITAL_BILL_STATUS_UNKNOWN,
)
from financemailparser.infrastructure.config.business_rules import (
    get_email_subject_keywords,
)
from financemailparser.infrastructure.data_source.qq_email.config import (
    QQEmailConfigManager,
)
from financemailparser.infrastructure.data_source.qq_email.parser import QQEmailParser
from financemailparser.infrastructure.data_source.qq_email.utils import (
    create_storage_structure,
)
from financemailparser.infrastructure.statement_parsers.parse import find_csv_file
from financemailparser.shared.logger import set_global_log_level

logger = logging.getLogger(__name__)


def download_digital_payment_emails(
    log_level: str = "INFO",
    alipay_pwd: Optional[str] = None,
    wechat_pwd: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    """
    从QQ邮箱下载支付宝/微信支付账单（各取最新一封），并在本地不存在时才下载。

    说明：
    - 不按时间筛选，只取匹配关键词的最新一封邮件；
    - 为避免「一次性下载链接」失效，本地已存在 CSV 时直接跳过下载；
    - 若本地已存在 ZIP 但尚未解压出 CSV，则优先尝试解压（不再重新下载）。
    """

    def report(progress: int, message: str) -> None:
        if progress_callback:
            progress_callback(progress, 100, message)

    def find_latest_zip_file(directory: Path) -> Optional[Path]:
        zip_files = list(directory.rglob("*.zip"))
        if not zip_files:
            return None
        try:
            return max(zip_files, key=lambda p: p.stat().st_mtime)
        except Exception:
            return zip_files[-1]

    def extract_existing_zip(
        parser: QQEmailParser,
        zip_path: Path,
        bill_dir: Path,
        password: str,
    ) -> Optional[Path]:
        """Extract ZIP and return first CSV found under bill_dir."""
        extract_dir = bill_dir / zip_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)
        if not parser.extract_zip_file(str(zip_path), extract_dir, password):
            return None
        return find_csv_file(bill_dir)

    set_global_log_level(log_level)
    report(0, "准备下载支付宝/微信账单...")

    email_dir = create_storage_structure()
    alipay_dir = email_dir / "alipay"
    wechat_dir = email_dir / "wechat"

    result: Dict[str, object] = {
        "alipay": 0,
        "wechat": 0,
        "alipay_status": DIGITAL_BILL_STATUS_UNKNOWN,
        "wechat_status": DIGITAL_BILL_STATUS_UNKNOWN,
        "alipay_csv": None,
        "wechat_csv": None,
    }

    existing_alipay_csv = find_csv_file(alipay_dir) if alipay_dir.exists() else None
    if existing_alipay_csv:
        result["alipay_status"] = DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
        result["alipay_csv"] = str(existing_alipay_csv)

    existing_wechat_csv = find_csv_file(wechat_dir) if wechat_dir.exists() else None
    if existing_wechat_csv:
        result["wechat_status"] = DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
        result["wechat_csv"] = str(existing_wechat_csv)

    alipay_zip_path = None
    if (
        result["alipay_status"] != DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
        and alipay_dir.exists()
    ):
        alipay_zip_path = find_latest_zip_file(alipay_dir)

    wechat_zip_path = None
    if (
        result["wechat_status"] != DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
        and wechat_dir.exists()
    ):
        wechat_zip_path = find_latest_zip_file(wechat_dir)

    if (
        result["alipay_status"] == DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
        and result["wechat_status"] == DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
    ):
        report(100, "本地已存在支付宝/微信账单 CSV，已跳过下载。")
        return result

    qq_config_manager = QQEmailConfigManager()
    email, password = qq_config_manager.get_email_config()
    if not email or not password:
        logger.error("未配置邮箱信息，请先配置邮箱")
        raise ValueError("未配置邮箱信息")

    parser = QQEmailParser(email, password)
    report(10, "正在连接邮箱...")
    if not parser.login():
        logger.error("登录失败")
        raise ConnectionError("登录失败")
    report(20, "连接成功，开始处理支付宝/微信账单...")

    try:
        if (
            result["alipay_status"] != DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
            and alipay_zip_path
        ):
            if not alipay_pwd:
                result["alipay_status"] = DIGITAL_BILL_STATUS_MISSING_PASSWORD
            else:
                report(30, "检测到本地已有支付宝ZIP，尝试解压...")
                extracted_csv = extract_existing_zip(
                    parser, alipay_zip_path, alipay_dir, alipay_pwd
                )
                if extracted_csv:
                    result["alipay_status"] = DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP
                    result["alipay_csv"] = str(extracted_csv)
                else:
                    result["alipay_status"] = (
                        DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP
                    )

        if (
            result["wechat_status"] != DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV
            and wechat_zip_path
        ):
            if not wechat_pwd:
                result["wechat_status"] = DIGITAL_BILL_STATUS_MISSING_PASSWORD
            else:
                report(60, "检测到本地已有微信ZIP，尝试解压...")
                extracted_csv = extract_existing_zip(
                    parser, wechat_zip_path, wechat_dir, wechat_pwd
                )
                if extracted_csv:
                    result["wechat_status"] = DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP
                    result["wechat_csv"] = str(extracted_csv)
                else:
                    result["wechat_status"] = (
                        DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP
                    )

        if (
            result["alipay_status"]
            not in (
                DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV,
                DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP,
            )
            and not alipay_zip_path
        ):
            if not alipay_pwd:
                result["alipay_status"] = DIGITAL_BILL_STATUS_MISSING_PASSWORD
            else:
                report(40, "正在查找最新的支付宝账单邮件...")
                alipay_keywords = get_email_subject_keywords().get("alipay", []) or []
                alipay_emails = parser.get_latest_emails_by_subject_keywords(
                    alipay_keywords, case_insensitive=True, limit=1
                )
                if not alipay_emails:
                    result["alipay_status"] = DIGITAL_BILL_STATUS_NOT_FOUND
                else:
                    alipay_dir.mkdir(parents=True, exist_ok=True)
                    email_data = alipay_emails[0]
                    saved_files = parser.save_bill_attachments(email_data, alipay_dir)
                    zip_files = [p for p in saved_files if p.lower().endswith(".zip")]
                    if not zip_files:
                        result["alipay_status"] = DIGITAL_BILL_STATUS_FAILED
                    else:
                        zip_path = Path(zip_files[0])
                        extract_dir = alipay_dir / zip_path.stem
                        extract_dir.mkdir(parents=True, exist_ok=True)
                        if parser.extract_zip_file(
                            str(zip_path), extract_dir, alipay_pwd
                        ):
                            result["alipay"] = 1
                            result["alipay_status"] = DIGITAL_BILL_STATUS_DOWNLOADED
                            csv_path = find_csv_file(alipay_dir)
                            result["alipay_csv"] = str(csv_path) if csv_path else None
                        else:
                            result["alipay_status"] = DIGITAL_BILL_STATUS_FAILED

        if (
            result["wechat_status"]
            not in (
                DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV,
                DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP,
            )
            and not wechat_zip_path
        ):
            if not wechat_pwd:
                result["wechat_status"] = DIGITAL_BILL_STATUS_MISSING_PASSWORD
            else:
                report(70, "正在查找最新的微信账单邮件...")
                wechat_keywords = get_email_subject_keywords().get("wechat", []) or []
                wechat_emails = parser.get_latest_emails_by_subject_keywords(
                    wechat_keywords, case_insensitive=True, limit=1
                )
                if not wechat_emails:
                    result["wechat_status"] = DIGITAL_BILL_STATUS_NOT_FOUND
                else:
                    wechat_dir.mkdir(parents=True, exist_ok=True)
                    email_data = wechat_emails[0]
                    download_link = parser.extract_wechat_download_link(email_data)
                    if not download_link:
                        result["wechat_status"] = DIGITAL_BILL_STATUS_FAILED
                    else:
                        saved_file = parser.download_wechat_bill(
                            download_link, wechat_dir
                        )
                        if not saved_file:
                            result["wechat_status"] = DIGITAL_BILL_STATUS_FAILED
                        else:
                            zip_path = Path(saved_file)
                            extract_dir = wechat_dir / zip_path.stem
                            extract_dir.mkdir(parents=True, exist_ok=True)
                            if parser.extract_zip_file(
                                str(zip_path), extract_dir, wechat_pwd
                            ):
                                result["wechat"] = 1
                                result["wechat_status"] = DIGITAL_BILL_STATUS_DOWNLOADED
                                csv_path = find_csv_file(wechat_dir)
                                result["wechat_csv"] = (
                                    str(csv_path) if csv_path else None
                                )
                            else:
                                result["wechat_status"] = DIGITAL_BILL_STATUS_FAILED

        report(100, "支付宝/微信账单处理完成。")
        return result
    finally:
        parser.close()
