"""
智能 Prompt 构建器 v2（ui_plan.md 2.7.5）

功能：
- 基于账户字典 + TF-IDF 匹配构建优化的 Prompt
- 分层结构：任务说明 → 账户字典 → Few-shot 示例 → 待处理交易
- 大幅减少 Prompt 大小（从 100KB+ 降至 10KB 以内）
"""

from __future__ import annotations

import textwrap
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass

from utils.beancount_validator import BeancountReconciler
from utils.account_extractor import extract_account_dict, format_account_dict_for_prompt
from utils.transaction_matcher import (
    TransactionMatcher,
    filter_transactions_with_accounts,
    extract_todo_transactions,
    format_transaction_for_prompt,
)


@dataclass
class PromptStats:
    """Prompt 统计信息"""

    total_chars: int  # 总字符数
    total_lines: int  # 总行数
    account_categories: int  # 可用账户总数
    todo_transactions: int  # 待处理交易数
    example_transactions: int  # 示例交易数
    historical_files: int  # 历史文件数
    match_quality_mean: float | None = None  # Top-1 相似度均值（0~1），用于衡量匹配质量


def build_smart_ai_prompt(
    latest_file_name: str,
    latest_file_content: str,
    reference_files: List[Tuple[str, str]],  # [(文件名, 内容), ...]
    examples_per_transaction: int = 3,
    account_definition_text: Optional[str] = None,
    extra_prompt: Optional[str] = None,
) -> Tuple[str, PromptStats]:
    """
    构建智能优化的 AI Prompt（v2 版本）。

    相比旧版 build_ai_prompt()：
    - 不发送完整历史文件，只发送相关示例
    - 添加账户字典，帮助 AI 理解可用账户
    - 使用 TF-IDF 匹配相似交易
    - Prompt 大小减少 85-90%

    Args:
        latest_file_name: 最新账单文件名
        latest_file_content: 最新账单内容
        reference_files: 历史账单文件列表
        examples_per_transaction: 每个 TODO 交易的示例数量
        account_definition_text: 可选的账户定义文件内容（包含 open 指令）
        extra_prompt: 可选的用户自定义指示

    Returns:
        (prompt, stats) 元组
    """
    latest_file_content = (latest_file_content or "").rstrip("\n")

    # 步骤 1: 解析所有文件的交易
    reconciler = BeancountReconciler()

    # 解析最新文件
    latest_transactions = reconciler.parse_transactions(latest_file_content)

    # 解析历史文件
    all_historical_transactions = []
    for _, content in reference_files:
        txns = reconciler.parse_transactions(content or "")
        all_historical_transactions.extend(txns)

    # 步骤 2: 提取账户字典
    # 优先使用账户定义文件，其次使用历史交易文件
    historical_texts = [content for _, content in reference_files]
    account_dict = extract_account_dict(
        beancount_texts=historical_texts,
        account_definition_text=account_definition_text,
    )
    account_dict_text = format_account_dict_for_prompt(account_dict)

    # 步骤 3: 分离 TODO 交易和已填充交易
    todo_transactions = extract_todo_transactions(latest_transactions)
    historical_with_accounts = filter_transactions_with_accounts(
        all_historical_transactions,
        exclude_todo=True,
    )

    # 步骤 4: 使用 TF-IDF 匹配相似交易
    matcher = TransactionMatcher(top_k=examples_per_transaction)
    match_results = matcher.find_similar_transactions(
        target_transactions=todo_transactions,
        historical_transactions=historical_with_accounts,
    )

    # Match quality: mean Top-1 cosine similarity for TODO transactions (0~1).
    match_quality_mean: float | None = None
    if match_results:
        top1_scores = [
            m.similarity_scores[0] for m in match_results if m.similarity_scores
        ]
        if top1_scores:
            match_quality_mean = sum(top1_scores) / len(top1_scores)

    # 步骤 5: 构建 Prompt
    prompt_parts = []

    # 第一部分：任务说明
    task_description = textwrap.dedent(
        """\
        # 任务说明
        你是一个专业的 Beancount 账本助手。请根据账户字典和参考示例，为待处理交易填充合适的账户名称。

        ## 要求
        1. 严格遵循 Beancount 账户命名规范
        2. 优先使用账户字典中已有的账户
        3. 参考示例中的分类逻辑和账户命名习惯
        4. 不要修改交易日期、金额、描述等其他字段
        5. 如果你看到形如 `__AMT_xxx_000001__` 的 token：这是金额脱敏占位符，必须保持完全不变（不要改动、不要拆分、不要增删），否则无法恢复真实金额
        6. 对于每个 TODO 账户，请参考下方提供的相似交易示例进行填充
        """
    ).strip()
    prompt_parts.append(task_description)
    prompt_parts.append("\n---\n")

    # 第二部分：用户自定义规则（如果有）
    if extra_prompt:
        prompt_parts.append("# 自定义规则\n\n")
        prompt_parts.append(extra_prompt)
        prompt_parts.append("\n\n---\n")

    # 第三部分：账户字典
    prompt_parts.append("# 第一部分：可用账户字典\n\n")
    if account_dict:
        prompt_parts.append(account_dict_text)
    else:
        prompt_parts.append("（暂无历史账户，请根据交易描述自行判断）")
    prompt_parts.append("\n\n---\n")

    # 第三部分：Few-shot 示例（为每个 TODO 交易展示相似示例）
    prompt_parts.append("# 第二部分：参考示例\n\n")

    if match_results:
        for idx, match in enumerate(match_results, 1):
            target_txn = match.target
            similar_txns = match.similar_transactions

            # 展示目标交易的描述
            prompt_parts.append(f'## 待处理交易 #{idx}: "{target_txn.description}"\n')
            prompt_parts.append("### 相似示例：\n\n")

            # 展示相似的历史交易
            for similar_txn in similar_txns:
                prompt_parts.append("```beancount\n")
                prompt_parts.append(format_transaction_for_prompt(similar_txn))
                prompt_parts.append("\n```\n\n")

            prompt_parts.append("\n")
    else:
        prompt_parts.append(
            "（本次未找到相似示例，请根据账户字典和交易描述自行判断）\n\n"
        )

    prompt_parts.append("---\n")

    # 第四部分：待处理交易
    prompt_parts.append("# 第三部分：待处理交易\n\n")
    prompt_parts.append(f"文件名：{latest_file_name}\n\n")
    prompt_parts.append("```beancount\n")
    prompt_parts.append(latest_file_content)
    prompt_parts.append("\n```\n\n")

    prompt_parts.append("---\n\n")
    prompt_parts.append("请开始处理，输出完整的 Beancount 文件。\n")

    # 合并所有部分
    prompt = "".join(prompt_parts)

    # 计算统计信息
    total_accounts = sum(len(accounts) for accounts in account_dict.values())
    stats = PromptStats(
        total_chars=len(prompt),
        total_lines=len(prompt.splitlines()),
        account_categories=total_accounts,
        todo_transactions=len(todo_transactions),
        example_transactions=sum(len(m.similar_transactions) for m in match_results),
        historical_files=len(reference_files),
        match_quality_mean=match_quality_mean,
    )

    return prompt, stats


def calculate_prompt_stats_v2(
    prompt: str, stats: Optional[PromptStats] = None
) -> Dict[str, Any]:
    """
    计算 Prompt 统计信息（兼容旧版接口）。

    Args:
        prompt: Prompt 文本
        stats: 可选的详细统计信息

    Returns:
        统计信息字典
    """
    result: Dict[str, Any] = {
        "chars": len(prompt),
        "lines": len(prompt.splitlines()),
        "files": int(prompt.count("文件名：")),
    }

    if stats:
        result.update(
            {
                "account_categories": stats.account_categories,
                "todo_transactions": stats.todo_transactions,
                "example_transactions": stats.example_transactions,
                "historical_files": stats.historical_files,
                "match_quality_mean": float(stats.match_quality_mean)
                if stats.match_quality_mean is not None
                else 0.0,
            }
        )

    return result
