from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from financemailparser.domain.models.source import TransactionSource


def _normalize_aliases(raw_aliases: object) -> list[str]:
    if not isinstance(raw_aliases, list):
        return []

    aliases: list[str] = []
    for alias in raw_aliases:
        value = str(alias or "").strip()
        if value:
            aliases.append(value)
    return aliases


def build_bank_alias_keywords(
    bank_alias_rules: Mapping[str, Mapping[str, Any]] | None,
) -> Dict[str, list[str]]:
    normalized: Dict[str, list[str]] = {}
    for raw_code, rule in (bank_alias_rules or {}).items():
        code = str(raw_code or "").strip().upper()
        if not code or not isinstance(rule, Mapping):
            continue

        aliases = _normalize_aliases(rule.get("aliases"))
        if aliases:
            normalized[code] = aliases
    return normalized


def build_bank_display_names(
    bank_alias_rules: Mapping[str, Mapping[str, Any]] | None,
) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for raw_code, rule in (bank_alias_rules or {}).items():
        code = str(raw_code or "").strip().upper()
        if not code or not isinstance(rule, Mapping):
            continue

        display_name = str(rule.get("display_name", "") or "").strip()
        if display_name:
            normalized[code] = display_name
    return normalized


def find_bank_code_by_alias(
    text: str,
    *,
    bank_alias_keywords: Mapping[str, Sequence[str]] | None,
) -> Optional[str]:
    text_norm = str(text or "").lower()
    if not text_norm:
        return None

    for raw_code, aliases in (bank_alias_keywords or {}).items():
        code = str(raw_code or "").strip().upper()
        if not code:
            continue

        for alias in aliases or ():
            alias_norm = str(alias or "").strip().lower()
            if alias_norm and alias_norm in text_norm:
                return code
    return None


def find_transaction_source_by_alias(
    text: str,
    *,
    bank_alias_keywords: Mapping[str, Sequence[str]] | None,
) -> Optional[TransactionSource]:
    bank_code = find_bank_code_by_alias(text, bank_alias_keywords=bank_alias_keywords)
    if not bank_code:
        return None

    try:
        return TransactionSource[bank_code]
    except KeyError:
        return None
