import email
import imaplib
import logging
import traceback
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional
from pathlib import Path
import re
import requests
import zipfile

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
        self.BILL_KEYWORDS = {
            'credit_card': [
                "信用卡电子账单",
                "信用卡对账单",
                "信用卡月结单",
                "信用卡电子对账单"
            ],
            'alipay': [
                "支付宝账单",
                "支付宝月度对账单",
                "支付宝交易流水",
                "交易流水明细"
            ],
            'wechat': [
                "微信支付账单",
                "微信支付对账单",
                "微信支付-账单",
                "账单流水文件"
            ]
        }

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
            self.logger.debug(f"INBOX 状态: {status}, 邮件数量: {count[0].decode('utf-8')}")

            _, messages = self.conn.search(None, 'ALL')

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

            self.logger.info(f"总共获取到 {len(email_list)} 封符合条件的��件")
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
            "信用卡电子对账单",
            "中国工商银行客户对账单"
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
            from statement_parsers.parse import parse_statement_email
            transactions = parse_statement_email(email_folder)

            if transactions:
                result['transactions'] = [txn.to_dict() for txn in transactions]
                self.logger.info(f"成功解析 {len(transactions)} 条交易记录")

                for i, txn in enumerate(transactions, 1):
                    self.logger.info(f"交易 {i}:")
                    self.logger.info(f"  - 日期: {txn.date}")
                    self.logger.info(f"  - 描���: {txn.description}")
                    self.logger.info(f"  - 金额: {txn.amount}")
            else:
                self.logger.warning("未解析到任何交易记录")

            self.logger.info("账单解析完成")
            self.logger.info("=" * 50)
            return result

        except Exception as e:
            self.logger.error(f"解析账��失败: {str(e)}", exc_info=True)
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

    def get_latest_bill_emails(self, bill_type: str) -> List[Dict]:
        """
        获取最新的账单邮件（支付宝或微信）
        
        Args:
            bill_type: 账单类型，'alipay' 或 'wechat'
        
        Returns:
            包含最新账单邮件数据的列表
        """
        try:
            status, count = self.conn.select('INBOX')
            total_count = count[0].decode('utf-8')
            self.logger.info(f"开始搜索{bill_type}账单邮件，邮箱共有 {total_count} 封邮件")
            
            keywords = self.BILL_KEYWORDS.get(bill_type, [])
            if not keywords:
                self.logger.error(f"未知的账单类型: {bill_type}")
                return []
            
            self.logger.info(f"搜索关键词: {keywords}")
            
            # 获取所有邮件
            _, messages = self.conn.search(None, 'ALL')
            message_numbers = messages[0].split()
            message_numbers.reverse()  # 最新的邮件在前
            
            self.logger.info(f"开始从最新邮件开始检查...")
            
            for i, num in enumerate(message_numbers):
                try:
                    email_data = self._create_email_data(num)
                    subject = email_data.get('subject', '')
                    
                    self.logger.debug(f"检查第 {i+1} 封邮件: {subject}")
                    
                    # 打印每个关键词的匹配结果，帮助调试
                    for keyword in keywords:
                        self.logger.debug(f"  - 关键词 '{keyword}' 是否匹配: {keyword in subject}")
                    
                    # 检查邮件主题是否包含关键词
                    if any(keyword in subject for keyword in keywords):
                        self.logger.info(f"找到{bill_type}账单邮件:")
                        self.logger.info(f"  - 主题: {subject}")
                        self.logger.info(f"  - 发件人: {email_data.get('from', '')}")
                        self.logger.info(f"  - 日期: {email_data.get('date', '')}")
                        return [email_data]
                    
                except Exception as e:
                    self.logger.error(f"处理第 {i+1} 封邮件时出错: {str(e)}")
                    continue
            
            self.logger.info(f"检查完成，未找到{bill_type}账单邮件")
            return []
            
        except Exception as e:
            self.logger.error(f"获取最新账单邮件时出错: {str(e)}")
            return []

    def save_bill_attachments(self, email_data: Dict, save_dir: Path) -> List[str]:
        """
        保存账单附件
        
        Args:
            email_data: 邮件数据
            save_dir: 保存目录
        
        Returns:
            保存的文件路径列表
        """
        save_dir.mkdir(parents=True, exist_ok=True)
        saved_files = []
        
        try:
            email_message = email_data['raw_message']
            self.logger.info(f"开始处理邮件附件...")
            
            for part in email_message.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                    
                filename = part.get_filename()
                if not filename:
                    continue
                    
                filename = decode_email_header(filename)
                self.logger.info(f"发现附件: {filename}")
                
                # 移除文件扩展名限制，保存所有附件
                filepath = save_dir / filename
                with open(filepath, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                saved_files.append(str(filepath))
                self.logger.info(f"成功保存附件: {filepath}")
                
            if not saved_files:
                self.logger.warning("未找到任何附件")
            
            return saved_files
            
        except Exception as e:
            self.logger.error(f"保存附件时出错: {str(e)}")
            return saved_files

    def extract_wechat_download_link(self, email_data: Dict) -> Optional[str]:
        """
        从微信支付账单邮件中提取下载链接
        
        Args:
            email_data: 邮件数据
        
        Returns:
            下载链接或None
        """
        try:
            email_message = email_data['raw_message']
            
            # 获取HTML内容
            html_content = None
            for part in email_message.walk():
                if part.get_content_type() == 'text/html':
                    html_content = part.get_payload(decode=True).decode()
                    break
            
            if not html_content:
                self.logger.warning("未找到HTML内容")
                return None
            
            # 查找下载链接
            # 在href属性中查找包含download_bill.cgi的链接
            download_links = re.findall(r'href="(https://download\.bill\.weixin\.qq\.com/[^"]+)"', html_content)
            
            if download_links:
                link = download_links[0]
                self.logger.info(f"成功提取到微信账单下载链接")
                return link
            
            self.logger.warning("未找到微信账单下载链接")
            return None
            
        except Exception as e:
            self.logger.error(f"提取微信下载链接时出错: {str(e)}")
            return None

    def is_bill_email(self, email_data: Dict, bill_type: str) -> bool:
        """
        判断邮件是否为指定类型的账单邮件
        
        Args:
            email_data: 邮件数据
            bill_type: 账单类型 ('alipay' 或 'wechat')
        
        Returns:
            是否为指定类型的账单邮件
        """
        keywords = self.BILL_KEYWORDS.get(bill_type, [])
        subject = email_data.get('subject', '').lower()
        return any(keyword.lower() in subject for keyword in keywords)

    def download_wechat_bill(self, download_link: str, save_dir: Path) -> Optional[str]:
        """
        下载微信账单文件
        
        Args:
            download_link: 下载链接
            save_dir: 保存目录
        
        Returns:
            保存的文件路径或None
        """
        try:
            self.logger.info("开始下载微信账单文件...")
            response = requests.get(download_link, timeout=30)
            
            if response.status_code != 200:
                self.logger.error(f"下载失败，状态码: {response.status_code}")
                return None
            
            # 从响应头中获取文件名并处理
            content_disposition = response.headers.get('content-disposition', '')
            self.logger.debug(f"Content-Disposition: {content_disposition}")
            
            try:
                # 尝试从Content-Disposition中提取文件名
                if 'filename*=utf-8' in content_disposition:
                    # 处理UTF-8编码的文件名
                    encoded_name = content_disposition.split("filename*=utf-8''")[-1]
                    from urllib.parse import unquote
                    filename = unquote(encoded_name.strip('"'))
                elif 'filename=' in content_disposition:
                    # 处理普通文件名
                    filename = re.findall('filename="?([^"]+)"?', content_disposition)[0]
                else:
                    # 如果无法获取文件名，使用默认名称
                    filename = f"微信账单_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                    
                # 清理文件名中的非法字符
                filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.', '(', ')'))
                
                self.logger.debug(f"解析得到文件名: {filename}")
                
            except Exception as e:
                self.logger.warning(f"解析文件名失败: {str(e)}，使用默认文件名")
                filename = f"微信账单_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            filepath = save_dir / filename
            
            # 保存文件
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            self.logger.info(f"成功下载微信账单文件: {filepath}")
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"下载微信账单文件时出错: {str(e)}")
            return None

    def extract_zip_file(self, zip_path: str, extract_dir: Path, password: Optional[str] = None) -> bool:
        """
        解压ZIP文件
        
        Args:
            zip_path: ZIP文件路径
            extract_dir: 解压目标目录
            password: 解压密码
        
        Returns:
            是否解压成功
        """
        try:
            self.logger.info(f"开始解压文件: {zip_path}")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                if password:
                    # 如果提供了密码，转换为bytes
                    pwd_bytes = password.encode('utf-8')
                    zip_ref.extractall(extract_dir, pwd=pwd_bytes)
                else:
                    zip_ref.extractall(extract_dir)
                    
            self.logger.info(f"成功解压到: {extract_dir}")
            return True
            
        except Exception as e:
            self.logger.error(f"解压文件失败: {str(e)}")
            return False