from __future__ import annotations

from typing import Literal

DigitalBillStatus = Literal[
    "downloaded",
    "skipped_existing_csv",
    "extracted_existing_zip",
    "failed_extract_existing_zip",
    "not_found",
    "missing_password",
    "failed",
    "unknown",
]

# App/services <-> UI status tokens for digital-bill download flow.
DIGITAL_BILL_STATUS_DOWNLOADED: DigitalBillStatus = "downloaded"
DIGITAL_BILL_STATUS_SKIPPED_EXISTING_CSV: DigitalBillStatus = "skipped_existing_csv"
DIGITAL_BILL_STATUS_EXTRACTED_EXISTING_ZIP: DigitalBillStatus = "extracted_existing_zip"
DIGITAL_BILL_STATUS_FAILED_EXTRACT_EXISTING_ZIP: DigitalBillStatus = (
    "failed_extract_existing_zip"
)
DIGITAL_BILL_STATUS_NOT_FOUND: DigitalBillStatus = "not_found"
DIGITAL_BILL_STATUS_MISSING_PASSWORD: DigitalBillStatus = "missing_password"
DIGITAL_BILL_STATUS_FAILED: DigitalBillStatus = "failed"
DIGITAL_BILL_STATUS_UNKNOWN: DigitalBillStatus = "unknown"
