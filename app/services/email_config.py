"""
Email configuration application service (use-case layer).

This module provides a thin facade for UI pages so they don't import `data_source/*`
directly. The underlying implementation can evolve (e.g. multi-provider email),
while UI keeps calling stable service methods.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from data_source.qq_email import QQEmailConfigManager


class QQEmailConfigService:
    """
    Facade for QQ email config operations used by UI.

    Notes:
    - This is intentionally a small wrapper. It keeps UI-layer imports clean and
      concentrates provider-specific wiring in the app layer.
    """

    def __init__(self, manager: Optional[QQEmailConfigManager] = None) -> None:
        self._manager = manager or QQEmailConfigManager()

    def config_present(self) -> bool:
        return self._manager.config_present()

    def load_config_strict(self) -> Dict[str, str]:
        return self._manager.load_config_strict()

    def save_config(self, email: str, auth_code: str) -> None:
        self._manager.save_config(email, auth_code)

    def test_connection(self, email: str, auth_code: str) -> Tuple[bool, str]:
        return self._manager.test_connection(email, auth_code)

    def delete_config(self) -> bool:
        return self._manager.delete_config()
