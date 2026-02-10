"""
Streamlit page helpers for capturing logs and showing progress/log UI.

This module intentionally stays small and only covers patterns already used by
existing pages (e.g., download_bills.py and parse_bills.py). It is NOT a generic
"task runner" abstraction.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io
import logging
from typing import Any, Callable, Iterator, Optional

import streamlit as st


@contextmanager
def capture_root_logger(
    *,
    fmt: str,
    datefmt: str,
    handler_level: Optional[int] = None,
    redirect_stdio: bool = False,
) -> Iterator[io.StringIO]:
    """
    Capture root logger output into a StringIO and optionally redirect stdout/stderr.

    Notes:
    - We only attach a temporary handler; we do not modify global logging config.
    - We restore the root logger level as a conservative cleanup step.
    """
    log_stream = io.StringIO()
    log_handler = logging.StreamHandler(log_stream)
    log_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    if handler_level is not None:
        log_handler.setLevel(handler_level)

    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.addHandler(log_handler)

    stdio_ctx = (
        redirect_stdout(log_stream) if redirect_stdio else nullcontext()  # type: ignore[assignment]
    )
    stderr_ctx = redirect_stderr(log_stream) if redirect_stdio else nullcontext()

    try:
        with stdio_ctx, stderr_ctx:
            yield log_stream
    finally:
        root_logger.removeHandler(log_handler)
        root_logger.setLevel(original_level)


def make_progress_callback(
    progress_bar: Any,
    message_container: Any,
) -> Callable[[int, int, str], None]:
    def progress_callback(current: int, total: int, message: str) -> None:
        progress = 0.0 if total <= 0 else (current / total)
        progress_bar.progress(max(0.0, min(progress, 1.0)))
        message_container.text(message)

    return progress_callback


def render_log_expander(
    *,
    expander_title: str,
    log_text: str,
    expanded: bool,
    height: int,
    text_area_key: Optional[str] = None,
) -> None:
    if not log_text:
        return
    with st.expander(expander_title, expanded=expanded):
        kwargs: dict[str, Any] = {}
        if text_area_key is not None:
            kwargs["key"] = text_area_key
        st.text_area(
            "日志输出",
            value=log_text,
            height=height,
            disabled=True,
            **kwargs,
        )
