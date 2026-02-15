import logging
from email.header import decode_header
from pathlib import Path

from financemailparser.shared.constants import (
    EMAILS_DIR,
    FALLBACK_ENCODINGS,
)

logger = logging.getLogger(__name__)


def decode_email_header(header: str) -> str:
    """解码邮件标题，处理各种编码方式"""
    if not header:
        return ""

    try:
        decoded_parts = decode_header(header)
        result = ""

        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result += part.decode(charset or "utf-8", errors="replace")
                except LookupError:
                    for encoding in FALLBACK_ENCODINGS:
                        try:
                            result += part.decode(encoding)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
            else:
                result += str(part)

        return result.strip()

    except Exception as e:
        logger.error(f"邮件头解码失败: {str(e)}, 原文: {header}")
        return header


def create_storage_structure() -> Path:
    """创建邮件存储的文件夹结构"""
    EMAILS_DIR.mkdir(parents=True, exist_ok=True)
    return EMAILS_DIR
