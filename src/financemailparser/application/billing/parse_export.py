from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional, TypedDict
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
    find_cc_digital_matches,
    merge_transaction_descriptions,
)
from financemailparser.domain.models.source import TransactionSource
from financemailparser.domain.models.txn import Transaction
from financemailparser.domain.services.transactions_filter import (
    RefundPair,
    find_matching_refund_pairs,
)
from financemailparser.infrastructure.statement_parsers.parse import (
    parse_statement_email,
)
from financemailparser.domain.services.bank_alias import build_bank_alias_keywords
from financemailparser.infrastructure.beancount.writer import (
    BeancountExportOptions,
    transactions_to_beancount,
)
from financemailparser.shared.logger import set_global_log_level
from dataclasses import asdict

logger = logging.getLogger(__name__)


ParseExportStats = TypedDict(
    "ParseExportStats",
    {
        "folders_total": int,
        "folders_parsed": int,
        "txns_total": int,
        "txns_before_dedup": int,
        "txns_after_cc_digital": int,
        "txns_after_refund": int,
        "cc_digital_removed": int,
        "refund_pairs_removed": int,
        "skipped_by_keyword": int,
        "skipped_by_amount": int,
    },
)

ParseExportDetails = TypedDict(
    "ParseExportDetails",
    {
        "cc_wechat_alipay_removed": list[dict[str, Any]],
        "refund_pairs_removed": list[dict[str, Any]],
        "keyword_skipped": list[dict[str, Any]],
        "amount_skipped": list[dict[str, Any]],
    },
)

ParseExportResult = TypedDict(
    "ParseExportResult",
    {
        "beancount_text": str,
        "output_path": str,
        "output_file_name": str,
        "stats": ParseExportStats,
        "details": ParseExportDetails,
    },
)


@dataclass(frozen=True)
class ParsedBillsResult:
    """解析所有账单后的原始结果（未去重）"""

    credit_card_transactions: List[Transaction]
    digital_transactions: List[Transaction]
    folders_total: int
    folders_parsed: int


