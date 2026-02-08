"""
交易过滤规则（Plan.md 阶段 4.2）

在前端配置：
- 跳过关键词（描述包含子串则跳过）
- 金额过滤区间（闭区间 [gte, lte]）

说明：
- 规则对所有来源统一生效（信用卡/微信/支付宝不区分）
- 主要在“解析账单 -> 导出 Beancount”链路生效，同时解析器内部也会复用关键词过滤
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

import streamlit as st

from app.services import (
    AmountRange,
    DEFAULT_TRANSACTION_AMOUNT_RANGES,
    DEFAULT_TRANSACTION_SKIP_KEYWORDS,
    TransactionFilters,
    UserRulesError,
    amount_in_ranges,
    get_transaction_filters,
    match_skip_keyword,
    save_transaction_filters,
)
from ui.flash_utils import set_flash, show_flash
from ui.keyword_utils import keywords_to_text, parse_keywords


def _load_into_session(*, use_defaults: bool = False) -> None:
    filters: TransactionFilters
    if use_defaults:
        filters = {
            "skip_keywords": list(DEFAULT_TRANSACTION_SKIP_KEYWORDS),
            "amount_ranges": list(DEFAULT_TRANSACTION_AMOUNT_RANGES),
        }
    else:
        filters = get_transaction_filters()

    skip_keywords = filters["skip_keywords"]
    amount_ranges = filters["amount_ranges"]

    st.session_state["transaction_filter_rules_editor"] = {
        "skip_keywords_text": keywords_to_text(skip_keywords),
        "ranges": [
            {
                "_id": uuid.uuid4().hex,
                "gte": float(r["gte"]),
                "lte": float(r["lte"]),
            }
            for r in amount_ranges
        ],
    }


st.set_page_config(page_title="交易过滤规则", page_icon="🚫", layout="wide")
st.title("🚫 交易过滤规则")

st.caption(
    "解析所有的账单时，若交易描述命中这些关键字或者金额在区间内，则跳过这些交易记录。"
)
st.divider()

if "transaction_filter_rules_editor" not in st.session_state:
    try:
        _load_into_session()
    except UserRulesError as e:
        st.error(f"❌ 用户规则格式错误：{str(e)}")
        _load_into_session(use_defaults=True)
    except Exception as e:
        st.error(f"❌ 读取用户规则失败：{str(e)}")
        _load_into_session(use_defaults=True)

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 从 config.yaml 重新加载", use_container_width=True):
        _load_into_session()
        st.rerun()
with col2:
    if st.button("🧹 重置为默认", use_container_width=True):
        _load_into_session(use_defaults=True)
        st.rerun()

editor: Dict[str, Any] = st.session_state.get("transaction_filter_rules_editor") or {}

st.subheader("跳过关键词")
st.caption("任一关键字命中则跳过")
skip_keywords_text = st.text_area(
    "跳过关键词",
    value=str(editor.get("skip_keywords_text", "") or ""),
    height=220,
    placeholder="例如：\n还款\n微信红包\n收益发放\n",
    help="每行一个关键词；也支持逗号分隔。匹配方式为包含子串。",
    label_visibility="collapsed",
)
editor["skip_keywords_text"] = skip_keywords_text

st.divider()
st.subheader("金额过滤区间")
st.caption("例如：跳过 [0,1] 可设置 gte=0 且 lte=1。")

ranges: List[Dict[str, Any]] = editor.get("ranges") or []


if not ranges:
    st.info("当前没有金额过滤区间。你可以点击“新增区间”。")
else:
    for idx, r in enumerate(list(ranges)):
        rid = r.get("_id") or str(idx)
        with st.expander(f"区间 #{idx + 1}", expanded=(idx < 3)):
            c1, c2, c3, c4 = st.columns([4, 4, 1, 1])
            with c1:
                gte = st.number_input(
                    "gte（包含）",
                    value=float(r.get("gte", 0.0)),
                    format="%.2f",
                    key=f"tfr_gte_{rid}",
                )
            with c2:
                lte = st.number_input(
                    "lte（包含）",
                    value=float(r.get("lte", 0.0)),
                    format="%.2f",
                    key=f"tfr_lte_{rid}",
                )
            with c3:
                move_up = st.button("⬆️", key=f"tfr_up_{rid}", disabled=idx == 0)
            with c4:
                delete = st.button("🗑️", key=f"tfr_del_{rid}")

            r["gte"] = float(gte)
            r["lte"] = float(lte)

            if move_up and idx > 0:
                ranges[idx - 1], ranges[idx] = ranges[idx], ranges[idx - 1]
                editor["ranges"] = ranges
                st.rerun()

            if delete:
                editor["ranges"] = [x for x in ranges if (x.get("_id") or "") != rid]
                st.rerun()
if st.button("➕ 新增区间", use_container_width=True, type="primary"):
    ranges.append({"_id": uuid.uuid4().hex, "gte": 0.0, "lte": 0.0})
    editor["ranges"] = ranges
    st.rerun()

st.divider()
st.subheader("试算")
st.caption("输入一条交易描述与金额，查看当前（未保存修改也算）是否会被过滤。")

test_desc = st.text_input(
    "交易描述",
    value="",
    placeholder="例如：微信红包-收款-xxx",
    label_visibility="collapsed",
)
test_amount = st.number_input(
    "金额",
    value=0.0,
    format="%.2f",
    help="金额为交易记录里的 amount（正数支出，负数退款/收入）。",
)

preview_skip_keywords = parse_keywords(editor.get("skip_keywords_text", "") or "")
preview_ranges: List[AmountRange] = [
    {"gte": float(x.get("gte", 0.0)), "lte": float(x.get("lte", 0.0))}
    for x in (editor.get("ranges") or [])
]

if test_desc.strip() or test_amount != 0.0:
    matched_kw = match_skip_keyword(test_desc.strip(), preview_skip_keywords)
    matched_amt = amount_in_ranges(float(test_amount), preview_ranges)

    if matched_kw:
        st.error(f"❌ 将被过滤（关键词命中）：{matched_kw}")
    elif matched_amt:
        st.error("❌ 将被过滤（金额区间命中）")
    else:
        st.success("✅ 将保留（未命中任何过滤规则）")

st.divider()

save_feedback_placeholder = None
save = st.button("💾 保存过滤规则", use_container_width=True, type="primary")
save_feedback_placeholder = st.empty()
st.caption("保存时会做校验：关键词可为空；金额区间要求 gte <= lte（都必须是数字）。")

if save_feedback_placeholder is not None:
    show_flash(
        "transaction_filter_rules_flash",
        placeholder=save_feedback_placeholder,
    )

if save:
    to_save_keywords = parse_keywords(editor.get("skip_keywords_text", "") or "")
    to_save_ranges = [
        {"gte": float(x.get("gte", 0.0)), "lte": float(x.get("lte", 0.0))}
        for x in (editor.get("ranges") or [])
    ]

    try:
        save_transaction_filters(
            skip_keywords=to_save_keywords,
            amount_ranges=to_save_ranges,
        )
        _load_into_session()
        set_flash(
            "transaction_filter_rules_flash",
            level="success",
            message="✅ 已保存到 config.yaml",
        )
        st.rerun()
    except UserRulesError as e:
        if save_feedback_placeholder is not None:
            save_feedback_placeholder.error(f"❌ 保存失败：{str(e)}")
        else:
            st.error(f"❌ 保存失败：{str(e)}")
    except Exception as e:
        if save_feedback_placeholder is not None:
            save_feedback_placeholder.error(f"❌ 保存失败：{str(e)}")
        else:
            st.error(f"❌ 保存失败：{str(e)}")
