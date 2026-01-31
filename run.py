from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Callable, Any
import logging
from pathlib import Path

from constants import (
    DATETIME_FMT_ISO,
    DATE_FMT_COMPACT,
    DATE_FMT_ISO,
    EMAILS_DIR,
    PROJECT_ROOT,
    TRANSACTIONS_CSV,
)
from data_source.qq_email import QQEmailParser, QQEmailConfigManager
from data_source.qq_email.email_processor import save_email_content
from data_source.qq_email.utils import create_storage_structure
from statement_parsers.parse import parse_statement_email, find_csv_file
from utils.csv_writer import CSVWriter
from utils.logger import set_global_log_level
from utils.beancount_writer import BeancountExportOptions, transactions_to_beancount
from models.txn import Transaction, DigitalPaymentTransaction

logger = logging.getLogger(__name__)

# Constants for transaction categorization
TRANSPORT_KEYWORDS = [
    "12306铁路一卡通-银联无卡自助消费",
    "（特约）龙支付清算户",
    "上海哈啰普惠科技有限公司",
    "北京公交",
    "昌32路",
    "北京公共交通",
    "北京轨道交通",
    "地铁",
    "昌19",
]

MEAL_KEYWORDS = [
    "麦当劳",
    "公司餐厅消费",
    "拉扎斯",
    "美团平台商户",
    "深圳美团科技有限公司",
    "饿了么",
    "多点",
    "盒马",
    "星巴克",
    "海底捞",
    "蜜雪冰城",
    "索迪斯",
    "北京总部",
]


def _shift_months(year: int, month: int, months: int) -> Tuple[int, int]:
    total_months = year * 12 + (month - 1) - months
    shifted_year = total_months // 12
    shifted_month = total_months % 12 + 1
    return shifted_year, shifted_month


def _get_month_end(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1) - timedelta(days=1)
    return datetime(year, month + 1, 1) - timedelta(days=1)


def get_quick_select_options() -> List[str]:
    today = datetime.now()
    options = ["本月", "上月", "最近三个月", "最近半年"]

    # Add month options from 2 months ago to 6 months ago (inclusive).
    for offset in range(2, 7):
        year, month = _shift_months(today.year, today.month, offset)
        options.append(f"{year}年{month:02d}月")

    return options


def calculate_date_range_for_quick_select(option: str) -> Tuple[datetime, datetime]:
    """
    根据快捷选项计算日期范围

    Args:
        option: 快捷选项（'本月'、'上月'、'最近三个月'、'最近半年'、'YYYY年MM月'）

    Returns:
        (start_date, end_date) 元组

    Raises:
        ValueError: 未知的快捷选项
    """
    today = datetime.now()

    if option == "本月":
        # 本月账单：本月1号到今天
        start_date = datetime(today.year, today.month, 1)
        end_date = today
    elif option == "上月":
        # 上月账单：上月1号到上月最后一天
        if today.month == 1:
            start_date = datetime(today.year - 1, 12, 1)
            end_date = datetime(today.year - 1, 12, 31)
        else:
            start_date = datetime(today.year, today.month - 1, 1)
            # 计算上月最后一天
            end_date = datetime(today.year, today.month, 1) - timedelta(days=1)
    elif option == "最近三个月":
        # 最近三个月：三个月前的1号到今天
        three_months_ago = today - timedelta(days=90)
        start_date = datetime(three_months_ago.year, three_months_ago.month, 1)
        end_date = today
    elif option == "最近半年":
        # 最近半年：六个月前所在月的1号到今天
        half_year_ago_year, half_year_ago_month = _shift_months(
            today.year, today.month, 6
        )
        start_date = datetime(half_year_ago_year, half_year_ago_month, 1)
        end_date = today
    elif option.endswith("月") and "年" in option:
        # 月份快捷项：YYYY年MM月
        try:
            year_part, month_part = option[:-1].split("年", 1)
            year = int(year_part)
            month = int(month_part)
            if month < 1 or month > 12:
                raise ValueError
        except ValueError:
            raise ValueError(f"未知的快捷选项：{option}")
        start_date = datetime(year, month, 1)
        end_date = _get_month_end(year, month)
    else:
        raise ValueError(f"未知的快捷选项：{option}")

    return start_date, end_date


