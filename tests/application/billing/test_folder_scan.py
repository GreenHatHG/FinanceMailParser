from __future__ import annotations

from pathlib import Path

from financemailparser.application.billing.folder_scan import (
    scan_downloaded_bill_folders,
)
from financemailparser.shared.constants import (
    EMAIL_HTML_FILENAME,
    EMAIL_METADATA_FILENAME,
)


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_downloaded_bill_folders_sorts_credit_cards_and_includes_wallet_dirs(
    tmp_path: Path,
) -> None:
    emails_dir = tmp_path / "emails"
    emails_dir.mkdir()

    b = emails_dir / "b"
    _touch(b / EMAIL_METADATA_FILENAME, '{"subject":"x"}')
    _touch(b / EMAIL_HTML_FILENAME, "<html></html>")

    a = emails_dir / "a"
    _touch(a / EMAIL_METADATA_FILENAME, '{"subject":"x"}')
    _touch(a / EMAIL_HTML_FILENAME, "<html></html>")

    (emails_dir / "alipay").mkdir()

    credit, digital = scan_downloaded_bill_folders(emails_dir)
    assert [p.name for p in credit] == ["a", "b"]
    assert [p.name for p in digital] == ["alipay"]
