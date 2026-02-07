from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import logging

from constants import (
    BEANCOUNT_OUTPUT_DIR,
    DATETIME_FMT_ISO,
    DATE_FMT_COMPACT,
    DATE_FMT_ISO,
    EMAILS_DIR,
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)
from models.txn import DigitalPaymentTransaction, Transaction
from statement_parsers.parse import parse_statement_email
from utils.beancount_writer import BeancountExportOptions, transactions_to_beancount
from utils.logger import set_global_log_level
from config.user_rules import (
    DEFAULT_TRANSACTION_AMOUNT_RANGES,
    DEFAULT_TRANSACTION_SKIP_KEYWORDS,
    UserRulesError,
    amount_in_ranges,
    get_expenses_account_rules,
    get_transaction_filters,
    match_expenses_account,
    match_skip_keyword,
)

logger = logging.getLogger(__name__)


def _merge_transaction_descriptions(
    credit_card_transactions: List[Transaction],
    digital_payment_transactions: List[Transaction],
) -> List[Transaction]:
    """Merge credit-card and digital-payment descriptions and dedupe matched digital txns."""
    logger.info("开始合并交易描述...")

    dp_txns_index: Dict[Tuple[Any, Any, Any], List[Transaction]] = {}
    for dp_txn in digital_payment_transactions:
        if isinstance(dp_txn, DigitalPaymentTransaction) and dp_txn.card_source:
            key = (dp_txn.date, dp_txn.amount, dp_txn.card_source)
            dp_txns_index.setdefault(key, []).append(dp_txn)

    matched_count = 0
    matched_dp_txns = set()

    for cc_txn in credit_card_transactions:
        key = (cc_txn.date, cc_txn.amount, cc_txn.source)

        if key in dp_txns_index:
            for dp_txn in dp_txns_index[key]:
                if dp_txn in matched_dp_txns:
                    continue

                logger.debug("\n找到匹配的交易:")
                try:
                    logger.debug(
                        "  信用卡: %s | %s | ¥%.2f | %s",
                        cc_txn.date,
                        cc_txn.description,
                        cc_txn.amount,
                        getattr(cc_txn.source, "value", cc_txn.source),
                    )
                    card_source_str = getattr(dp_txn, "card_source", "N/A")
                    logger.debug(
                        "  %s: %s | %s | ¥%.2f | 支付方式: %s",
                        dp_txn.source,
                        dp_txn.date,
                        dp_txn.description,
                        dp_txn.amount,
                        card_source_str,
                    )
                except Exception:
                    pass

                cc_desc_len = len(str(cc_txn.description or "").strip())
                dp_desc_len = len(str(dp_txn.description or "").strip())

                final_desc = (
                    cc_txn.description
                    if cc_desc_len >= dp_desc_len
                    else dp_txn.description
                )
                cc_txn.description = final_desc

                matched_dp_txns.add(dp_txn)
                matched_count += 1
                break

    unmatched_dp_txns = [
        txn for txn in digital_payment_transactions if txn not in matched_dp_txns
    ]
    all_transactions = credit_card_transactions + unmatched_dp_txns

    logger.info("\n合并完成:")
    logger.info("  - 成功匹配并合并: %s 条交易", matched_count)
    logger.info("  - 已移除的重复数字支付交易: %s 条", len(matched_dp_txns))
    logger.info("  - 未匹配的数字支付交易: %s 条", len(unmatched_dp_txns))
    logger.info("  - 最终交易总数: %s 条", len(all_transactions))

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

    # Prepare user-configurable transaction filters early so parsers can skip
    # noise transactions before merging descriptions.
    skip_keywords = DEFAULT_TRANSACTION_SKIP_KEYWORDS
    amount_ranges = DEFAULT_TRANSACTION_AMOUNT_RANGES
    try:
        tx_filters = get_transaction_filters()
        skip_keywords = tx_filters["skip_keywords"]
        amount_ranges = tx_filters["amount_ranges"]
    except UserRulesError as e:
        logger.warning("用户过滤规则格式错误，将使用默认过滤规则：%s", e)
    except Exception as e:
        logger.warning("用户过滤规则加载失败，将使用默认过滤规则：%s", e)

    def should_skip_transaction(description: str) -> bool:
        return match_skip_keyword(str(description or ""), skip_keywords) is not None

    def is_credit_card_bill_folder(folder: Path) -> bool:
        if not folder.is_dir():
            return False
        if folder.name in ("alipay", "wechat", ".DS_Store"):
            return False
        return (folder / EMAIL_HTML_FILENAME).exists() and (
            folder / EMAIL_METADATA_FILENAME
        ).exists()

    def is_digital_bill_folder(folder: Path) -> bool:
        return folder.is_dir() and folder.name in ("alipay", "wechat")

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

    credit_card_transactions: List[Transaction] = []
    digital_transactions: List[Transaction] = []

    parsed_folders = 0
    for folder in credit_card_folders:
        parsed_folders += 1
        progress = int(parsed_folders / max(1, folders_total) * 70)
        report(progress, f"解析信用卡账单：{folder.name}")
        txns = parse_statement_email(
            folder,
            start_date,
            end_date,
            skip_transaction=should_skip_transaction,
        )
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
        txns = parse_statement_email(
            folder,
            start_date,
            end_date,
            skip_transaction=should_skip_transaction,
        )
        if txns:
            digital_transactions.extend(txns)
        logger.info("%s账单解析完成: 交易数=%s", folder.name, len(txns or []))

    report(92, "合并交易描述并生成 Beancount...")

    merged_transactions = _merge_transaction_descriptions(
        credit_card_transactions, digital_transactions
    )
    merged_transactions = sorted(
        merged_transactions,
        key=lambda t: (str(getattr(t, "date", "")), str(getattr(t, "description", ""))),
    )

    before_filter_total = len(merged_transactions)
    skipped_by_keyword = 0
    skipped_by_amount = 0
    filtered_transactions: List[Transaction] = []

    for txn in merged_transactions:
        desc = str(getattr(txn, "description", "") or "")
        amt = float(getattr(txn, "amount", 0.0) or 0.0)

        if match_skip_keyword(desc, skip_keywords) is not None:
            skipped_by_keyword += 1
            continue

        if amount_in_ranges(amt, amount_ranges):
            skipped_by_amount += 1
            continue

        filtered_transactions.append(txn)

    merged_transactions = filtered_transactions

    if skipped_by_keyword or skipped_by_amount:
        logger.info(
            "交易过滤：总=%s，按关键词跳过=%s，按金额跳过=%s，保留=%s",
            before_filter_total,
            skipped_by_keyword,
            skipped_by_amount,
            len(merged_transactions),
        )

    expenses_rules = []
    try:
        expenses_rules = get_expenses_account_rules()
    except UserRulesError as e:
        logger.warning("用户规则加载失败，将忽略消费账户关键词映射：%s", e)
    except Exception as e:
        logger.warning("用户规则加载失败，将忽略消费账户关键词映射：%s", e)

    matched_accounts = 0
    if expenses_rules:
        for txn in merged_transactions:
            try:
                amount = float(getattr(txn, "amount", 0.0) or 0.0)
                if amount < 0:
                    continue

                desc = str(getattr(txn, "description", "") or "")
                matched = match_expenses_account(desc, expenses_rules)
                if matched:
                    setattr(txn, "beancount_expenses_account", matched)
                    matched_accounts += 1
            except Exception:
                continue

        logger.info(
            "消费账户关键词映射：规则=%s，命中=%s",
            len(expenses_rules),
            matched_accounts,
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
        "FinanceMailParser Export\n"
        f"Range: {start_date.strftime(DATE_FMT_ISO)} ~ {end_date.strftime(DATE_FMT_ISO)}\n"
        f"Generated at: {datetime.now().strftime(DATETIME_FMT_ISO)}\n"
        "Accounts are placeholders (TODO) unless user_rules filled some Expenses accounts."
    )
    beancount_text = transactions_to_beancount(
        merged_transactions,
        options=BeancountExportOptions(),
        header_comment=header,
    )

    output_dir = BEANCOUNT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir
        / f"transactions_{start_date.strftime(DATE_FMT_COMPACT)}_{end_date.strftime(DATE_FMT_COMPACT)}.bean"
    )
    output_path.write_text(beancount_text, encoding="utf-8")

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
