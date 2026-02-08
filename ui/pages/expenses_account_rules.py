"""
消费账户关键词映射（Plan.md 阶段 4.1）

在前端配置：
- Expenses:* Beancount 账户
- 关键词列表（包含子串匹配）

解析账单导出 Beancount 时：
- 命中规则的交易会直接填充 Expenses posting 的账户
- 未命中仍保持 Expenses:TODO（由 constants.py 定义，用户不可配置）
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

import streamlit as st

from app.services.user_rules_service import (
    UserRulesError,
    get_expenses_account_rules,
    match_expenses_account,
    save_expenses_account_rules,
)
from constants import BEANCOUNT_TODO_TOKEN
from ui.flash_utils import set_flash, show_flash
from ui.keyword_utils import keywords_to_text, parse_keywords


def _load_rules_into_session() -> None:
    rules_from_config: List[Dict[str, Any]] = []
    try:
        rules_from_config = get_expenses_account_rules()
    except UserRulesError as e:
        st.error(f"❌ 用户规则格式错误：{str(e)}")
    except Exception as e:
        st.error(f"❌ 读取用户规则失败：{str(e)}")

    st.session_state["expenses_account_rules_editor"] = [
        {
            "_id": uuid.uuid4().hex,
            "account": str(rule.get("account", "") or ""),
            "keywords_text": keywords_to_text(rule.get("keywords") or []),
        }
        for rule in rules_from_config
    ]


st.set_page_config(page_title="消费账户规则", page_icon="🏷️", layout="wide")
st.title("🏷️ 消费账户关键词映射")

st.caption(
    "解析账单时，若交易描述命中某条规则，则将该笔交易的支出账户直接填充为对应的 `Expenses:*` 账户。"
)
st.divider()

if "expenses_account_rules_editor" not in st.session_state:
    _load_rules_into_session()

col_left, col_right = st.columns([1, 1])
with col_left:
    if st.button("🔄 从 config.yaml 重新加载", use_container_width=True):
        _load_rules_into_session()
        st.rerun()
with col_right:
    if st.button("➕ 新增规则", use_container_width=True, type="primary"):
        st.session_state["expenses_account_rules_editor"].append(
            {"_id": uuid.uuid4().hex, "account": "", "keywords_text": ""}
        )
        st.rerun()

rules = st.session_state.get("expenses_account_rules_editor") or []

if not rules:
    st.info("当前没有规则。你可以点击“新增规则”开始配置。")
else:
    st.subheader("规则列表（按顺序匹配）")

for idx, rule in enumerate(list(rules)):
    rule_id = rule.get("_id") or str(idx)
    account_preview = str(rule.get("account", "") or "").strip() or "（未填写账户）"
    title = f"#{idx + 1}  {account_preview}"

    with st.expander(title, expanded=(idx < 3)):
        col1, col2, col3, col4 = st.columns([6, 1, 1, 1])
        with col1:
            account = st.text_input(
                "消费账户（必须以 Expenses: 开头）",
                value=str(rule.get("account", "") or ""),
                key=f"ear_account_{rule_id}",
                placeholder="例如：Expenses:Food:Cafe",
            )
        with col2:
            move_up = st.button("⬆️", key=f"ear_up_{rule_id}", disabled=idx == 0)
        with col3:
            move_down = st.button(
                "⬇️", key=f"ear_down_{rule_id}", disabled=idx == len(rules) - 1
            )
        with col4:
            delete = st.button("🗑️", key=f"ear_del_{rule_id}")

        keywords_text = st.text_area(
            "关键词（每行一个；也支持用逗号分隔）",
            value=str(rule.get("keywords_text", "") or ""),
            key=f"ear_kw_{rule_id}",
            height=140,
            placeholder="例如：\n星巴克\n瑞幸\n",
        )

        # Sync back to session-state list
        rule["account"] = account
        rule["keywords_text"] = keywords_text

        if move_up and idx > 0:
            rules[idx - 1], rules[idx] = rules[idx], rules[idx - 1]
            st.session_state["expenses_account_rules_editor"] = rules
            st.rerun()

        if move_down and idx < len(rules) - 1:
            rules[idx + 1], rules[idx] = rules[idx], rules[idx + 1]
            st.session_state["expenses_account_rules_editor"] = rules
            st.rerun()

        if delete:
            st.session_state["expenses_account_rules_editor"] = [
                r for r in rules if (r.get("_id") or "") != rule_id
            ]
            st.rerun()

st.divider()
st.subheader("试算")
st.caption("输入一条交易描述，查看当前规则（含未保存修改）会命中哪个 Expenses 账户。")

test_desc = st.text_input(
    "交易描述",
    value="",
    placeholder="例如：星巴克(国贸) - 微信支付 - ...",
    label_visibility="collapsed",
)

preview_rules: List[Dict[str, Any]] = []
for rule in st.session_state.get("expenses_account_rules_editor") or []:
    account = str(rule.get("account", "") or "").strip()
    keywords = parse_keywords(str(rule.get("keywords_text", "") or ""))
    if account and keywords:
        preview_rules.append({"account": account, "keywords": keywords})

if test_desc.strip():
    matched = match_expenses_account(test_desc.strip(), preview_rules)
    if matched:
        st.success(f"✅ 命中：{matched}")
    else:
        st.info("未命中任何规则，将回退到默认占位 `Expenses:TODO`。")

st.divider()

save_col1, save_col2 = st.columns([1, 2])
save_feedback_placeholder = st.empty()
save = st.button("💾 保存规则", use_container_width=True, type="primary")
st.caption(
    f"保存时会做校验：账户必须以 `Expenses:` 开头，且不能包含 `{BEANCOUNT_TODO_TOKEN}`。"
)

if save_feedback_placeholder is not None:
    show_flash("expenses_account_rules_flash", placeholder=save_feedback_placeholder)

if save:
    to_save: List[Dict[str, Any]] = []
    for rule in st.session_state.get("expenses_account_rules_editor") or []:
        account = str(rule.get("account", "") or "").strip()
        keywords = parse_keywords(str(rule.get("keywords_text", "") or ""))
        if not account and not keywords:
            # allow empty row as "draft"; just skip
            continue
        to_save.append({"account": account, "keywords": keywords})

    try:
        save_expenses_account_rules(to_save)
        _load_rules_into_session()
        set_flash(
            "expenses_account_rules_flash",
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
