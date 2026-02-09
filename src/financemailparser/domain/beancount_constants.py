"""
Beancount-related domain constants.

These constants carry business semantics (placeholders used by export/AI flows),
so they live in `domain/` to avoid `domain` depending on `shared`.
"""

from __future__ import annotations


BEANCOUNT_CURRENCY = "CNY"

# Placeholder token used across export/AI flows.
BEANCOUNT_TODO_TOKEN = "TODO"

# Default placeholder accounts used when exporting Beancount entries before AI fills real accounts.
BEANCOUNT_DEFAULT_ASSETS_ACCOUNT = f"Assets:{BEANCOUNT_TODO_TOKEN}"
BEANCOUNT_DEFAULT_EXPENSES_ACCOUNT = f"Expenses:{BEANCOUNT_TODO_TOKEN}"
BEANCOUNT_DEFAULT_INCOME_ACCOUNT = f"Income:{BEANCOUNT_TODO_TOKEN}"
