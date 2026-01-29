"""根据“最新账单 + 多份历史账单参考”构建用于 AI 处理的 Prompt 文本。"""

from __future__ import annotations

import textwrap
from typing import List, Tuple


def build_ai_prompt(
    latest_file_name: str,
    latest_file_content: str,
    reference_files: List[Tuple[str, str]],  # [(文件名, 内容), ...]
) -> str:
    """构建 AI 处理 Beancount 的 Prompt。"""
    latest_file_content = (latest_file_content or "").rstrip("\n")

    prompt = textwrap.dedent(
        """\
        # 任务说明
        你是一个专业的 Beancount 账本助手。请根据历史账单的记账习惯，为最新账单中的 `TODO` 占位账户填充合适的账户名称。

        ## 要求
        1. 严格遵循 Beancount 账户命名规范
        2. 参考历史账单中的账户命名习惯和分类逻辑
        3. 保持账户层级结构的一致性
        4. 不要修改交易日期、金额、描述等其他字段
        """
    ).strip("\n")

    prompt += "\n\n---\n\n"

    prompt += textwrap.dedent(
        f"""\
        # 最新账单（需要处理）
        文件名：{latest_file_name}

        ```beancount
        {latest_file_content}
        ```
        """
    ).strip("\n")

    prompt += "\n\n---\n\n"

    prompt += "# 历史账单（参考）"
    if not reference_files:
        prompt += "\n（本次未选择历史账单）"
    else:
        for file_name, file_content in reference_files:
            file_content = (file_content or "").rstrip("\n")
            prompt += "\n\n" + textwrap.dedent(
                f"""\
                文件名：{file_name}

                ```beancount
                {file_content}
                ```
                """
            ).strip("\n")

    prompt += "\n\n---\n\n请开始处理，输出完整的 Beancount 文件。\n"

    return prompt


def calculate_prompt_stats(prompt: str) -> dict:
    """计算 Prompt 统计信息：字符数、行数、文件数。"""
    prompt = prompt or ""
    return {
        "chars": len(prompt),
        "lines": len(prompt.splitlines()),
        "files": int(prompt.count("文件名：")),
    }
