"""
UI helpers for showing one-time (flash) messages.

This module is used by multiple Streamlit pages to avoid duplicating the same
flash/session-state boilerplate.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def set_flash(key: str, *, level: str, message: str) -> None:
    """
    Store a one-time message in session_state.

    Args:
        key: session_state key, e.g. "expenses_account_rules_flash"
        level: "success" | "error" | "info"
        message: message to show on next rerun
    """
    st.session_state[key] = {"level": str(level or ""), "message": str(message or "")}


def show_flash(key: str, *, placeholder: Any) -> bool:
    """
    Pop and show a flash message using a placeholder.

    Args:
        key: session_state key, e.g. "expenses_account_rules_flash"
        placeholder: st.empty() result or any object supporting success/error/info

    Returns:
        True if a message was shown, otherwise False.
    """
    flash = st.session_state.pop(key, None)
    if not isinstance(flash, dict):
        return False

    if placeholder is None:
        return False

    level = str(flash.get("level", "") or "")
    message = str(flash.get("message", "") or "").strip()
    if not message:
        return False

    if level == "success":
        placeholder.success(message)
    elif level == "error":
        placeholder.error(message)
    else:
        placeholder.info(message)

    return True
