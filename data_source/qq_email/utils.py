import json
import logging
from email.header import decode_header
from pathlib import Path

from constants import EMAILS_DIR

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
                except (UnicodeDecodeError, LookupError):
                    for encoding in ["utf-8", "gb18030", "big5", "iso-8859-1"]:
                        try:
                            result += part.decode(encoding)
                            break
                        except UnicodeDecodeError:
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


def save_parsed_result(folder_path: Path, parsed_result: dict) -> None:
    """保存解析结果到JSON文件"""
    with open(folder_path / "parsed_result.json", "w", encoding="utf-8") as f:
        json.dump(parsed_result, f, ensure_ascii=False, indent=2)
