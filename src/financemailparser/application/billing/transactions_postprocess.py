from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from financemailparser.application.settings.user_rules_facade import (
    get_expenses_account_rules_ui_snapshot,
    get_transaction_filters_ui_snapshot,
)
from financemailparser.infrastructure.config.user_rules import (
    AmountRange,
    match_expenses_account,
    match_skip_keyword,
)
from financemailparser.domain.models.txn import DigitalPaymentTransaction, Transaction
from financemailparser.domain.services.date_filter import parse_date_safe

logger = logging.getLogger(__name__)

_DETAIL_PREFIXES = ("支付宝-", "微信-")
_NOISE_DIGIT_SEQ_MIN_LEN = 8
_NOISE_DIGIT_SEQ_RE = re.compile(rf"\d{{{_NOISE_DIGIT_SEQ_MIN_LEN},}}")
_NOISE_HINT_KEYWORDS = (
    "收银",
    "订单号",
    "交易单号",
    "商户单号",
    "流水",
)
_PLATFORM_WORDS = (
    "美团",
    "饿了么",
    "支付宝",
    "微信",
    "财付通",
    "云闪付",
    "银联",
)
_MIN_EFFECTIVE_MERCHANT_LEN_FOR_PLATFORM_ONLY = 4


def _normalize_desc_for_detail_compare(desc: str) -> str:
    s = str(desc or "").strip()
    for prefix in _DETAIL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    return s


def _has_ellipsis(desc: str) -> bool:
    s = str(desc or "")
    return ("…" in s) or ("..." in s)


def _strip_noise_tokens_for_effective_text(desc: str) -> str:
    """
    Produce a conservative "effective" text for comparing merchant-like details.
    This is ONLY used for scoring/choosing; we do not rewrite the final description.
    """
    s = _normalize_desc_for_detail_compare(desc)
    s = _NOISE_DIGIT_SEQ_RE.sub("", s)
    for kw in _NOISE_HINT_KEYWORDS:
        s = s.replace(kw, "")
    for w in _PLATFORM_WORDS:
        s = s.replace(w, "")
    # Remove punctuation/whitespace/digits to keep "content-like" chars.
    s = re.sub(r"[\s\-_:/#（）()，,。.;；·]+", "", s)
    s = re.sub(r"\d+", "", s)
    return s.strip()


def _is_platform_noise_desc(desc: str) -> bool:
    """
    Identify descriptions that are likely platform/channel noise (e.g., '美团收银...').
    Keep it conservative to avoid breaking existing behavior.
    """
    raw = _normalize_desc_for_detail_compare(desc)
    if not raw:
        return False

    # Strong signal: long digit sequences (receipt/order ids).
    if _NOISE_DIGIT_SEQ_RE.search(raw):
        return True

    # Keyword + any digit is usually an id-like noise.
    if any(kw in raw for kw in _NOISE_HINT_KEYWORDS) and any(
        ch.isdigit() for ch in raw
    ):
        return True

    # Platform-only: contains platform word but has too little effective merchant text.
    if any(w in raw for w in _PLATFORM_WORDS):
        effective = _strip_noise_tokens_for_effective_text(raw)
        if len(effective) < _MIN_EFFECTIVE_MERCHANT_LEN_FOR_PLATFORM_ONLY:
            return True

    return False


@dataclass(frozen=True)
class TransactionFilterStats:
    skipped_by_keyword: int
    skipped_by_amount: int
    before_total: int
    after_total: int


@dataclass(frozen=True)
class KeywordSkipItem:
    date: str
    source: str
    amount: float
    description: str
    matched_keyword: str


@dataclass(frozen=True)
class AmountSkipItem:
    date: str
    source: str
    amount: float
    description: str
    matched_range_raw: str


@dataclass(frozen=True)
class CCDigitalMatch:
    cc_txn: Transaction
    dp_txn: DigitalPaymentTransaction
    cc_description_before: str
    dp_description: str
    final_description: str
    final_from: str  # "cc" or "dp"


