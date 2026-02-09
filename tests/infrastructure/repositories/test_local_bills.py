from __future__ import annotations

from pathlib import Path

from financemailparser.infrastructure.repositories.local_bills import (
    read_bill_html_text,
    read_bill_metadata_json,
    scan_credit_card_bill_folders,
)
from financemailparser.shared.constants import (
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_credit_card_bill_folders_includes_only_valid_folders(
    tmp_path: Path,
) -> None:
    emails_dir = tmp_path / "emails"
    emails_dir.mkdir()

    valid = emails_dir / "20260101_valid"
    _touch(valid / EMAIL_METADATA_FILENAME, '{"subject":"x"}')
    _touch(valid / EMAIL_HTML_FILENAME, "<html></html>")

    missing_html = emails_dir / "20260102_missing_html"
    _touch(missing_html / EMAIL_METADATA_FILENAME, '{"subject":"x"}')

    missing_meta = emails_dir / "20260103_missing_meta"
    _touch(missing_meta / EMAIL_HTML_FILENAME, "<html></html>")

    (emails_dir / "alipay").mkdir()
    (emails_dir / "wechat").mkdir()
    (emails_dir / ".DS_Store").mkdir()
    _touch(emails_dir / "not-a-dir.txt", "x")

    out = scan_credit_card_bill_folders(emails_dir=emails_dir)
    assert out == [valid]


def test_read_bill_metadata_json_warns_and_returns_none_on_invalid_json(
    tmp_path: Path,
) -> None:
    meta = tmp_path / EMAIL_METADATA_FILENAME
    _touch(meta, "{invalid-json")

    warnings: list[str] = []
    out = read_bill_metadata_json(metadata_path=meta, on_warning=warnings.append)
    assert out is None
    assert warnings
    assert str(meta) in warnings[0]


def test_read_bill_html_text_warns_and_returns_none_on_missing_file(
    tmp_path: Path,
) -> None:
    html = tmp_path / "missing.html"
    warnings: list[str] = []
    out = read_bill_html_text(html_path=html, on_warning=warnings.append)
    assert out is None
    assert warnings
    assert str(html) in warnings[0]
