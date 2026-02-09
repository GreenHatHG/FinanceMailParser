from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from financemailparser.infrastructure.config.config_manager import ConfigManager
from financemailparser.infrastructure.config.secrets import (
    MASTER_PASSWORD_ENV,
    is_encrypted_value,
)
from financemailparser.infrastructure.data_source.qq_email.config import (
    QQEmailConfigManager,
)
from financemailparser.infrastructure.data_source.qq_email.exceptions import LoginError


def test_save_and_load_config_strict_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    config_file = tmp_path / "config.yaml"
    cm = ConfigManager(config_path=config_file)
    mgr = QQEmailConfigManager(config_manager=cm)

    mgr.save_config(" a@qq.com ", " auth ")
    loaded = mgr.load_config_strict()
    assert loaded == {"email": "a@qq.com", "auth_code": "auth"}

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    saved = raw["email"]["qq"]
    assert saved["email"] == "a@qq.com"
    assert is_encrypted_value(saved["auth_code"]) is True


def test_config_present_vs_exists_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)

    assert mgr.config_present() is False
    assert mgr.config_exists() is False

    # Present is "file has values", regardless of decryptability.
    cm.set_value("email", "qq", {"email": "a@qq.com", "auth_code": "PLAINTEXT"})
    assert mgr.config_present() is True
    assert mgr.config_exists() is False


def test_load_config_lenient_returns_none_on_secret_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)

    cm.set_value("email", "qq", {"email": "a@qq.com", "auth_code": "PLAINTEXT"})
    assert mgr.load_config() is None


def test_load_config_strict_raises_for_missing_or_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)

    with pytest.raises(ValueError):
        mgr.load_config_strict()

    cm.set_value("email", "qq", {"email": "a@qq.com"})
    with pytest.raises(ValueError):
        mgr.load_config_strict()


def test_get_email_config_raises_actionable_error_on_secret_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MASTER_PASSWORD_ENV, "pw-1")
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)
    mgr.save_config("a@qq.com", "auth")

    monkeypatch.delenv(MASTER_PASSWORD_ENV, raising=False)
    with pytest.raises(ValueError) as exc:
        mgr.get_email_config()
    assert MASTER_PASSWORD_ENV in str(exc.value)


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        (LoginError("authentication failed"), "授权码错误"),
        (LoginError("nodename nor servname"), "网络连接失败"),
        (LoginError("protocol error"), "IMAP 服务未开启"),
        (LoginError("other"), "登录失败："),
    ],
)
def test_test_connection_maps_common_login_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, err: Exception, expected: str
) -> None:
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)

    class StubParser:
        def __init__(self, _email: str, _auth_code: str):
            pass

        def login(self) -> None:
            raise err

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "financemailparser.infrastructure.data_source.qq_email.config.QQEmailParser",
        StubParser,
    )

    ok, msg = mgr.test_connection("a@qq.com", "auth")
    assert ok is False
    assert expected in msg


def test_test_connection_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cm = ConfigManager(config_path=tmp_path / "config.yaml")
    mgr = QQEmailConfigManager(config_manager=cm)

    called: dict[str, int] = {"login": 0, "close": 0}

    class StubParser:
        def __init__(self, _email: str, _auth_code: str):
            pass

        def login(self) -> None:
            called["login"] += 1

        def close(self) -> None:
            called["close"] += 1

    monkeypatch.setattr(
        "financemailparser.infrastructure.data_source.qq_email.config.QQEmailParser",
        StubParser,
    )

    ok, msg = mgr.test_connection("a@qq.com", "auth")
    assert ok is True
    assert "连接成功" in msg
    assert called == {"login": 1, "close": 1}