def print_transaction_stats(transactions: List[Transaction]) -> None:
    """
    打印交易记录的统计信息

    Args:
        transactions: 交易记录列表
    """
    if not transactions:
        logger.info("未找到任何交易记录")
        return

    total_amount = sum(txn.amount for txn in transactions)
    logger.info(f"处理完成，共解析 {len(transactions)} 条交易记录")
    logger.info(f"总金额: ¥{total_amount:.2f}")

    # 按银行分类统计
    bank_stats: Dict[Any, Dict[str, Any]] = {}
    bank_transactions: Dict[Any, List[Transaction]] = {}  # 新增：存储每个银行的交易记录
    for txn in transactions:
        bank = txn.source
        if bank not in bank_stats:
            bank_stats[bank] = {"count": 0, "amount": 0}
            bank_transactions[bank] = []  # 新增：初始化银行交易列表
        bank_stats[bank]["count"] += 1
        bank_stats[bank]["amount"] += txn.amount
        bank_transactions[bank].append(txn)  # 新增：添加交易到对应银行

    logger.info("\n按银行统计:")
    for bank, stats in bank_stats.items():
        logger.info(f"{bank}: {stats['count']}笔交易, 总金额 ¥{stats['amount']:.2f}")
        # 新印每个银行的详细交易记录
        logger.debug(f"\n{bank} 的交易明细:")
        for txn in bank_transactions[bank]:
            logger.debug(
                f"  - 日期: {txn.date}, 描述: {txn.description}, 金额: ¥{txn.amount:.2f}"
            )