def find_cc_digital_matches(
    credit_card_transactions: List[Transaction],
    digital_payment_transactions: List[Transaction],
) -> List[CCDigitalMatch]:
    """
    Find matches between credit-card transactions and WeChat/Alipay credit-card payments.

    Matching key:
    - date
    - amount
    - card_source (from dp_txn) equals cc_txn.source
    """
    dp_txns_index: Dict[Tuple[Any, Any, Any], List[DigitalPaymentTransaction]] = {}
    for dp_txn in digital_payment_transactions:
        if isinstance(dp_txn, DigitalPaymentTransaction) and dp_txn.card_source:
            dp_dt = parse_date_safe(getattr(dp_txn, "date", ""))
            dp_date_key = (
                dp_dt.strftime("%Y-%m-%d")
                if dp_dt
                else str(getattr(dp_txn, "date", "") or "")
            )
            key = (dp_date_key, dp_txn.amount, dp_txn.card_source)
            dp_txns_index.setdefault(key, []).append(dp_txn)

    matches: List[CCDigitalMatch] = []
    matched_dp_txns = set()

    for cc_txn in credit_card_transactions:
        cc_dt = parse_date_safe(getattr(cc_txn, "date", ""))
        cc_date_key = (
            cc_dt.strftime("%Y-%m-%d")
            if cc_dt
            else str(getattr(cc_txn, "date", "") or "")
        )
        key = (cc_date_key, cc_txn.amount, cc_txn.source)
        if key not in dp_txns_index:
            continue

        for dp_txn in dp_txns_index[key]:
            if dp_txn in matched_dp_txns:
                continue

            dp_dt = parse_date_safe(getattr(dp_txn, "date", ""))
            # Explicit same-day requirement (conservative):
            # - if both dates parseable: must be same calendar day
            # - otherwise: require raw date string equality
            if cc_dt and dp_dt:
                if dp_dt.date() != cc_dt.date():
                    continue
            else:
                if str(getattr(dp_txn, "date", "") or "") != str(
                    getattr(cc_txn, "date", "") or ""
                ):
                    continue

            cc_desc_before = str(cc_txn.description or "")
            dp_desc = str(dp_txn.description or "")

            cc_has_ellipsis = _has_ellipsis(cc_desc_before)
            dp_has_ellipsis = _has_ellipsis(dp_desc)
            if cc_has_ellipsis != dp_has_ellipsis:
                # Prefer the one without ellipsis (usually means not truncated).
                if cc_has_ellipsis:
                    final_desc = dp_desc
                    final_from = "dp"
                else:
                    final_desc = cc_desc_before
                    final_from = "cc"
            else:
                # Prefer merchant-like descriptions over platform/channel noise.
                cc_is_noise = _is_platform_noise_desc(cc_desc_before)
                dp_is_noise = _is_platform_noise_desc(dp_desc)
                if cc_is_noise != dp_is_noise:
                    if cc_is_noise:
                        final_desc = dp_desc
                        final_from = "dp"
                    else:
                        final_desc = cc_desc_before
                        final_from = "cc"
                else:
                    cc_norm = _normalize_desc_for_detail_compare(cc_desc_before)
                    dp_norm = _normalize_desc_for_detail_compare(dp_desc)
                    if len(cc_norm) >= len(dp_norm):
                        final_desc = cc_desc_before
                        final_from = "cc"
                    else:
                        final_desc = dp_desc
                        final_from = "dp"

            matches.append(
                CCDigitalMatch(
                    cc_txn=cc_txn,
                    dp_txn=dp_txn,
                    cc_description_before=cc_desc_before,
                    dp_description=dp_desc,
                    final_description=final_desc,
                    final_from=final_from,
                )
            )
            matched_dp_txns.add(dp_txn)
            break

    return matches


def load_transaction_filters_safe() -> Tuple[List[str], List[AmountRange]]:
    """
    Load user-configurable transaction filters, with safe fallbacks.

    Returns:
        (skip_keywords, amount_ranges)
    """
    snap = get_transaction_filters_ui_snapshot()
    if snap.state == "format_error":
        logger.warning(
            "用户过滤规则格式错误，将使用默认过滤规则：%s", snap.error_message
        )
    elif snap.state == "load_failed":
        logger.warning(
            "用户过滤规则加载失败，将使用默认过滤规则：%s", snap.error_message
        )

    filters = dict(snap.filters or {})
    skip_keywords = list(filters.get("skip_keywords") or [])
    amount_ranges = list(filters.get("amount_ranges") or [])
    return skip_keywords, amount_ranges


def make_should_skip_transaction(skip_keywords: List[str]) -> Callable[[str], bool]:
    def should_skip_transaction(description: str) -> bool:
        return match_skip_keyword(str(description or ""), skip_keywords) is not None

    return should_skip_transaction


