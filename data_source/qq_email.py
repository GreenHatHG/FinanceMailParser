import email
import imaplib
import json
import os
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import List, Dict, Optional

from utils.logger import setup_logger


class QQEmailParser:
    def __init__(self, email_address: str, password: str):
        self.email_address = email_address
        self.password = password
        self.imap_server = "imap.qq.com"
        self.conn = None
        self.logger = setup_logger(__name__)

    def login(self) -> bool:
        """连接并登录到QQ邮箱"""
        try:
            self.logger.info(f"正在连接到 {self.imap_server}...")
            self.conn = imaplib.IMAP4_SSL(self.imap_server)
            self.conn.login(self.email_address, self.password)
            self.logger.info("登录成功")
            return True
        except Exception as e:
            self.logger.error(f"登录失败: {str(e)}")
            return False

    def get_email_list(self, folder: str = "INBOX", start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None) -> List[Dict]:
        """获取指定文件夹中的邮件列表
        
        Args:
            folder: 邮件文件夹名称
            start_date: 开始日期，如果为None则不限制开始日期
            end_date: 结束日期，如果为None则不限制结束日期
        """
        if not self.conn:
            raise ConnectionError("未连接到邮箱服务器")

        self.conn.select(folder)

        # 构建搜索条件
        search_criteria = []

        if start_date:
            # SINCE 包含指定日期
            date_since = start_date.strftime("%d-%b-%Y")
            search_criteria.append(f'SINCE "{date_since}"')

        if end_date:
            # BEFORE 不包含指定日期，所以要加1天
            date_before = (end_date + timedelta(days=1)).strftime("%d-%b-%Y")
            search_criteria.append(f'BEFORE "{date_before}"')

        # 如果没有指定任何日期条件，获取所有邮件
        final_criteria = " ".join(search_criteria) if search_criteria else "ALL"

        self.logger.info(f"搜索条件: {final_criteria}")
        _, messages = self.conn.search(None, final_criteria)

        total_messages = len(messages[0].split())
        self.logger.info(f"找到 {total_messages} 封邮件")

        email_list = []
        for num in messages[0].split():
            _, msg = self.conn.fetch(num, '(RFC822)')
            email_message = email.message_from_bytes(msg[0][1])

            # 解析邮件日期
            email_date = email.utils.parsedate_to_datetime(email_message['date'])

            # 解码发件人信息
            from_header = email_message['from']
            decoded_from = self._decode_email_header(from_header)

            # 添加更详细的调试日志
            self.logger.debug("=" * 50)
            self.logger.debug(f"处理邮件 ID: {num.decode()}")
            self.logger.debug(f"主题: {self._decode_email_header(email_message['subject'])}")
            self.logger.debug(f"发件人: {decoded_from}")
            self.logger.debug(f"日期: {email_date}")

            email_data = {
                'subject': self._decode_email_header(email_message['subject']),
                'from': decoded_from,
                'date': email_date,
                'message_id': num
            }

            # 获取邮件大小
            raw_email_size = len(msg[0][1])
            self.logger.debug(f"邮件大小: {raw_email_size / 1024:.2f} KB")

            # 检查邮件类型和附件
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type not in ['text/plain', 'text/html', 'multipart/alternative', 'multipart/mixed']:
                    filename = part.get_filename()
                    if filename:
                        self.logger.debug(f"附件: {filename} ({content_type})")

            email_list.append(email_data)

        return email_list

    def is_credit_card_statement(self, email_data: Dict) -> bool:
        """判断邮件是否为信用卡账单"""
        keywords = [
            "信用卡电子账单",
            "信用卡对账单",
            "信用卡月结单",
            "信用卡电子对账单"
        ]

        subject = email_data['subject'].lower()
        is_statement = any(keyword.lower() in subject for keyword in keywords)

        if is_statement:
            self.logger.info(f"找到信用卡账单邮件: {email_data['subject']}")

        return is_statement

    def parse_statement(self, email_data: Dict) -> Optional[Dict]:
        """解析信用卡账单邮件"""
        self.logger.info("=" * 50)
        self.logger.info(f"开始解析账单邮件: {email_data['subject']}")
        try:
            # 获取邮件内容
            _, msg = self.conn.fetch(email_data['message_id'], '(RFC822)')
            email_message = email.message_from_bytes(msg[0][1])

            # 添加详细的邮件内容日志
            self.logger.info("邮件详细信息:")
            self.logger.info(f"Message-ID: {email_message.get('Message-ID')}")
            self.logger.info(f"发件人: {self._decode_email_header(email_message.get('From'))}")
            self.logger.info(f"收件人: {self._decode_email_header(email_message.get('To'))}")
            self.logger.info(f"日期: {email_message.get('Date')}")
            self.logger.info(f"主题: {self._decode_email_header(email_message.get('Subject'))}")
            
            # 创建结果字典
            result = {
                'bank': '待定',
                'statement_date': None,
                'transactions': [],
                'content_length': 0
            }
            
            # 保存邮件内容
            self._save_email_content(email_data, email_message, result)
            
            # 获取邮件保存路径
            date_str = email_data['date'].strftime('%Y%m%d')
            safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
            email_folder = Path("emails") / f"{date_str}_{safe_subject}"
            
            self.logger.info(f"开始解析账单文件: {email_folder}")
            
            # 解析账单内容
            from statement_parsers.qq_email_parser import parse_statement_email
            transactions = parse_statement_email(email_folder)
            
            if transactions:
                result['transactions'] = [txn.to_dict() for txn in transactions]
                self.logger.info(f"成功解析 {len(transactions)} 条交易记录")
                
                # 打印每条交易记录的详细信息
                for i, txn in enumerate(transactions, 1):
                    self.logger.info(f"交易 {i}:")
                    self.logger.info(f"  - 日期: {txn.date}")
                    self.logger.info(f"  - 描述: {txn.description}")
                    self.logger.info(f"  - 金额: {txn.amount}")
            else:
                self.logger.warning("未解析到任何交易记录")
            
            self.logger.info("账单解析完成")
            self.logger.info("=" * 50)
            return result
                
        except Exception as e:
            self.logger.error(f"解析账单失败: {str(e)}", exc_info=True)
            self.logger.info("=" * 50)
            return None

    def _decode_email_header(self, header: str) -> str:
        """解码邮件标题，处理各种编码方式"""
        if not header:
            return ""

        try:
            # 直接使用 email.header.decode_header
            decoded_parts = decode_header(header)
            result = ""

            for part, charset in decoded_parts:
                # 处理字节类型
                if isinstance(part, bytes):
                    try:
                        # 如果指定了字符集就用指定的，否则尝试 utf-8
                        result += part.decode(charset or 'utf-8', errors='replace')
                    except (UnicodeDecodeError, LookupError):
                        # 如果解码失败，尝试其他常见编码
                        for encoding in ['utf-8', 'gb18030', 'big5', 'iso-8859-1']:
                            try:
                                result += part.decode(encoding)
                                break
                            except UnicodeDecodeError:
                                continue
                else:
                    result += str(part)

            return result.strip()

        except Exception as e:
            self.logger.error(f"邮件头解码失: {str(e)}, 原文: {header}")
            return header

    def close(self):
        """关闭连接"""
        if self.conn:
            self.logger.info("关闭邮箱连接")
            self.conn.close()
            self.conn.logout()

    def _create_storage_structure(self) -> Path:
        """创建邮件存储的文件夹结构"""
        # 直接创建 emails 文件夹
        email_dir = Path("emails")
        email_dir.mkdir(exist_ok=True)
        return email_dir

    def _save_email_content(self, email_data: Dict, email_message: Message, parsed_result: Optional[Dict] = None) -> None:
        """保存邮件内容到文件
        
        Args:
            email_data: 邮件基本信息
            email_message: 原始邮件对象
            parsed_result: 解析后的结果（如果有）
        """
        email_dir = self._create_storage_structure()
        
        # 使用日期和主题创建文件夹名
        date_str = email_data['date'].strftime('%Y%m%d')
        safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
        safe_subject = safe_subject.strip()
        
        # 创建邮件专属文件夹
        email_folder = email_dir / f"{date_str}_{safe_subject}"
        email_folder.mkdir(exist_ok=True)
        
        # 保存邮件元数据
        metadata = {
            'subject': email_data['subject'],
            'from': email_data['from'],
            'date': email_data['date'].isoformat(),
            'message_id': email_data['message_id'].decode() if isinstance(email_data['message_id'], bytes) else email_data['message_id']
        }
        
        with open(email_folder / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # 保存邮件内容，根据内容类型使用不同的扩展名
        for part in email_message.walk():
            if part.get_content_maintype() == 'text':
                content_type = part.get_content_type()
                charset = part.get_content_charset() or 'utf-8'
                
                try:
                    content = part.get_payload(decode=True)
                    if content:
                        # 根据内容类型决定文件扩展名
                        if content_type == 'text/html':
                            file_ext = '.html'
                            # 尝试使用不同的编码解码内容
                            decoded_content = None
                            for enc in [charset, 'utf-8', 'gb18030', 'big5', 'iso-8859-1']:
                                try:
                                    decoded_content = content.decode(enc)
                                    break
                                except (UnicodeDecodeError, LookupError):
                                    continue
                            
                            if decoded_content is None:
                                raise UnicodeDecodeError("无法解码HTML内容")

                            if '<!DOCTYPE' not in decoded_content and '<html' not in decoded_content:
                                # 如果内容中没有DOCTYPE和html标签，添加基本的HTML结构
                                decoded_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{email_data['subject']}</title>
</head>
<body>
{decoded_content}
</body>
</html>'''
                            elif '<meta charset=' not in decoded_content.lower():
                                # 如果已经有HTML结构但没有charset声明，在head标签后添加
                                decoded_content = decoded_content.replace('<head>', '<head>\n    <meta charset="utf-8">')
                            
                            with open(email_folder / f'content{file_ext}', 'w', encoding='utf-8') as f:
                                f.write(decoded_content)
                        elif content_type == 'text/plain':
                            file_ext = '.txt'
                            # 尝试使用不同的编码解码文本内容
                            for enc in [charset, 'utf-8', 'gb18030', 'big5', 'iso-8859-1']:
                                try:
                                    decoded_content = content.decode(enc)
                                    with open(email_folder / f'content{file_ext}', 'w', encoding='utf-8') as f:
                                        f.write(decoded_content)
                                    break
                                except (UnicodeDecodeError, LookupError):
                                    continue
                except Exception as e:
                    self.logger.warning(f"保存 {content_type} 内容时出错: {str(e)}")
            
            # 保存附件
            elif part.get_content_maintype() != 'multipart':
                filename = part.get_filename()
                if filename:
                    # 清理文件名
                    safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.'))
                    if safe_filename:
                        # 创建 attachments 文件夹
                        attachments_dir = email_folder / 'attachments'
                        attachments_dir.mkdir(exist_ok=True)
                        
                        # 保存附件
                        with open(attachments_dir / safe_filename, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                        self.logger.info(f"已保存附件: {safe_filename}")
        
        # 如果有解析结果，保存解析结果
        if parsed_result:
            with open(email_folder / 'parsed_result.json', 'w', encoding='utf-8') as f:
                json.dump(parsed_result, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"邮件内容已保存到: {email_folder}")

    def process_emails(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        处理指定日期范围内的信用卡账单邮件
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            解析出的所有交易记录列表
        """
        self.logger.info(f"搜索日期范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
        
        # 获取邮件列表
        email_list = self.get_email_list(
            start_date=start_date,
            end_date=end_date
        )
        
        self.logger.info(f"共获取到 {len(email_list)} 封邮件")
        
        # 处理每封邮件
        all_transactions = []
        for email_data in email_list:
            if self.is_credit_card_statement(email_data):
                statement_data = self.parse_statement(email_data)
                if statement_data and statement_data.get('transactions'):
                    all_transactions.extend(statement_data['transactions'])
                    self.logger.info(f"成功解析账单，包含 {len(statement_data['transactions'])} 条交易记录")
                    
        return all_transactions


def main():
    logger = setup_logger(__name__)

    # 从环境变量获取邮箱和授权码
    email_address = os.getenv('QQ_EMAIL')
    password = os.getenv('QQ_EMAIL_AUTH_CODE')

    if not email_address or not password:
        logger.error("环境变量未设置")
        raise ValueError(
            "请设置环境变量：\n"
            "QQ_EMAIL: QQ邮箱地址\n"
            "QQ_EMAIL_AUTH_CODE: QQ邮箱授权码"
        )

    parser = QQEmailParser(email_address, password)

    if parser.login():
        try:
            # 获取上个月的日期范围
            today = datetime.now()
            first_day = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            last_day = today.replace(day=1) - timedelta(days=1)

            # 处理邮件并获取交易记录
            all_transactions = parser.process_emails(first_day, last_day)
            logger.info(f"共解析 {len(all_transactions)} 条交易记录")

        finally:
            parser.close()


if __name__ == '__main__':
    main()
