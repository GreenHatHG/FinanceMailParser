"""
交易匹配工具（ui_plan.md 2.7.5）

功能：
- 使用 TF-IDF + 余弦相似度匹配相似交易
- 为每个 TODO 交易找到最相似的历史交易
- 支持智能示例选择
"""

from __future__ import annotations

from typing import List
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from utils.beancount_validator import BeancountTransaction


@dataclass
class MatchResult:
    """匹配结果数据类"""

    target: BeancountTransaction  # 目标交易（TODO）
    similar_transactions: List[BeancountTransaction]  # 相似的历史交易
    similarity_scores: List[float]  # 相似度分数


class TransactionMatcher:
    """交易匹配器（基于 TF-IDF）"""

    def __init__(self, top_k: int = 3):
        """
        初始化匹配器。

        Args:
            top_k: 为每个目标交易返回的最相似交易数量
        """
        self.top_k = top_k
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            token_pattern=r"(?u)\b\w+\b",  # 支持中文分词
            max_features=1000,
        )

    def find_similar_transactions(
        self,
        target_transactions: List[BeancountTransaction],
        historical_transactions: List[BeancountTransaction],
    ) -> List[MatchResult]:
        """
        为每个目标交易找到最相似的历史交易。

        Args:
            target_transactions: 目标交易列表（待填充账户的交易）
            historical_transactions: 历史交易列表（已填充账户的交易）

        Returns:
            匹配结果列表
        """
        if not target_transactions or not historical_transactions:
            return []

        # 提取交易描述
        target_descriptions = [txn.description for txn in target_transactions]
        historical_descriptions = [txn.description for txn in historical_transactions]

        # 合并所有描述用于 TF-IDF 拟合
        all_descriptions = target_descriptions + historical_descriptions

        # TF-IDF 向量化
        try:
            tfidf_matrix = self.vectorizer.fit_transform(all_descriptions)
        except ValueError:
            # 如果所有描述都为空或无效，返回空结果
            return []

        # 分离目标和历史的向量
        target_vectors = tfidf_matrix[: len(target_transactions)]
        historical_vectors = tfidf_matrix[len(target_transactions) :]

        # 计算余弦相似度
        similarities = cosine_similarity(target_vectors, historical_vectors)

        # 为每个目标交易找到最相似的历史交易
        results: List[MatchResult] = []

        for i, target_txn in enumerate(target_transactions):
            # 获取当前目标交易与所有历史交易的相似度
            similarity_scores = similarities[i]

            # 获取 top_k 个最相似的索引
            top_indices = np.argsort(similarity_scores)[-self.top_k :][::-1]

            # 提取对应的历史交易和分数
            similar_txns = [historical_transactions[idx] for idx in top_indices]
            scores = [float(similarity_scores[idx]) for idx in top_indices]

            results.append(
                MatchResult(
                    target=target_txn,
                    similar_transactions=similar_txns,
                    similarity_scores=scores,
                )
            )

        return results


def filter_transactions_with_accounts(
    transactions: List[BeancountTransaction],
    exclude_todo: bool = True,
) -> List[BeancountTransaction]:
    """
    过滤交易，只保留已填充账户的交易。

    Args:
        transactions: 交易列表
        exclude_todo: 是否排除包含 TODO 账户的交易

    Returns:
        过滤后的交易列表
    """
    filtered: List[BeancountTransaction] = []

    for txn in transactions:
        if exclude_todo:
            # 检查是否包含 TODO 账户
            has_todo = any("TODO" in account.upper() for account in txn.accounts)
            if has_todo:
                continue

        # 确保至少有一个 Expenses 账户
        has_expense = any(account.startswith("Expenses:") for account in txn.accounts)
        if has_expense:
            filtered.append(txn)

    return filtered


def extract_todo_transactions(
    transactions: List[BeancountTransaction],
) -> List[BeancountTransaction]:
    """
    提取包含 TODO 账户的交易。

    Args:
        transactions: 交易列表

    Returns:
        包含 TODO 的交易列表
    """
    todo_txns: List[BeancountTransaction] = []

    for txn in transactions:
        # 检查是否包含 TODO 账户
        has_todo = any("TODO" in account.upper() for account in txn.accounts)
        if has_todo:
            todo_txns.append(txn)

    return todo_txns


def format_transaction_for_prompt(txn: BeancountTransaction) -> str:
    """
    将交易格式化为 Beancount 文本（用于 Prompt）。

    Args:
        txn: 交易对象

    Returns:
        Beancount 格式的文本
    """
    lines = [f'{txn.date} * "{txn.description}" ""']

    # 添加账户和金额行
    for account, amount in zip(txn.accounts, txn.amounts):
        lines.append(f"  {account}  {amount}")

    return "\n".join(lines)