def download_credit_card_emails(
    start_date: datetime,
    end_date: datetime,
    log_level: str = "INFO",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, int]:
    """
    从QQ邮箱下载信用卡账单

    Args:
        start_date: 开始日期
        end_date: 结束日期
        log_level: 日志级别
        progress_callback: 进度回调函数 (current_step, total_steps, message)

    Returns:
        下载统计信息 {'credit_card': count}
    """
    # 设置全局日志级别
    set_global_log_level(log_level)
    logger.info("开始下载信用卡账单...")
    logger.info(
        f"日期范围: {start_date.strftime(DATE_FMT_ISO)} 到 {end_date.strftime(DATE_FMT_ISO)}"
    )

    # 创建解析器实例
    qq_config_manager = QQEmailConfigManager()
    email, password = qq_config_manager.get_email_config()

    if not email or not password:
        logger.error("未配置邮箱信息，请先配置邮箱")
        raise ValueError("未配置邮箱信息")

    parser = QQEmailParser(email, password)

    # 步骤 1: 连接邮箱
    if progress_callback:
        progress_callback(0, 100, "正在连接邮箱...")

    if not parser.login():
        logger.error("登录失败")
        raise ConnectionError("登录失败")

    if progress_callback:
        progress_callback(10, 100, "连接成功")

    try:
        email_dir = create_storage_structure()

        # 步骤 2: 搜索邮件
        if progress_callback:
            progress_callback(15, 100, "正在搜索邮件...")

        email_list = parser.get_email_list(start_date, end_date)
        logger.info(f"找到 {len(email_list)} 封邮件")

        if progress_callback:
            progress_callback(20, 100, f"找到 {len(email_list)} 封邮件")

        # 初始化统计
        saved_count = 0

        # 步骤 3: 处理每封邮件
        total_emails = len(email_list)
        if total_emails == 0:
            if progress_callback:
                progress_callback(100, 100, "未找到信用卡账单")
            logger.info("未找到信用卡账单")
            return {"credit_card": 0}

        for idx, email_data in enumerate(email_list):
            # 计算进度：20% - 100% 用于处理邮件
            progress = 20 + int((idx + 1) / total_emails * 80)

            if progress_callback:
                progress_callback(
                    progress,
                    100,
                    f"正在处理邮件 {idx + 1}/{total_emails}: {email_data['subject'][:30]}...",
                )

            # 只处理信用卡账单
            if parser.is_credit_card_statement(email_data):
                date_str = email_data["date"].strftime(DATE_FMT_COMPACT)
                safe_subject = "".join(
                    c
                    for c in email_data["subject"]
                    if c.isalnum() or c in (" ", "-", "_")
                )[:50]
                email_folder = email_dir / f"{date_str}_{safe_subject}"
                save_email_content(email_folder, email_data, email_data["raw_message"])
                saved_count += 1
                logger.info(f"已保存信用卡账单: {email_data['subject']}")

        # 完成
        if progress_callback:
            progress_callback(100, 100, f"下载完成！共 {saved_count} 封信用卡账单")

        logger.info(f"下载完成，共保存 {saved_count} 封信用卡账单")
        return {"credit_card": saved_count}

    except Exception as e:
        logger.error(f"下载信用卡账单时出错: {str(e)}", exc_info=True)
        raise
    finally:
        parser.close()


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

    Args:
        log_level: 日志级别
        alipay_pwd: 支付宝 ZIP 解压密码
        wechat_pwd: 微信 ZIP 解压密码
        progress_callback: 进度回调函数 (current_step, total_steps, message)

    Returns:
        结果字典，包含：
        - alipay: 本次新下载的支付宝账单数量（0/1）
        - wechat: 本次新下载的微信账单数量（0/1）
        - alipay_status/wechat_status: 处理状态（downloaded / skipped_existing_csv / extracted_existing_zip / not_found / missing_password / failed）
        - alipay_csv/wechat_csv: 发现或生成的 CSV 路径（字符串或 None）
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
        """解压指定 ZIP 并返回解压后在 bill_dir 下找到的 CSV（递归）。"""
        extract_dir = bill_dir / zip_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)
        if not parser.extract_zip_file(str(zip_path), extract_dir, password):
            return None
        return find_csv_file(bill_dir)

    # 设置全局日志级别
    set_global_log_level(log_level)
    report(0, "准备下载支付宝/微信账单...")

    # 先检查本地文件，尽量避免不必要的邮箱连接/下载
    email_dir = create_storage_structure()
    alipay_dir = email_dir / "alipay"
    wechat_dir = email_dir / "wechat"

    result: Dict[str, object] = {
        "alipay": 0,
        "wechat": 0,
        "alipay_status": "unknown",
        "wechat_status": "unknown",
        "alipay_csv": None,
        "wechat_csv": None,
    }

    # 1) 本地已有 CSV：直接跳过下载
    existing_alipay_csv = find_csv_file(alipay_dir) if alipay_dir.exists() else None
    if existing_alipay_csv:
        result["alipay_status"] = "skipped_existing_csv"
        result["alipay_csv"] = str(existing_alipay_csv)

    existing_wechat_csv = find_csv_file(wechat_dir) if wechat_dir.exists() else None
    if existing_wechat_csv:
        result["wechat_status"] = "skipped_existing_csv"
        result["wechat_csv"] = str(existing_wechat_csv)

    # 1.5) 若未找到 CSV，但目录里已存在 ZIP，则后续只做「解压」而不再重新下载，避免一次性链接失效
    alipay_zip_path = None
    if result["alipay_status"] != "skipped_existing_csv" and alipay_dir.exists():
        alipay_zip_path = find_latest_zip_file(alipay_dir)

    wechat_zip_path = None
    if result["wechat_status"] != "skipped_existing_csv" and wechat_dir.exists():
        wechat_zip_path = find_latest_zip_file(wechat_dir)

    # 如果都已存在 CSV，就无需后续处理
    if (
        result["alipay_status"] == "skipped_existing_csv"
        and result["wechat_status"] == "skipped_existing_csv"
    ):
        report(100, "本地已存在支付宝/微信账单 CSV，已跳过下载。")
        return result

    # 2) 连接邮箱（只有在需要进一步处理时才连接）
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
        # 3) 若已有 ZIP 但未出现 CSV：仅尝试解压，不再重新下载
        if result["alipay_status"] != "skipped_existing_csv" and alipay_zip_path:
            if not alipay_pwd:
                result["alipay_status"] = "missing_password"
            else:
                report(30, "检测到本地已有支付宝ZIP，尝试解压...")
                extracted_csv = extract_existing_zip(
                    parser, alipay_zip_path, alipay_dir, alipay_pwd
                )
                if extracted_csv:
                    result["alipay_status"] = "extracted_existing_zip"
                    result["alipay_csv"] = str(extracted_csv)
                else:
                    result["alipay_status"] = "failed_extract_existing_zip"

        if result["wechat_status"] != "skipped_existing_csv" and wechat_zip_path:
            if not wechat_pwd:
                result["wechat_status"] = "missing_password"
            else:
                report(60, "检测到本地已有微信ZIP，尝试解压...")
                extracted_csv = extract_existing_zip(
                    parser, wechat_zip_path, wechat_dir, wechat_pwd
                )
                if extracted_csv:
                    result["wechat_status"] = "extracted_existing_zip"
                    result["wechat_csv"] = str(extracted_csv)
                else:
                    result["wechat_status"] = "failed_extract_existing_zip"

        # 4) 仍未有 CSV：下载最新邮件
        if (
            result["alipay_status"]
            not in ("skipped_existing_csv", "extracted_existing_zip")
            and not alipay_zip_path
        ):
            if not alipay_pwd:
                result["alipay_status"] = "missing_password"
            else:
                report(40, "正在查找最新的支付宝账单邮件...")
                alipay_emails = parser.get_latest_bill_emails("alipay")
                if not alipay_emails:
                    result["alipay_status"] = "not_found"
                else:
                    alipay_dir.mkdir(parents=True, exist_ok=True)
                    email_data = alipay_emails[0]
                    saved_files = parser.save_bill_attachments(email_data, alipay_dir)
                    zip_files = [p for p in saved_files if p.lower().endswith(".zip")]
                    if not zip_files:
                        result["alipay_status"] = "failed"
                    else:
                        zip_path = Path(zip_files[0])
                        extract_dir = alipay_dir / zip_path.stem
                        extract_dir.mkdir(parents=True, exist_ok=True)
                        if parser.extract_zip_file(
                            str(zip_path), extract_dir, alipay_pwd
                        ):
                            result["alipay"] = 1
                            result["alipay_status"] = "downloaded"
                            csv_path = find_csv_file(alipay_dir)
                            result["alipay_csv"] = str(csv_path) if csv_path else None
                        else:
                            result["alipay_status"] = "failed"

        if (
            result["wechat_status"]
            not in ("skipped_existing_csv", "extracted_existing_zip")
            and not wechat_zip_path
        ):
            if not wechat_pwd:
                result["wechat_status"] = "missing_password"
            else:
                report(70, "正在查找最新的微信账单邮件...")
                wechat_emails = parser.get_latest_bill_emails("wechat")
                if not wechat_emails:
                    result["wechat_status"] = "not_found"
                else:
                    wechat_dir.mkdir(parents=True, exist_ok=True)
                    email_data = wechat_emails[0]
                    download_link = parser.extract_wechat_download_link(email_data)
                    if not download_link:
                        result["wechat_status"] = "failed"
                    else:
                        saved_file = parser.download_wechat_bill(
                            download_link, wechat_dir
                        )
                        if not saved_file:
                            result["wechat_status"] = "failed"
                        else:
                            zip_path = Path(saved_file)
                            extract_dir = wechat_dir / zip_path.stem
                            extract_dir.mkdir(parents=True, exist_ok=True)
                            if parser.extract_zip_file(
                                str(zip_path), extract_dir, wechat_pwd
                            ):
                                result["wechat"] = 1
                                result["wechat_status"] = "downloaded"
                                csv_path = find_csv_file(wechat_dir)
                                result["wechat_csv"] = (
                                    str(csv_path) if csv_path else None
                                )
                            else:
                                result["wechat_status"] = "failed"

        report(100, "支付宝/微信账单处理完成。")
        return result

    finally:
        parser.close()


