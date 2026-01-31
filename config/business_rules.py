"""
业务规则加载器（系统规则）

说明：
- `business_rules.yaml` 用于保存“系统规则”（例如账单邮件识别关键词）
- `config.yaml` 用于保存“用户输入/用户偏好”（例如邮箱/AI 配置，以及阶段 4 的分类关键词）
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from constants import BUSINESS_RULES_FILE


class BusinessRulesError(Exception):
    """Business rules error with user-facing message in args[0]."""


def _validate_str_list(value: object, *, label: str) -> List[str]:
    if not isinstance(value, list):
        raise BusinessRulesError(f"{label} 必须是字符串列表")

    normalized: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BusinessRulesError(f"{label} 包含非法项：{item!r}")
        normalized.append(item.strip())

    if not normalized:
        raise BusinessRulesError(f"{label} 不能为空")

    return normalized


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise BusinessRulesError(f"未找到业务规则文件：{path}") from e
    except Exception as e:
        raise BusinessRulesError(f"读取业务规则文件失败：{path}（{e}）") from e

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise BusinessRulesError(f"业务规则 YAML 格式错误：{e}") from e

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise BusinessRulesError("业务规则文件根节点必须是 YAML mapping（dict）")

    return data


@lru_cache(maxsize=1)
def get_business_rules() -> Dict[str, Any]:
    """
    加载并校验 business_rules.yaml。

    Returns:
        业务规则字典（已做最小校验与归一化）。

    Note:
        - 如需在运行时重新加载，可调用 `get_business_rules.cache_clear()` 后再调用本函数。
    """
    data = _load_yaml(BUSINESS_RULES_FILE)

    version = data.get("version")
    if version != 1:
        raise BusinessRulesError(f"业务规则版本不支持：{version!r}（仅支持 1）")

    email_subject_keywords = data.get("email_subject_keywords")
    if not isinstance(email_subject_keywords, dict):
        raise BusinessRulesError("缺少 email_subject_keywords 或类型错误（应为 dict）")

    normalized_email_subject_keywords = {
        "credit_card": _validate_str_list(
            email_subject_keywords.get("credit_card"),
            label="email_subject_keywords.credit_card",
        ),
        "alipay": _validate_str_list(
            email_subject_keywords.get("alipay"),
            label="email_subject_keywords.alipay",
        ),
        "wechat": _validate_str_list(
            email_subject_keywords.get("wechat"),
            label="email_subject_keywords.wechat",
        ),
    }

    data["email_subject_keywords"] = normalized_email_subject_keywords
    return data


def get_email_subject_keywords() -> Dict[str, List[str]]:
    """
    获取账单邮件识别关键词（按 bill_type 分组）。

    Returns:
        dict: {"credit_card": [...], "alipay": [...], "wechat": [...]}
    """
    rules = get_business_rules()
    return rules["email_subject_keywords"]
