from __future__ import annotations

from datetime import datetime

from financemailparser.domain.services.date_filter import (
    is_in_date_range,
    parse_date_safe,
)


def test_parse_date_safe_supports_default_formats_and_whitespace() -> None:
    assert parse_date_safe("2026-01-02") == datetime(2026, 1, 2)
    assert parse_date_safe("2026/01/03") == datetime(2026, 1, 3)
    assert parse_date_safe("20260104") == datetime(2026, 1, 4)
    assert parse_date_safe("  2026-01-05  ") == datetime(2026, 1, 5)


def test_parse_date_safe_returns_none_on_unparseable() -> None:
    assert parse_date_safe("") is None
    assert parse_date_safe("not-a-date") is None
    assert parse_date_safe("2026-13-40") is None


def test_is_in_date_range_inclusive_boundaries() -> None:
    start = datetime(2026, 1, 2)
    end = datetime(2026, 1, 3)

    assert is_in_date_range("2026-01-02", start, end) is True
    assert is_in_date_range("2026-01-03", start, end) is True
    assert is_in_date_range("2026-01-01", start, end) is False
    assert is_in_date_range("2026-01-04", start, end) is False


def test_is_in_date_range_returns_true_when_no_bounds() -> None:
    assert is_in_date_range("not-a-date", None, None) is True
    assert is_in_date_range("", None, None) is True


def test_is_in_date_range_unparseable_respects_keep_if_unparseable_flag() -> None:
    start = datetime(2026, 1, 2)
    end = datetime(2026, 1, 3)

    assert is_in_date_range("not-a-date", start, end, keep_if_unparseable=True) is True
    assert (
        is_in_date_range("not-a-date", start, end, keep_if_unparseable=False) is False
    )
