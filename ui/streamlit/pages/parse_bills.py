"""
解析账单页面（ui_plan.md 2.6）

将本地已下载的账单（信用卡/微信/支付宝）解析并导出为 Beancount。
"""

from datetime import datetime, timedelta
import csv
import io
import json
import logging

import streamlit as st

from financemailparser.shared.constants import (
    DATE_FMT_COMPACT,
    DATE_FMT_ISO,
    EMAILS_DIR,
    TIME_FMT_HMS,
)
from financemailparser.application.billing.parse_export import (
    ParseExportDetails,
    ParseExportResult,
    ParseExportStats,
    parse_downloaded_bills_to_beancount,
)
from financemailparser.application.common.date_range import (
    calculate_date_range_for_quick_select,
    get_quick_select_options,
)
from financemailparser.application.billing.beancount_history import (
    count_transactions,
    get_beancount_file_content,
    list_beancount_history,
    remove_beancount_file,
)

from ui.streamlit.log_utils import (
    capture_root_logger,
    make_progress_callback,
    render_log_expander,
)


st.set_page_config(page_title="解析账单", page_icon="🧾", layout="wide")
st.title("🧾 解析账单")

if not EMAILS_DIR.exists():
    st.error("❌ 未找到 emails 目录，请先到「下载账单」页面下载账单。")
    st.stop()

st.caption("将本地已下载的账单（信用卡/微信/支付宝）解析并导出为 Beancount。")
st.caption("当前只支持导出 Beancount（账户为占位符，后续可做智能填充）。")
st.divider()


