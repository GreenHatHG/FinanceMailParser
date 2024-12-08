import json
from pathlib import Path
from email.message import Message
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

def save_email_content(email_folder: Path, email_data: Dict, email_message: Message, parsed_result: Optional[Dict] = None) -> None:
    """保存邮件内容到文件"""
    email_folder.mkdir(exist_ok=True)
    
    # 保存邮件元数据
    metadata = {
        'subject': email_data['subject'],
        'from': email_data['from'],
        'to': email_data.get('to', ''),
        'date': email_data['date'].isoformat(),
        'message_id': email_data['message_id'].decode() if isinstance(email_data['message_id'], bytes) else email_data['message_id'],
        'content_type': email_data.get('content_type', ''),
        'size': email_data.get('size', 0)
    }
    
    with open(email_folder / 'metadata.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    # 处理邮件内容
    for part in email_message.walk():
        _process_email_part(part, email_folder, email_data)
    
    # 保存解析结果
    if parsed_result:
        with open(email_folder / 'parsed_result.json', 'w', encoding='utf-8') as f:
            json.dump(parsed_result, f, ensure_ascii=False, indent=2)
    
    logger.info(f"邮件内容已保存到: {email_folder}")

def _process_email_part(part: Message, email_folder: Path, email_data: Dict) -> None:
    """处理邮件的各个部分"""
    if part.get_content_maintype() == 'text':
        _save_text_content(part, email_folder, email_data)
    elif part.get_content_maintype() != 'multipart':
        _save_attachment(part, email_folder)

def _save_text_content(part: Message, email_folder: Path, email_data: Dict) -> None:
    """保存文本内容"""
    content_type = part.get_content_type()
    charset = part.get_content_charset() or 'utf-8'
    
    try:
        content = part.get_payload(decode=True)
        if not content:
            return

        if content_type == 'text/html':
            _save_html_content(content, charset, email_folder, email_data)
        elif content_type == 'text/plain':
            _save_plain_text(content, charset, email_folder)
    except Exception as e:
        logger.warning(f"保存 {content_type} 内容时出错: {str(e)}")

def _save_html_content(content: bytes, charset: str, email_folder: Path, email_data: Dict) -> None:
    """保存HTML内容"""
    for enc in [charset, 'utf-8', 'gb18030', 'big5', 'iso-8859-1']:
        try:
            decoded_content = content.decode(enc)
            decoded_content = _ensure_html_structure(decoded_content, email_data['subject'])
            
            with open(email_folder / 'content.html', 'w', encoding='utf-8') as f:
                f.write(decoded_content)
            break
        except (UnicodeDecodeError, LookupError):
            continue

def _save_plain_text(content: bytes, charset: str, email_folder: Path) -> None:
    """保存纯文本内容"""
    for enc in [charset, 'utf-8', 'gb18030', 'big5', 'iso-8859-1']:
        try:
            decoded_content = content.decode(enc)
            with open(email_folder / 'content.txt', 'w', encoding='utf-8') as f:
                f.write(decoded_content)
            break
        except (UnicodeDecodeError, LookupError):
            continue

def _save_attachment(part: Message, email_folder: Path) -> None:
    """保存附件"""
    filename = part.get_filename()
    if filename:
        safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.'))
        if safe_filename:
            attachments_dir = email_folder / 'attachments'
            attachments_dir.mkdir(exist_ok=True)
            
            with open(attachments_dir / safe_filename, 'wb') as f:
                f.write(part.get_payload(decode=True))
            logger.info(f"已保存附件: {safe_filename}")

def _ensure_html_structure(content: str, subject: str) -> str:
    """确保HTML内容具有完整的结构"""
    if '<!DOCTYPE' not in content and '<html' not in content:
        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
</head>
<body>
{content}
</body>
</html>'''
    elif '<meta charset=' not in content.lower():
        return content.replace('<head>', '<head>\n    <meta charset="utf-8">')
    return content 