def merge_transaction_descriptions(
    credit_card_transactions: List[Transaction],
    digital_payment_transactions: List[Transaction],
) -> List[Transaction]:
    """
    Merge credit-card and digital-payment descriptions and dedupe duplicates.

    Rule:
    - If matched, keep the transaction whose description is longer.
    - If equal length, keep the credit-card transaction (deterministic).
    - The removed one is excluded from the returned list.
    """
    logger.info("开始合并交易描述...")

    matches = find_cc_digital_matches(
        credit_card_transactions, digital_payment_transactions
    )
    to_remove: set[Transaction] = set()
    matched_count = len(matches)

    for m in matches:
        cc_txn = m.cc_txn
        dp_txn = m.dp_txn

        logger.debug("\n找到匹配的交易:")
        try:
            logger.debug(
                "  信用卡: %s | %s | ¥%.2f | %s",
                cc_txn.date,
                m.cc_description_before,
                cc_txn.amount,
                getattr(cc_txn.source, "value", cc_txn.source),
            )
            card_source_str = getattr(dp_txn, "card_source", "N/A")
            logger.debug(
                "  %s: %s | %s | ¥%.2f | 支付方式: %s",
                dp_txn.source,
                dp_txn.date,
                m.dp_description,
                dp_txn.amount,
                card_source_str,
            )
        except Exception:
            pass

        if m.final_from == "cc":
            cc_txn.description = m.final_description
            to_remove.add(dp_txn)
        else:
            # Keep dp txn (more detailed), remove cc txn.
            to_remove.add(cc_txn)

    all_transactions = [
        t
        for t in (list(credit_card_transactions) + list(digital_payment_transactions))
        if t not in to_remove
    ]

    logger.info("\n合并完成:")
    logger.info("  - 成功匹配并合并: %s 条交易", matched_count)
    logger.info("  - 已移除的重复交易: %s 条", len(to_remove))
    logger.info("  - 最终交易总数: %s 条", len(all_transactions))

    return all_transactions


def filter_transactions_by_rules(
    transactions: List[Transaction],
    *,
    skip_keywords: List[str],
    amount_ranges: List[AmountRange],
) -> Tuple[
    List[Transaction],
    TransactionFilterStats,
    List[KeywordSkipItem],
    List[AmountSkipItem],
]:
    before_filter_total = len(transactions)
    skipped_by_keyword = 0
    skipped_by_amount = 0
    filtered_transactions: List[Transaction] = []
    keyword_skipped: List[KeywordSkipItem] = []
    amount_skipped: List[AmountSkipItem] = []

    for txn in transactions:
        desc = str(getattr(txn, "description", "") or "")
        amt = float(getattr(txn, "amount", 0.0) or 0.0)

        matched_keyword = match_skip_keyword(desc, skip_keywords)
        if matched_keyword is not None:
            skipped_by_keyword += 1
            keyword_skipped.append(
                KeywordSkipItem(
                    date=str(getattr(txn, "date", "") or ""),
                    source=str(
                        getattr(getattr(txn, "source", None), "value", None)
                        or getattr(txn, "source", "")
                    ),
                    amount=float(amt),
                    description=desc,
                    matched_keyword=str(matched_keyword),
                )
            )
            continue

        matched_range: tuple[float, float] | None = None
        for r in amount_ranges or []:
            try:
                gte = float(r["gte"])
                lte = float(r["lte"])
            except Exception:
                continue
            if gte <= amt <= lte:
                matched_range = (gte, lte)
                break

        if matched_range is not None:
            skipped_by_amount += 1
            gte, lte = matched_range
            amount_skipped.append(
                AmountSkipItem(
                    date=str(getattr(txn, "date", "") or ""),
                    source=str(
                        getattr(getattr(txn, "source", None), "value", None)
                        or getattr(txn, "source", "")
                    ),
                    amount=float(amt),
                    description=desc,
                    matched_range_raw=f"[{gte}, {lte}]",
                )
            )
            continue

        filtered_transactions.append(txn)

    stats = TransactionFilterStats(
        skipped_by_keyword=skipped_by_keyword,
        skipped_by_amount=skipped_by_amount,
        before_total=before_filter_total,
        after_total=len(filtered_transactions),
    )
    return filtered_transactions, stats, keyword_skipped, amount_skipped


def load_expenses_account_rules_safe() -> List[Dict[str, Any]]:
    snap = get_expenses_account_rules_ui_snapshot()
    if snap.state == "format_error":
        logger.warning(
            "用户规则加载失败，将忽略消费账户关键词映射：%s", snap.error_message
        )
    elif snap.state == "load_failed":
        logger.warning(
            "用户规则加载失败，将忽略消费账户关键词映射：%s", snap.error_message
        )
    return list(snap.rules or [])


def apply_expenses_account_rules(
    transactions: List[Transaction],
    *,
    expenses_rules: List[Dict[str, Any]],
) -> int:
    matched_accounts = 0
    if not expenses_rules:
        return 0

    for txn in transactions:
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

    return matched_accounts