def parse_all_bills(
    start_date: datetime,
    end_date: datetime,
    *,
    skip_refund_filter: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> ParsedBillsResult:
    """
    扫描并解析所有已下载账单，返回原始交易列表（信用卡 + 数字钱包分开）。

    此函数不做去重，供解析和去重模块共用。

    Args:
        start_date: 交易日期范围开始
        end_date: 交易日期范围结束
        skip_refund_filter: 是否跳过银行解析器内部的退款去重
        progress_callback: 进度回调 (current, total, message)
    """

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

    skip_keywords, _amount_ranges = load_transaction_filters_safe()
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
            skip_refund_filter=skip_refund_filter,
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

    return ParsedBillsResult(
        credit_card_transactions=credit_card_transactions,
        digital_transactions=digital_transactions,
        folders_total=folders_total,
        folders_parsed=parsed_folders,
    )


def parse_downloaded_bills_to_beancount(
    start_date: datetime,
    end_date: datetime,
    log_level: str = "INFO",
    *,
    enable_cc_digital_dedup: bool = False,
    enable_refund_dedup: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> ParseExportResult:
    """
    解析所有已下载账单并导出为 Beancount（默认不做去重，可选启用去重）

    关键点：
    - 以「交易发生日期」为准：所有解析器都会按 start_date/end_date 过滤交易；
    - 为保证结果符合直觉，这里不再用"账单目录日期"来决定是否解析某个账单目录；
    - 默认不做信用卡与数字钱包去重，也不做退款配对去重；可通过参数启用；
    - 输出目前只支持 Beancount 文本（账户先用占位符，后续再做智能化处理）。
    """
    set_global_log_level(log_level)

    def report(progress: int, message: str) -> None:
        if progress_callback:
            progress_callback(progress, 100, message)

    parsed = parse_all_bills(
        start_date,
        end_date,
        skip_refund_filter=True,
        progress_callback=progress_callback,
    )

    report(92, "合并交易并生成 Beancount...")

    all_transactions = list(parsed.credit_card_transactions) + list(
        parsed.digital_transactions
    )
    all_transactions = sorted(
        all_transactions,
        key=lambda t: (str(getattr(t, "date", "")), str(getattr(t, "description", ""))),
    )

    skip_keywords, amount_ranges = load_transaction_filters_safe()
    all_transactions, filter_stats, keyword_skipped, amount_skipped = (
        filter_transactions_by_rules(
            all_transactions,
            skip_keywords=skip_keywords,
            amount_ranges=amount_ranges,
        )
    )

    if filter_stats.skipped_by_keyword or filter_stats.skipped_by_amount:
        logger.info(
            "交易过滤：总=%s，按关键词跳过=%s，按金额跳过=%s，保留=%s",
            filter_stats.before_total,
            filter_stats.skipped_by_keyword,
            filter_stats.skipped_by_amount,
            filter_stats.after_total,
        )

    txns_before_dedup = len(all_transactions)
    cc_digital_removed = 0
    refund_pairs_removed = 0
    cc_digital_removed_items: list[dict[str, object]] = []
    refund_pairs_items: list[dict[str, object]] = []
    keyword_skipped_items: list[dict[str, object]] = [
        asdict(i) for i in keyword_skipped
    ]
    amount_skipped_items: list[dict[str, object]] = [asdict(i) for i in amount_skipped]

    if enable_cc_digital_dedup or enable_refund_dedup:
        report(94, "执行可选去重...")

    if enable_cc_digital_dedup and all_transactions:
        cc_txns = [
            t
            for t in all_transactions
            if getattr(t, "source", None)
            in [
                TransactionSource.CCB,
                TransactionSource.CMB,
                TransactionSource.CEB,
                TransactionSource.ABC,
                TransactionSource.ICBC,
            ]
        ]
        dp_txns = [
            t
            for t in all_transactions
            if getattr(t, "source", None)
            in [TransactionSource.ALIPAY, TransactionSource.WECHAT]
        ]
        if cc_txns and dp_txns:
            matches = find_cc_digital_matches(cc_txns, dp_txns)
            all_transactions = merge_transaction_descriptions(cc_txns, dp_txns)
            cc_digital_removed = len(matches)
            for m in matches:
                cc = m.cc_txn
                dp = m.dp_txn
                cc_digital_removed_items.append(
                    {
                        "cc_date": str(getattr(cc, "date", "") or ""),
                        "cc_source": str(
                            getattr(getattr(cc, "source", None), "value", None)
                            or getattr(cc, "source", "")
                        ),
                        "cc_amount": float(getattr(cc, "amount", 0.0) or 0.0),
                        "cc_description": str(m.cc_description_before or ""),
                        "wx_alipay_date": str(getattr(dp, "date", "") or ""),
                        "wx_alipay_source": str(
                            getattr(getattr(dp, "source", None), "value", None)
                            or getattr(dp, "source", "")
                        ),
                        "wx_alipay_amount": float(getattr(dp, "amount", 0.0) or 0.0),
                        "wx_alipay_description": str(m.dp_description or ""),
                        "wx_alipay_card_source": str(
                            getattr(getattr(dp, "card_source", None), "value", None)
                            or getattr(dp, "card_source", "")
                        ),
                        "final_description": str(m.final_description or ""),
                        "final_from": str(m.final_from or ""),
                    }
                )

    after_cc_digital_count = len(all_transactions)

    if enable_refund_dedup and all_transactions:
        pairs: list[RefundPair] = find_matching_refund_pairs(all_transactions)
        to_remove = {p.purchase for p in pairs} | {p.refund for p in pairs}
        all_transactions = [t for t in all_transactions if t not in to_remove]
        refund_pairs_removed = len(to_remove)
        for p in pairs:
            refund_pairs_items.append(
                {
                    "purchase_date": str(getattr(p.purchase, "date", "") or ""),
                    "purchase_source": str(
                        getattr(getattr(p.purchase, "source", None), "value", None)
                        or getattr(p.purchase, "source", "")
                    ),
                    "purchase_amount": float(getattr(p.purchase, "amount", 0.0) or 0.0),
                    "purchase_description": str(
                        getattr(p.purchase, "description", "") or ""
                    ),
                    "refund_date": str(getattr(p.refund, "date", "") or ""),
                    "refund_source": str(
                        getattr(getattr(p.refund, "source", None), "value", None)
                        or getattr(p.refund, "source", "")
                    ),
                    "refund_amount": float(getattr(p.refund, "amount", 0.0) or 0.0),
                    "refund_description": str(
                        getattr(p.refund, "description", "") or ""
                    ),
                }
            )

    after_refund_count = len(all_transactions)

    expenses_rules = load_expenses_account_rules_safe()
    matched_accounts = apply_expenses_account_rules(
        all_transactions,
        expenses_rules=expenses_rules,
    )

    if expenses_rules:
        logger.info(
            "消费账户关键词映射：规则=%s，命中=%s",
            len(expenses_rules),
            matched_accounts,
        )

    if logger.isEnabledFor(logging.DEBUG):
        for txn in all_transactions:
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
        f"CC-Digital dedup: {'enabled' if enable_cc_digital_dedup else 'disabled'}\n"
        f"Refund dedup: {'enabled' if enable_refund_dedup else 'disabled'}\n"
        f"Before dedup: {txns_before_dedup}, CC-Digital removed: {cc_digital_removed}, "
        f"Refund pairs removed: {refund_pairs_removed}, Final: {len(all_transactions)}\n"
        "Accounts are placeholders (TODO) unless user_rules filled some Expenses accounts."
    )
    beancount_text = transactions_to_beancount(
        all_transactions,
        options=BeancountExportOptions(),
        header_comment=header,
    )

    output_dir = BEANCOUNT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    file_suffix = "_deduped" if (enable_cc_digital_dedup or enable_refund_dedup) else ""
    output_file_name = f"transactions_{start_date.strftime(DATE_FMT_COMPACT)}_{end_date.strftime(DATE_FMT_COMPACT)}{file_suffix}.bean"
    output_path = output_dir / output_file_name
    output_path.write_text(beancount_text, encoding="utf-8")

    report(100, f"完成：共 {len(all_transactions)} 条交易")
    logger.info("Beancount 已写入: %s", output_path)
    return {
        "beancount_text": beancount_text,
        "output_path": str(output_path),
        "output_file_name": output_file_name,
        "stats": {
            "folders_total": parsed.folders_total,
            "folders_parsed": parsed.folders_parsed,
            "txns_total": len(all_transactions),
            "txns_before_dedup": txns_before_dedup,
            "txns_after_cc_digital": after_cc_digital_count,
            "txns_after_refund": after_refund_count,
            "cc_digital_removed": cc_digital_removed,
            "refund_pairs_removed": refund_pairs_removed,
            "skipped_by_keyword": int(
                getattr(filter_stats, "skipped_by_keyword", 0) or 0
            ),
            "skipped_by_amount": int(
                getattr(filter_stats, "skipped_by_amount", 0) or 0
            ),
        },
        "details": {
            "cc_wechat_alipay_removed": cc_digital_removed_items,
            "refund_pairs_removed": refund_pairs_items,
            "keyword_skipped": keyword_skipped_items,
            "amount_skipped": amount_skipped_items,
        },
    }
