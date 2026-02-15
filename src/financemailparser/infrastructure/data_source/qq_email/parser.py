import email
import imaplib
import logging
import re
import zipfile
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Iterable
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

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

    def _sanitize_url_for_log(self, url: str) -> str:
        """Remove query/fragment to avoid leaking tokens in logs."""
        try:
            parts = urlsplit(str(url or ""))
            scheme = parts.scheme or "https"
            netloc = parts.netloc
            path = parts.path or ""
            if netloc:
                return f"{scheme}://{netloc}{path}"
            return f"{scheme}:{path}"
        except Exception:
            return "<invalid-url>"

    def extract_wechat_download_links(self, email_data: Dict) -> List[str]:
        """
        从微信支付账单邮件中提取可能的下载链接（按优先级排序）。

        说明：
        - 不写死域名；尽量从邮件 HTML 中抽取候选链接；
        - 为避免漏掉“图片按钮”，会综合 a.get_text()、img[alt]、a[title]/a[aria-label]；
        - 这里只做候选排序，不做“最终可下载”判定；最终判定由下载阶段的 ZIP 魔数校验完成。
        """
        try:
            email_message = email_data["raw_message"]

            # 获取HTML内容
            html_content = None
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, (bytes, bytearray)):
                        html_content = payload.decode(charset, errors="replace")
                    else:
                        html_content = str(payload or "")
                    break

            if not html_content:
                self.logger.warning("未找到HTML内容")
                return []

            soup = BeautifulSoup(html_content, "lxml")
            anchors = soup.find_all("a", href=True)
            if not anchors:
                self.logger.warning("未找到任何链接")
                return []

            keywords = ("下载", "download")
            candidates: list[tuple[int, int, str]] = []
            seen: set[str] = set()

            for idx, a in enumerate(anchors):
                raw_href = str(a.get("href") or "").strip()
                if not raw_href:
                    continue

                if raw_href.startswith("//"):
                    raw_href = "https:" + raw_href

                # Ignore non-web links.
                lower_href = raw_href.lower()
                if lower_href.startswith(("mailto:", "javascript:", "#")):
                    continue

                if raw_href in seen:
                    continue
                seen.add(raw_href)

                label_parts: list[str] = []
                text = a.get_text(" ", strip=True)
                if text:
                    label_parts.append(text)
                title = str(a.get("title") or "").strip()
                if title:
                    label_parts.append(title)
                aria = str(a.get("aria-label") or "").strip()
                if aria:
                    label_parts.append(aria)

                for img in a.find_all("img"):
                    alt = str(img.get("alt") or "").strip()
                    if alt:
                        label_parts.append(alt)

                label = " ".join(dict.fromkeys(p for p in label_parts if p))
                label_lower = label.lower()
                score = 1 if any(k in label_lower for k in keywords) else 0
                candidates.append((score, idx, raw_href))

            if not candidates:
                self.logger.warning("未找到微信账单下载链接")
                return []

            candidates.sort(key=lambda x: (-x[0], x[1]))
            sorted_links = [href for _score, _idx, href in candidates]

            if sorted_links:
                self.logger.info(
                    "成功提取到微信账单下载链接候选（%s个）", len(sorted_links)
                )
                self.logger.debug(
                    "微信账单候选链接（已脱敏）: %s",
                    [self._sanitize_url_for_log(u) for u in sorted_links[:10]],
                )
            else:
                self.logger.warning("未找到微信账单下载链接")

            return sorted_links

        except Exception as e:
            self.logger.error(f"提取微信下载链接时出错: {str(e)}")
            return []

    def download_wechat_bill_candidates(
        self, download_links: Iterable[str], save_dir: Path
    ) -> Optional[str]:
        """
        逐个尝试下载候选链接，只有当响应内容通过 ZIP 魔数校验时才落盘。

        约束：只允许 https。
        """
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("开始下载微信账单文件...")

            for raw_link in download_links:
                download_link = str(raw_link or "").strip()
                if not download_link:
                    continue

                parts = urlsplit(download_link)
                if parts.scheme.lower() != "https":
                    self.logger.warning(
                        "跳过非 https 下载链接: %s",
                        self._sanitize_url_for_log(download_link),
                    )
                    continue

                response = None
                try:
                    self.logger.info(
                        "尝试下载候选链接: %s",
                        self._sanitize_url_for_log(download_link),
                    )
                    response = requests.get(
                        download_link,
                        timeout=self.download_timeout,
                        stream=True,
                    )

                    final_url = str(getattr(response, "url", "") or download_link)
                    final_scheme = urlsplit(final_url).scheme.lower()
                    if final_scheme != "https":
                        self.logger.warning(
                            "跳过重定向到非 https 的链接: %s",
                            self._sanitize_url_for_log(final_url),
                        )
                        continue

                    if response.status_code != 200:
                        self.logger.warning(
                            "下载失败，状态码: %s（%s）",
                            response.status_code,
                            self._sanitize_url_for_log(final_url),
                        )
                        continue

                    content_disposition = response.headers.get(
                        "content-disposition", ""
                    )
                    content_type = response.headers.get("content-type", "")
                    self.logger.debug("Content-Disposition: %s", content_disposition)
                    self.logger.debug("Content-Type: %s", content_type)

                    iterator = response.iter_content(chunk_size=8192)
                    buffered: list[bytes] = []
                    prefix = b""
                    while len(prefix) < 4:
                        chunk = next(iterator, b"")
                        if not chunk:
                            break
                        buffered.append(chunk)
                        prefix += chunk

                    if not prefix.startswith(b"PK\x03\x04"):
                        self.logger.warning(
                            "候选链接返回内容非 ZIP（已跳过）: %s",
                            self._sanitize_url_for_log(final_url),
                        )
                        continue

                    try:
                        if "filename*=utf-8" in content_disposition.lower():
                            encoded_name = content_disposition.split(
                                "filename*=utf-8''"
                            )[-1]
                            from urllib.parse import unquote

                            filename = unquote(encoded_name.strip('"'))
                        elif "filename=" in content_disposition.lower():
                            filename = re.findall(
                                'filename="?([^"]+)"?',
                                content_disposition,
                                flags=re.IGNORECASE,
                            )[0]
                        else:
                            filename = f"微信账单_{datetime.now().strftime(DATETIME_FMT_COMPACT)}.zip"

                        filename = "".join(
                            c
                            for c in filename
                            if c.isalnum() or c in (" ", "-", "_", ".", "(", ")")
                        )
                        if not filename.lower().endswith(".zip"):
                            filename = f"{filename}.zip"

                    except Exception as e:
                        self.logger.warning(
                            "解析文件名失败: %s，使用默认文件名", str(e)
                        )
                        filename = f"微信账单_{datetime.now().strftime(DATETIME_FMT_COMPACT)}.zip"

                    filepath = save_dir / filename

                    with open(filepath, "wb") as f:
                        for b in buffered:
                            f.write(b)
                        for chunk in iterator:
                            if chunk:
                                f.write(chunk)

                    self.logger.info("成功下载微信账单文件: %s", filepath)
                    return str(filepath)

                except Exception as e:
                    self.logger.warning(
                        "下载候选链接失败: %s（%s）",
                        str(e),
                        self._sanitize_url_for_log(download_link),
                    )
                    continue
                finally:
                    try:
                        if response is not None:
                            response.close()
                    except Exception:
                        pass

            self.logger.error("所有候选下载链接均失败（未获得有效 ZIP）")
            return None

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