def _to_json_bytes(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _to_csv_bytes(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    fieldnames = sorted({k for r in rows for k in r.keys()})
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(
            {k: ("" if r.get(k) is None else str(r.get(k))) for k in fieldnames}
        )
    return buf.getvalue().encode("utf-8")


# UI is organized to match "下载账单" page: range -> advanced -> action -> result.
st.subheader("解析范围")
st.caption("按交易发生日期筛选（不是邮件发送时间）。")
selection_mode = st.radio(
    "选择方式",
    ["快捷选择", "自定义日期范围"],
    horizontal=True,
    label_visibility="collapsed",
)

start_date = None
end_date = None

if selection_mode == "快捷选择":
    quick_option = st.selectbox(
        "选择时间范围",
        get_quick_select_options(),
        label_visibility="collapsed",
    )
    try:
        start_date, end_date = calculate_date_range_for_quick_select(quick_option)
    except Exception as e:
        st.error(f"❌ 日期计算错误：{str(e)}")
else:
    col1, col2 = st.columns(2)
    with col1:
        start_date_input = st.date_input(
            "开始",
            value=datetime.now() - timedelta(days=30),
            help="按交易发生日期筛选（包含当天）",
            label_visibility="collapsed",
        )
    with col2:
        end_date_input = st.date_input(
            "结束",
            value=datetime.now(),
            help="结束日期（包含当天）",
            label_visibility="collapsed",
        )

    if start_date_input and end_date_input:
        if start_date_input > end_date_input:
            st.error("❌ 开始日期不能晚于结束日期")
        else:
            start_date = datetime.combine(start_date_input, datetime.min.time())
            end_date = datetime.combine(end_date_input, datetime.max.time())

if start_date and end_date:
    st.info(
        f"📅 将解析并筛选交易：{start_date.strftime(DATE_FMT_ISO)} 至 {end_date.strftime(DATE_FMT_ISO)}（包含起止日期）"
    )

with st.expander("高级设置", expanded=False):
    log_level = st.selectbox(
        "日志级别",
        ["INFO", "DEBUG"],
        index=0,
        help="如果你觉得“完整日志”不够多，切到 DEBUG 会看到更多细节；同时会捕获代码里的 print 输出。",
    )
    st.caption("去重（可选）")
    enable_cc_digital_dedup = st.checkbox(
        "信用卡与微信/支付宝去重",
        value=False,
        help="将信用卡交易与微信/支付宝中“信用卡支付”的重复交易合并，保留描述更详细的一条。",
        key="parse_enable_cc_digital_dedup",
    )
    enable_refund_dedup = st.checkbox(
        "退款配对去重",
        value=False,
        help="将同一来源、金额相同的一笔消费和一笔退款配对删除。退款日期必须等于或晚于消费日期；如果日期解析不出来，就不会配对删除。",
        key="parse_enable_refund_dedup",
    )

st.divider()
st.subheader("执行解析")
parse_button = st.button(
    "🚀 开始解析并导出 Beancount",
    disabled=not start_date or not end_date,
    width="stretch",
    type="primary",
)
st.caption("成功后优先展示摘要与下载；预览与完整日志默认折叠，可按需展开。")

if parse_button:
    with capture_root_logger(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt=TIME_FMT_HMS,
        handler_level=logging.DEBUG,
        redirect_stdio=True,
    ) as log_stream:
        try:
            with st.status("正在解析账单并生成 Beancount...", expanded=True) as status:
                progress_bar = st.progress(0.0)
                message_container = st.empty()
                progress_callback = make_progress_callback(
                    progress_bar, message_container
                )

                if start_date is None or end_date is None:
                    st.error("日期范围不能为空")
                    st.stop()
                    raise RuntimeError("Unreachable")  # For type checker

                result: ParseExportResult = parse_downloaded_bills_to_beancount(
                    start_date=start_date,
                    end_date=end_date,
                    log_level=log_level,
                    enable_cc_digital_dedup=enable_cc_digital_dedup,
                    enable_refund_dedup=enable_refund_dedup,
                    progress_callback=progress_callback,
                )

                stats: ParseExportStats = result["stats"]
                beancount_text: str = result["beancount_text"]
                output_path: str = result["output_path"]
                details: ParseExportDetails = result["details"]

                # 进度区收口：避免把“最终完成提示”与下面的成功提示重复展示
                message_container.empty()

                status.update(label="✅ 解析完成", state="complete")

                st.success(
                    f"完成：解析目录 {stats['folders_parsed']}/{stats['folders_total']}，"
                    f"共生成 {stats['txns_total']} 条交易"
                )

                if start_date and end_date:
                    download_name = (
                        str(result["output_file_name"] or "").strip()
                        or f"transactions_{start_date.strftime(DATE_FMT_COMPACT)}_{end_date.strftime(DATE_FMT_COMPACT)}.bean"
                    )
                    st.download_button(
                        label="⬇️ 下载 Beancount 文件",
                        data=beancount_text.encode("utf-8"),
                        file_name=download_name,
                        mime="text/plain",
                        width="stretch",
                    )

                if output_path:
                    st.caption("已写入文件：")
                    st.code(output_path)

                # ==================== 过滤链路（逐层） ====================
                skipped_by_keyword = int(stats["skipped_by_keyword"] or 0)
                skipped_by_amount = int(stats["skipped_by_amount"] or 0)
                txns_before_dedup = int(stats["txns_before_dedup"] or 0)
                parsed_total = (
                    txns_before_dedup + skipped_by_keyword + skipped_by_amount
                )
                after_keyword = parsed_total - skipped_by_keyword
                after_amount = after_keyword - skipped_by_amount

                st.markdown("##### 🔎 过滤链路（逐层）")
                if enable_cc_digital_dedup or enable_refund_dedup:
                    st.caption(
                        "顺序：解析得到 → 关键字过滤 → 金额区间过滤 → 去重 → 导出"
                    )
                    st.info(
                        f"解析得到 {parsed_total} 条 → "
                        f"关键字过滤剔除 {skipped_by_keyword} 条（剩 {after_keyword} 条） → "
                        f"金额区间过滤剔除 {skipped_by_amount} 条（剩 {after_amount} 条） → "
                        f"信用卡-微信/支付宝去重移除 {int(stats['cc_digital_removed'] or 0)} 条（剩 {int(stats['txns_after_cc_digital'] or 0)} 条） → "
                        f"退款配对去重移除 {int(stats['refund_pairs_removed'] or 0)} 条（剩 {int(stats['txns_after_refund'] or 0)} 条） → "
                        f"最终导出 {stats['txns_total']} 条"
                    )
                else:
                    st.caption("顺序：解析得到 → 关键字过滤 → 金额区间过滤 → 导出")
                    st.info(
                        f"解析得到 {parsed_total} 条 → "
                        f"关键字过滤剔除 {skipped_by_keyword} 条（剩 {after_keyword} 条） → "
                        f"金额区间过滤剔除 {skipped_by_amount} 条（剩 {after_amount} 条） → "
                        f"最终导出 {stats['txns_total']} 条"
                    )

                # ==================== 详情列表 ====================
                cc_removed_rows = list(details["cc_wechat_alipay_removed"] or [])
                refund_pair_rows = list(details["refund_pairs_removed"] or [])
                keyword_skipped_rows = list(details["keyword_skipped"] or [])
                amount_skipped_rows = list(details["amount_skipped"] or [])

                with st.expander(
                    f"1) 🚫 关键字过滤详情（剔除 {len(keyword_skipped_rows)} 条）",
                    expanded=False,
                ):
                    if not keyword_skipped_rows:
                        st.caption("本次未因关键字过滤剔除任何交易。")
                    else:
                        st.download_button(
                            label="⬇️ 下载关键字过滤详情（JSON）",
                            data=_to_json_bytes(
                                {
                                    "keyword_skipped": keyword_skipped_rows,
                                }
                            ),
                            file_name="keyword_skipped.json",
                            mime="application/json",
                            width="stretch",
                        )
                        st.caption("仅展示前 200 条，完整数据请下载 JSON/CSV。")
                        st.dataframe(
                            keyword_skipped_rows[:200],
                            width="stretch",
                            height=360,
                        )
                        st.download_button(
                            label="⬇️ 下载关键字过滤列表（CSV）",
                            data=_to_csv_bytes(keyword_skipped_rows),
                            file_name="keyword_skipped.csv",
                            mime="text/csv",
                            width="stretch",
                        )

                with st.expander(
                    f"2) 💰 金额区间过滤详情（剔除 {len(amount_skipped_rows)} 条）",
                    expanded=False,
                ):
                    if not amount_skipped_rows:
                        st.caption("本次未因金额区间过滤剔除任何交易。")
                    else:
                        st.caption("仅展示前 200 条，完整数据请下载 CSV。")
                        st.dataframe(
                            amount_skipped_rows[:200],
                            width="stretch",
                            height=360,
                        )
                        st.download_button(
                            label="⬇️ 下载金额区间过滤列表（CSV）",
                            data=_to_csv_bytes(amount_skipped_rows),
                            file_name="amount_skipped.csv",
                            mime="text/csv",
                            width="stretch",
                        )

                if enable_cc_digital_dedup or enable_refund_dedup:
                    with st.expander("3) 🧾 去重详情（本次解析）", expanded=False):
                        if not cc_removed_rows and not refund_pair_rows:
                            st.caption("本次未移除任何去重条目。")

                        st.markdown("##### 信用卡与微信/支付宝去重详细")
                        if not cc_removed_rows:
                            st.caption("本次未移除任何微信/支付宝重复交易。")
                        else:
                            st.caption("仅展示前 200 条，完整数据请下载 CSV。")
                            st.dataframe(
                                cc_removed_rows[:200],
                                width="stretch",
                                height=320,
                            )
                            st.download_button(
                                label="⬇️ 下载移除列表（CSV）",
                                data=_to_csv_bytes(cc_removed_rows),
                                file_name="cc_wechat_alipay_removed.csv",
                                mime="text/csv",
                                width="stretch",
                            )

                        st.markdown("##### 退款配对去重详细")
                        if not refund_pair_rows:
                            st.caption("本次未移除任何退款配对。")
                        else:
                            st.caption("仅展示前 200 条，完整数据请下载 CSV。")
                            st.dataframe(
                                refund_pair_rows[:200],
                                width="stretch",
                                height=360,
                            )
                            st.download_button(
                                label="⬇️ 下载退款配对列表（CSV）",
                                data=_to_csv_bytes(refund_pair_rows),
                                file_name="refund_pairs_removed.csv",
                                mime="text/csv",
                                width="stretch",
                            )

                with st.expander("预览", expanded=False):
                    preview = "\n".join(beancount_text.splitlines())
                    st.text_area(
                        "Beancount 预览", value=preview, height=650, disabled=True
                    )

                render_log_expander(
                    expander_title="📋 查看完整日志",
                    log_text=log_stream.getvalue(),
                    expanded=False,
                    height=450,
                )

        except Exception as e:
            st.error(f"❌ 解析失败：{str(e)}")
            render_log_expander(
                expander_title="📋 查看错误日志",
                log_text=log_stream.getvalue(),
                expanded=True,
                height=300,
            )

# ==================== 历史解析结果 ====================
st.divider()
st.subheader("📂 历史解析结果")
st.caption("以下是之前解析生成的 Beancount 文件，刷新页面后仍可查看和下载。")

history_items = list_beancount_history()

if not history_items:
    st.info("📭 暂无历史解析结果")
else:
    st.info(f"共 {len(history_items)} 个文件")

    for item in history_items:
        with st.expander(
            f"📄 {item.info.name}（{item.size_kb:.1f} KB · {item.modified_time_str}）"
        ):
            content = get_beancount_file_content(item.info.path)
            if content is None:
                st.error("读取文件内容失败")
                continue

            txn_count = count_transactions(content)
            st.caption(f"交易数约 {txn_count} 条 · 文件路径：{item.info.path}")

            col1, col2 = st.columns([1, 1])
            with col1:
                st.download_button(
                    label="⬇️ 下载",
                    data=content.encode("utf-8"),
                    file_name=item.info.name,
                    mime="text/plain",
                    key=f"download_{item.info.name}",
                )
            with col2:
                if st.button(
                    "🗑️ 删除",
                    key=f"delete_{item.info.name}",
                ):
                    if remove_beancount_file(item.info.path):
                        st.rerun()
                    else:
                        st.error("删除文件失败")

            st.text_area(
                "预览",
                value=content,
                height=400,
                disabled=True,
                key=f"preview_{item.info.name}",
                label_visibility="collapsed",
            )
