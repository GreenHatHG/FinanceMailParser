import email
import imaplib
import logging
import re
import zipfile
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

import requests

from financemailparser.shared.constants import (
    DATETIME_FMT_COMPACT,
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    DEFAULT_IMAP_SERVER,
)
from .exceptions import LoginError, ParseError
from .utils import decode_email_header


class QQEmailParser:
    def __init__(self, email_address: str, password: str):
        if not email_address:
            raise ValueError("QQ邮箱地址不能为空")
        if not password:
            raise ValueError("QQ邮箱授权码不能为空")

        self.email_address = email_address
        self.password = password

        self.imap_server = DEFAULT_IMAP_SERVER
        self.download_timeout = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS

        self.conn: Optional[imaplib.IMAP4_SSL] = None
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
                if not self.conn:
                    raise LoginError("未连接到邮箱服务器")
                _, msg_data = self.conn.fetch(message_id, "(RFC822)")
                if msg_data and isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1:
                    raw_bytes = msg_data[0][1]
                    if isinstance(raw_bytes, bytes):
                        email_message = email.message_from_bytes(raw_bytes)
                    else:
                        raise ParseError("无法获取邮件内容")
                else:
                    raise ParseError("邮件数据格式错误")

            date_str = email_message["Date"]
            email_date = parsedate_to_datetime(date_str)

            return {
                "message_id": message_id,
                "subject": decode_email_header(email_message["Subject"] or ""),
                "from": decode_email_header(email_message["From"] or ""),
                "to": decode_email_header(email_message["To"] or ""),
                "date": email_date,
                "raw_message": email_message,
                "content_type": email_message.get_content_type(),
                "size": len(str(email_message)),
            }
        except Exception as e:
            raise ParseError(f"创建邮件数据结构时出错: {str(e)}")

    def get_email_list(self, start_date=None, end_date=None) -> List[Dict]:
        """获取指定日期范围内的邮件列表"""
        email_list: List[Dict[str, Any]] = []

        if not self.conn:
            raise LoginError("未连接到邮箱服务器")

        try:
            status, count = self.conn.select("INBOX")
            if count and isinstance(count[0], bytes):
                self.logger.debug(
                    f"INBOX 状态: {status}, 邮件数量: {count[0].decode('utf-8')}"
                )

            _, messages = self.conn.search(None, "ALL")

            if messages and isinstance(messages[0], bytes):
                message_numbers = messages[0].split()
            else:
                message_numbers = []
            message_numbers.reverse()
            total_messages = len(message_numbers)
            self.logger.debug(f"找到邮件总数: {total_messages}")

            if not message_numbers:
                self.logger.debug("没有找到邮件")
                return email_list

            for num in message_numbers:
                try:
                    email_data = self._create_email_data(num)
                    email_date = email_data["date"].date()

                    self.logger.debug(
                        f"\n处理邮件:"
                        f"\n  - 日期: {email_date}"
                        f"\n  - 主题: {email_data['subject']}"
                        f"\n  - 发件人: {email_data['from']}"
                        f"\n  - 大小: {email_data['size'] / 1024:.1f}KB"
                    )

                    if start_date and end_date:
                        start_date_date = (
                            start_date.date()
                            if isinstance(start_date, datetime)
                            else start_date
                        )
                        end_date_date = (
                            end_date.date()
                            if isinstance(end_date, datetime)
                            else end_date
                        )

                        if email_date < start_date_date:
                            self.logger.debug(
                                f"  ⨯ 邮件日期早于开始日期 {start_date_date}，停止处理"
                            )
                            break

                        if email_date <= end_date_date:
                            self.logger.debug("  ✓ 邮件在目标日期范围内，已添加")
                            email_list.append(email_data)
                        else:
                            self.logger.debug(
                                f"  ⨯ 邮件日期晚于结束日期 {end_date_date}，跳过"
                            )
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

    def close(self):
        """关闭连接"""
        if self.conn:
            self.logger.info("关闭邮箱连接")
            try:
                # 只调用 logout，不调用 close
                # close() 只能在 SELECTED 状态下调用
                self.conn.logout()
            except Exception as e:
                self.logger.error(f"关闭连接时出错: {str(e)}")

    def get_latest_emails_by_subject_keywords(
        self,
        keywords: List[str],
        *,
        case_insensitive: bool = True,
        limit: int = 1,
    ) -> List[Dict]:
        """
        按主题关键词查找“最新的”邮件（从最新到最旧遍历）。

        Args:
            keywords: 关键词列表（命中任意一个即视为匹配）
            case_insensitive: 是否忽略大小写（默认 True）
            limit: 返回匹配邮件的数量上限（默认 1）

        Returns:
            匹配到的邮件列表（按最新→最旧顺序），可能为空列表。
        """
        if not self.conn:
            raise LoginError("未连接到邮箱服务器")

        try:
            status, count = self.conn.select("INBOX")
            if count and isinstance(count[0], bytes):
                total_count = count[0].decode("utf-8")
                self.logger.info(
                    "开始按关键词搜索邮件，邮箱共有 %s 封邮件", total_count
                )

            normalized_keywords = [
                str(k).strip() for k in (keywords or []) if str(k).strip()
            ]
            if not normalized_keywords:
                return []

            self.logger.info("搜索关键词: %s", normalized_keywords)

            # 获取所有邮件
            _, messages = self.conn.search(None, "ALL")
            if messages and isinstance(messages[0], bytes):
                message_numbers = messages[0].split()
                message_numbers.reverse()  # 最新的邮件在前
            else:
                self.logger.warning("未找到任何邮件")
                return []

            self.logger.info("开始从最新邮件开始检查...")

            matches: List[Dict] = []

            for i, num in enumerate(message_numbers):
                try:
                    email_data = self._create_email_data(num)
                    subject = email_data.get("subject", "")

                    self.logger.debug("检查第 %s 封邮件: %s", i + 1, subject)

                    subject_to_match = str(subject or "")
                    if case_insensitive:
                        subject_norm = subject_to_match.lower()
                        hit = any(
                            k.lower() in subject_norm for k in normalized_keywords
                        )
                    else:
                        hit = any(k in subject_to_match for k in normalized_keywords)

                    if hit:
                        matches.append(email_data)
                        self.logger.info("找到匹配邮件: %s", subject_to_match)
                        if len(matches) >= max(1, int(limit)):
                            return matches

                except Exception as e:
                    self.logger.error(f"处理第 {i + 1} 封邮件时出错: {str(e)}")
                    continue

            self.logger.info("检查完成，未找到匹配邮件")
            return matches

        except Exception as e:
            self.logger.error(f"按关键词查找最新邮件时出错: {str(e)}")
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
            email_message = email_data["raw_message"]
            self.logger.info("开始处理邮件附件...")

            for part in email_message.walk():
                if part.get_content_maintype() == "multipart":
                    continue

                filename = part.get_filename()
                if not filename:
                    continue

                filename = decode_email_header(filename)
                self.logger.info(f"发现附件: {filename}")

                # 移除文件扩展名限制，保存所有附件
                filepath = save_dir / filename
                with open(filepath, "wb") as f:
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
            email_message = email_data["raw_message"]

            # 获取HTML内容
            html_content = None
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    html_content = part.get_payload(decode=True).decode()
                    break

            if not html_content:
                self.logger.warning("未找到HTML内容")
                return None

            # 查找下载链接
            # 在href属性中查找包含download_bill.cgi的链接
            download_links = re.findall(
                r'href="(https://download\.bill\.weixin\.qq\.com/[^"]+)"', html_content
            )

            if download_links:
                link = download_links[0]
                self.logger.info("成功提取到微信账单下载链接")
                return link

            self.logger.warning("未找到微信账单下载链接")
            return None

        except Exception as e:
            self.logger.error(f"提取微信下载链接时出错: {str(e)}")
            return None

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
            response = requests.get(download_link, timeout=self.download_timeout)

            if response.status_code != 200:
                self.logger.error(f"下载失败，状态码: {response.status_code}")
                return None

            # 从响应头中获取文件名并处理
            content_disposition = response.headers.get("content-disposition", "")
            self.logger.debug(f"Content-Disposition: {content_disposition}")

            try:
                # 尝试从Content-Disposition中提取文件名
                if "filename*=utf-8" in content_disposition:
                    # 处理UTF-8编码的文件名
                    encoded_name = content_disposition.split("filename*=utf-8''")[-1]
                    from urllib.parse import unquote

                    filename = unquote(encoded_name.strip('"'))
                elif "filename=" in content_disposition:
                    # 处理普通文件名
                    filename = re.findall('filename="?([^"]+)"?', content_disposition)[
                        0
                    ]
                else:
                    # 如果无法获取文件名，使用默认名称
                    filename = (
                        f"微信账单_{datetime.now().strftime(DATETIME_FMT_COMPACT)}.zip"
                    )

                # 清理文件名中的非法字符
                filename = "".join(
                    c
                    for c in filename
                    if c.isalnum() or c in (" ", "-", "_", ".", "(", ")")
                )

                self.logger.debug(f"解析得到文件名: {filename}")

            except Exception as e:
                self.logger.warning(f"解析文件名失败: {str(e)}，使用默认文件名")
                filename = (
                    f"微信账单_{datetime.now().strftime(DATETIME_FMT_COMPACT)}.zip"
                )

            filepath = save_dir / filename

            # 保存文件
            with open(filepath, "wb") as f:
                f.write(response.content)

            self.logger.info(f"成功下载微信账单文件: {filepath}")
            return str(filepath)

        except Exception as e:
            self.logger.error(f"下载微信账单文件时出错: {str(e)}")
            return None

    def extract_zip_file(
        self, zip_path: str, extract_dir: Path, password: Optional[str] = None
    ) -> bool:
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

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                if password:
                    # 如果提供了密码，转换为bytes
                    pwd_bytes = password.encode("utf-8")
                    zip_ref.extractall(extract_dir, pwd=pwd_bytes)
                else:
                    zip_ref.extractall(extract_dir)

            self.logger.info(f"成功解压到: {extract_dir}")
            return True

        except Exception as e:
            self.logger.error(f"解压文件失败: {str(e)}")
            return False