def merge_transaction_descriptions(
    credit_card_transactions: List[Transaction],
    digital_payment_transactions: List[Transaction],
) -> List[Transaction]:
    """合并信用卡交易和数字支付交易的描述"""
    logger.info("开始合并交易描述...")

    # 将数字支付交易按日期、金额和关联的信用卡建立索引
    dp_txns_index: Dict[Tuple[Any, Any, Any], List[Transaction]] = {}
    for dp_txn in digital_payment_transactions:
        if (
            isinstance(dp_txn, DigitalPaymentTransaction) and dp_txn.card_source
        ):  # 检查类型和卡信息
            key = (dp_txn.date, dp_txn.amount, dp_txn.card_source)
            if key not in dp_txns_index:
                dp_txns_index[key] = []
            dp_txns_index[key].append(dp_txn)

    matched_count = 0
    matched_dp_txns = set()

    for cc_txn in credit_card_transactions:
        key = (cc_txn.date, cc_txn.amount, cc_txn.source)

        if key in dp_txns_index:
            for dp_txn in dp_txns_index[key]:
                if dp_txn not in matched_dp_txns:
                    logger.debug("\n找到匹配的交易:")
                    logger.debug(
                        f"  信用卡: {cc_txn.date} | {cc_txn.description} | ¥{cc_txn.amount:.2f} | {cc_txn.source.value}"
                    )
                    # 安全访问 card_source 属性
                    card_source_str = getattr(dp_txn, "card_source", "N/A")
                    logger.debug(
                        f"  {dp_txn.source}: {dp_txn.date} | {dp_txn.description} | ¥{dp_txn.amount:.2f} | 支付方式: {card_source_str}"
                    )

                    cc_desc_len = len(cc_txn.description.strip())
                    dp_desc_len = len(dp_txn.description.strip())

                    if cc_desc_len >= dp_desc_len:
                        final_desc = cc_txn.description
                    else:
                        final_desc = dp_txn.description

                    cc_txn.description = final_desc
                    matched_dp_txns.add(dp_txn)
                    matched_count += 1
                    break

    # 过滤掉已匹配的数字支付交易
    unmatched_dp_txns = [
        txn for txn in digital_payment_transactions if txn not in matched_dp_txns
    ]
    all_transactions = credit_card_transactions + unmatched_dp_txns

    logger.info("\n合并完成:")
    logger.info(f"  - 成功匹配并合并: {matched_count} 条交易")
    logger.info(f"  - 已移除的重复数字支付交易: {len(matched_dp_txns)} 条")
    logger.info(f"  - 未匹配的数字支付交易: {len(unmatched_dp_txns)} 条")
    logger.info(f"  - 最终交易总数: {len(all_transactions)} 条")

    return all_transactions


