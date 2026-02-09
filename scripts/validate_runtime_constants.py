#!/usr/bin/env python3
from __future__ import annotations

import codecs
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from financemailparser.shared.constants import (  # noqa: E402
    ALIPAY_CSV_DEFAULTS,
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    DEFAULT_IMAP_SERVER,
    FALLBACK_ENCODINGS,
    WECHAT_CSV_DEFAULTS,
    CsvParseDefaults,
)


def _validate_csv_defaults(label: str, value: CsvParseDefaults) -> None:
    if not isinstance(value, CsvParseDefaults):
        raise ValueError(f"{label} 类型错误（应为 CsvParseDefaults）")

    if not isinstance(value.header_row, int) or value.header_row < 0:
        raise ValueError(f"{label}.header_row 必须是 int >= 0")

    if not isinstance(value.skip_footer, int) or value.skip_footer < 0:
        raise ValueError(f"{label}.skip_footer 必须是 int >= 0")

    if not isinstance(value.encoding, str) or not value.encoding.strip():
        raise ValueError(f"{label}.encoding 必须是非空字符串")
    codecs.lookup(value.encoding)


def validate_runtime_constants() -> None:
    if not isinstance(DEFAULT_IMAP_SERVER, str) or not DEFAULT_IMAP_SERVER.strip():
        raise ValueError("DEFAULT_IMAP_SERVER 必须是非空字符串")

    if (
        not isinstance(DEFAULT_DOWNLOAD_TIMEOUT_SECONDS, int)
        or DEFAULT_DOWNLOAD_TIMEOUT_SECONDS <= 0
    ):
        raise ValueError("DEFAULT_DOWNLOAD_TIMEOUT_SECONDS 必须是 int > 0")

    if not isinstance(FALLBACK_ENCODINGS, tuple) or not FALLBACK_ENCODINGS:
        raise ValueError("FALLBACK_ENCODINGS 必须是非空 tuple")

    if len(set(FALLBACK_ENCODINGS)) != len(FALLBACK_ENCODINGS):
        raise ValueError("FALLBACK_ENCODINGS 包含重复项")

    for enc in FALLBACK_ENCODINGS:
        if not isinstance(enc, str) or not enc.strip():
            raise ValueError(f"FALLBACK_ENCODINGS 包含非法项：{enc!r}")
        codecs.lookup(enc)

    _validate_csv_defaults("ALIPAY_CSV_DEFAULTS", ALIPAY_CSV_DEFAULTS)
    _validate_csv_defaults("WECHAT_CSV_DEFAULTS", WECHAT_CSV_DEFAULTS)


def main() -> int:
    try:
        validate_runtime_constants()
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
