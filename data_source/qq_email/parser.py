import email
import imaplib
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional

from .email_processor import save_email_content
from .exceptions import LoginError, ParseError
from .utils import decode_email_header, create_storage_structure


class QQEmailParser:
    def __init__(self, email_address: str, password: str):
        if not email_address:
            raise ValueError("QQ邮箱地址不能为空")
        if not password:
            raise ValueError("QQ邮箱授权码不能为空")

        self.email_address = email_address
        self.password = password
        self.imap_server = "imap.qq.com"
        self.conn = None
        self.logger = logging.getLogger(__name__)

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
            raise LoginError(f"登录失败: {str(e)}")

    def _create_email_data(self, message_id, email_message=None) -> Dict:
        """创建标准化的邮件数据结构"""
        try:
            if email_message is None:
                _, msg_data = self.conn.fetch(message_id, '(RFC822)')
                email_message = email.message_from_bytes(msg_data[0][1])

            date_str = email_message['Date']
            email_date = parsedate_to_datetime(date_str)

            return {
                'message_id': message_id,
                'subject': decode_email_header(email_message['Subject'] or ''),
                'from': decode_email_header(email_message['From'] or ''),
                'to': decode_email_header(email_message['To'] or ''),
                'date': email_date,
                'raw_message': email_message,
                'content_type': email_message.get_content_type(),
                'size': len(str(email_message)),
            }
        except Exception as e:
            raise ParseError(f"创建邮件数据结构时出错: {str(e)}")

    def get_email_list(self, start_date=None, end_date=None) -> List[Dict]:
        """获取指定日期范围内的邮件列表"""
        email_list = []

        try:
            status, count = self.conn.select('INBOX')
            self.logger.debug(f"INBOX 状态: {status}, 邮件数量: {count[0].decode()}")

            _, messages = self.conn.search('UTF-8', 'ALL')

            message_numbers = messages[0].split()
            message_numbers.reverse()
            total_messages = len(message_numbers)
            self.logger.debug(f"找到邮件总数: {total_messages}")

            if not message_numbers:
                self.logger.debug("没有找到邮件")
                return email_list

            for num in message_numbers:
                try:
                    email_data = self._create_email_data(num)
                    email_date = email_data['date'].date()

                    self.logger.debug(
                        f"\n处理邮件:"
                        f"\n  - 日期: {email_date}"
                        f"\n  - 主题: {email_data['subject']}"
                        f"\n  - 发件人: {email_data['from']}"
                        f"\n  - 大小: {email_data['size']/1024:.1f}KB"
                    )

                    if start_date and end_date:
                        start_date_date = start_date.date() if isinstance(start_date, datetime) else start_date
                        end_date_date = end_date.date() if isinstance(end_date, datetime) else end_date

                        if email_date < start_date_date:
                            self.logger.debug(f"  ⨯ 邮件日期早于开始日期 {start_date_date}，停止处理")
                            break

                        if email_date <= end_date_date:
                            self.logger.debug(f"  ✓ 邮件在目标日期范围内，已添加")
                            email_list.append(email_data)
                        else:
                            self.logger.debug(f"  ⨯ 邮件日期晚于结束日期 {end_date_date}，跳过")
                    else:
                        self.logger.debug("  ✓ 无日期过滤，已添加")
                        email_list.append(email_data)

                except Exception as e:
                    self.logger.error(f"处理邮件时出错: {str(e)}")
                    continue

            self.logger.info(f"总共获取到 {len(email_list)} 封符合条件的邮件")
            return email_list

        except Exception as e:
            self.logger.error(f"获取邮件列表时出错: {str(e)}")
            return email_list

    def is_credit_card_statement(self, email_data: Dict) -> bool:
        """判断邮件是否为信用卡账单"""
        keywords = [
            "信用卡电子账单",
            "信用卡对账单",
            "信用卡月结单",
            "信用卡电子对账单"
        ]

        subject = email_data.get('subject', '').lower()
        is_statement = any(keyword.lower() in subject for keyword in keywords)

        if is_statement:
            self.logger.info(f"找到信用卡账单邮件: {subject}")

        return is_statement

    def parse_statement(self, email_data: Dict) -> Optional[Dict]:
        """解析信用卡账单邮件"""
        self.logger.info("=" * 50)
        self.logger.info(f"开始解析账单邮件: {email_data['subject']}")
        try:
            result = {
                'bank': '待定',
                'statement_date': None,
                'transactions': [],
                'content_length': email_data.get('size', 0)
            }

            # 获取邮件保存路径
            date_str = email_data['date'].strftime('%Y%m%d')
            safe_subject = "".join(c for c in email_data['subject'] if c.isalnum() or c in (' ', '-', '_'))[:50]
            email_folder = create_storage_structure() / f"{date_str}_{safe_subject}"

            # 保存邮件内容
            save_email_content(email_folder, email_data, email_data['raw_message'], result)

            self.logger.info(f"开始解析账单文件: {email_folder}")

            # 解析账单内容
            from statement_parsers.qq_email import parse_statement_email
            transactions = parse_statement_email(email_folder)

            if transactions:
                result['transactions'] = [txn.to_dict() for txn in transactions]
                self.logger.info(f"成功解析 {len(transactions)} 条交易记录")

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

    def process_emails(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """处理指定日期范围内的信用卡账单邮件"""
        self.logger.info(f"搜索日期范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")

        email_list = self.get_email_list(
            start_date=start_date,
            end_date=end_date
        )

        self.logger.info(f"共获取到 {len(email_list)} 封邮件")

        all_transactions = []
        for email_data in email_list:
            if self.is_credit_card_statement(email_data):
                statement_data = self.parse_statement(email_data)
                if statement_data and statement_data.get('transactions'):
                    all_transactions.extend(statement_data['transactions'])
                    self.logger.info(f"成功解析账单，包含 {len(statement_data['transactions'])} 条交易记录")

        return all_transactions

    def close(self):
        """关闭连接"""
        if self.conn:
            self.logger.info("关闭邮箱连接")
            try:
                self.conn.close()
                self.conn.logout()
            except Exception as e:
                self.logger.error(f"关闭连接时出错: {str(e)}")