def parse_downloaded_bills_to_beancount(
    start_date: datetime,
    end_date: datetime,
    log_level: str = "INFO",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    """
    解析所有已下载账单并导出为 Beancount（ui_plan.md 2.6）。

    关键点：
    - 以「交易发生日期」为准：所有解析器都会按 start_date/end_date 过滤交易；
    - 为保证结果符合直觉，这里不再用“账单目录日期”来决定是否解析某个账单目录；
    - 输出目前只支持 Beancount 文本（账户先用占位符，后续再做智能化处理）。

    Args:
        start_date: 时间范围开始（包含）
        end_date: 时间范围结束（包含）
        log_level: 日志级别
        progress_callback: 进度回调 (current, total, message)，total 固定 100

    Returns:
        {
          "beancount_text": str,
          "stats": {"folders_total": int, "folders_parsed": int, "txns_total": int},
          "output_path": str,
        }
    """
    set_global_log_level(log_level)

    def report(progress: int, message: str) -> None:
        if progress_callback:
            progress_callback(progress, 100, message)

    email_dir = EMAILS_DIR
    if not email_dir.exists():
        raise FileNotFoundError("未找到 emails 目录，请先下载账单")

    logger.info(
        "开始解析本地已下载账单，交易日期范围（包含起止日期）：%s ~ %s",
        start_date.strftime(DATE_FMT_ISO),
        end_date.strftime(DATE_FMT_ISO),
    )

    def is_credit_card_bill_folder(folder: Path) -> bool:
        if not folder.is_dir():
            return False
        if folder.name in ("alipay", "wechat", ".DS_Store"):
            return False
        return (folder / "content.html").exists() and (
            folder / "metadata.json"
        ).exists()

    def is_digital_bill_folder(folder: Path) -> bool:
        return folder.is_dir() and folder.name in ("alipay", "wechat")

    # 1) 收集将要解析的目录
    credit_card_folders: List[Path] = []
    digital_folders: List[Path] = []
    for folder in sorted(email_dir.iterdir()):
        if is_digital_bill_folder(folder):
            digital_folders.append(folder)
            continue
        if is_credit_card_bill_folder(folder):
            credit_card_folders.append(folder)

    folders_total = len(credit_card_folders) + len(digital_folders)
    report(0, f"发现账单目录 {folders_total} 个，准备开始解析...")
    logger.info("发现信用卡账单目录: %s 个", len(credit_card_folders))
    logger.info("发现微信/支付宝目录: %s 个", len(digital_folders))
    logger.debug("信用卡账单目录列表: %s", [p.name for p in credit_card_folders])
    logger.debug("微信/支付宝目录列表: %s", [p.name for p in digital_folders])

    # 2) 解析交易
    credit_card_transactions: List[Transaction] = []
    digital_transactions: List[Transaction] = []

    parsed_folders = 0
    for folder in credit_card_folders:
        parsed_folders += 1
        progress = int(parsed_folders / max(1, folders_total) * 70)
        report(progress, f"解析信用卡账单：{folder.name}")
        txns = parse_statement_email(folder, start_date, end_date)
        if txns:
            credit_card_transactions.extend(txns)
        logger.info("信用卡账单解析完成: %s, 交易数=%s", folder.name, len(txns or []))

    for folder in digital_folders:
        parsed_folders += 1
        progress = 70 + int(
            (parsed_folders - len(credit_card_folders))
            / max(1, len(digital_folders))
            * 20
        )
        report(progress, f"解析{folder.name}账单（交易时间过滤）...")
        txns = parse_statement_email(folder, start_date, end_date)
        if txns:
            digital_transactions.extend(txns)
        logger.info("%s账单解析完成: 交易数=%s", folder.name, len(txns or []))

    report(92, "合并交易描述并生成 Beancount...")

    merged_transactions = merge_transaction_descriptions(
        credit_card_transactions, digital_transactions
    )
    # 排序：先日期再描述，便于阅读
    merged_transactions = sorted(
        merged_transactions,
        key=lambda t: (str(getattr(t, "date", "")), str(getattr(t, "description", ""))),
    )
    if logger.isEnabledFor(logging.DEBUG):
        for txn in merged_transactions:
            try:
                logger.debug("txn: %s", txn.to_dict())
            except Exception:
                logger.debug(
                    "txn: date=%s desc=%s amount=%s source=%s",
                    getattr(txn, "date", None),
                    getattr(txn, "description", None),
                    getattr(txn, "amount", None),
                    getattr(txn, "source", None),
                )

    header = (
        f"FinanceMailParser Export\n"
        f"Range: {start_date.strftime(DATE_FMT_ISO)} ~ {end_date.strftime(DATE_FMT_ISO)}\n"
        f"Generated at: {datetime.now().strftime(DATETIME_FMT_ISO)}\n"
        f"Accounts are placeholders (TODO)."
    )
    beancount_text = transactions_to_beancount(
        merged_transactions,
        options=BeancountExportOptions(),
        header_comment=header,
    )

    output_dir = PROJECT_ROOT / "outputs" / "beancount"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir
        / f"transactions_{start_date.strftime(DATE_FMT_COMPACT)}_{end_date.strftime(DATE_FMT_COMPACT)}.bean"
    )
    output_path.write_text(beancount_text, encoding="utf-8")

    # UI 侧通常会单独展示「写入文件路径」，这里避免在进度消息里重复输出路径
    report(100, f"完成：共 {len(merged_transactions)} 条交易")
    logger.info("Beancount 已写入: %s", output_path)
    return {
        "beancount_text": beancount_text,
        "output_path": str(output_path),
        "stats": {
            "folders_total": folders_total,
            "folders_parsed": parsed_folders,
            "txns_total": len(merged_transactions),
        },
    }


def categorize_transaction(transaction: Transaction) -> str:
    """
    Categorize a transaction based on its description and amount.

    Args:
        transaction: Transaction object to categorize

    Returns:
        str: Category name
    """
    if any(keyword in transaction.description for keyword in TRANSPORT_KEYWORDS):
        return "交通"

    if any(keyword in transaction.description for keyword in MEAL_KEYWORDS):
        return "三餐"

    return "待分类"


def to_csv(transactions: List[Transaction]) -> None:
    """
    Process transactions and write them to CSV file.

    Args:
        transactions: List of Transaction objects to process
    """
    # Filter out invalid transactions
    valid_transactions = [
        txn for txn in transactions if txn.amount != 0.01 and not (-1 < txn.amount <= 0)
    ]

    # Sort and categorize transactions
    sorted_transactions = sorted(valid_transactions, key=lambda x: x.date)
    for transaction in sorted_transactions:
        transaction.category = categorize_transaction(transaction)
        print(transaction.to_dict())

    # Write to CSV
    csv_writer = CSVWriter(TRANSACTIONS_CSV, Transaction.get_fieldnames())
    csv_writer.write_transactions(sorted_transactions)
