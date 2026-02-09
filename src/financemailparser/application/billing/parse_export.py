from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional
import logging

from financemailparser.shared.constants import (
    BEANCOUNT_OUTPUT_DIR,
    DATETIME_FMT_ISO,
    DATE_FMT_COMPACT,
    DATE_FMT_ISO,
    EMAILS_DIR,
)
from financemailparser.infrastructure.config.business_rules import (
    get_bank_alias_keywords,
)
from financemailparser.application.billing.folder_scan import (
    scan_downloaded_bill_folders,
)
from financemailparser.application.billing.transactions_postprocess import (
    apply_expenses_account_rules,
    filter_transactions_by_rules,
    load_expenses_account_rules_safe,
    load_transaction_filters_safe,
    make_should_skip_transaction,
    merge_transaction_descriptions,
)
from financemailparser.domain.models.txn import Transaction
from financemailparser.infrastructure.statement_parsers.parse import (
    parse_statement_email,
)
from financemailparser.domain.services.bank_alias import build_bank_alias_keywords
from financemailparser.infrastructure.beancount.writer import (
    BeancountExportOptions,
    transactions_to_beancount,
)
from financemailparser.shared.logger import set_global_log_level

logger = logging.getLogger(__name__)


def parse_downloaded_bills_to_beancount(
    start_date: datetime,
    end_date: datetime,
    log_level: str = "INFO",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    """
    解析所有已下载账单并导出为 Beancount

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
    skip_keywords, amount_ranges = load_transaction_filters_safe()
    should_skip_transaction = make_should_skip_transaction(skip_keywords)
    bank_alias_keywords = build_bank_alias_keywords(get_bank_alias_keywords())

    credit_card_folders, digital_folders = scan_downloaded_bill_folders(email_dir)

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
            bank_alias_keywords=bank_alias_keywords,
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
            bank_alias_keywords=bank_alias_keywords,
        )
        if txns:
            digital_transactions.extend(txns)
        logger.info("%s账单解析完成: 交易数=%s", folder.name, len(txns or []))

    report(92, "合并交易描述并生成 Beancount...")

    merged_transactions = merge_transaction_descriptions(
        credit_card_transactions, digital_transactions
    )
    merged_transactions = sorted(
        merged_transactions,
        key=lambda t: (str(getattr(t, "date", "")), str(getattr(t, "description", ""))),
    )

    merged_transactions, filter_stats = filter_transactions_by_rules(
        merged_transactions,
        skip_keywords=skip_keywords,
        amount_ranges=amount_ranges,
    )

    if filter_stats.skipped_by_keyword or filter_stats.skipped_by_amount:
        logger.info(
            "交易过滤：总=%s，按关键词跳过=%s，按金额跳过=%s，保留=%s",
            filter_stats.before_total,
            filter_stats.skipped_by_keyword,
            filter_stats.skipped_by_amount,
            filter_stats.after_total,
        )

    expenses_rules = load_expenses_account_rules_safe()
    matched_accounts = apply_expenses_account_rules(
        merged_transactions,
        expenses_rules=expenses_rules,
    )

    if expenses_rules:
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
