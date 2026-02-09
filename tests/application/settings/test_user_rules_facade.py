from __future__ import annotations

import pytest

from financemailparser.application.common.facade_common import (
    map_secret_load_error_to_ui_state,
    mask_secret,
)
from financemailparser.application.settings import user_rules_facade as facade
from financemailparser.infrastructure.config.secrets import (
    MasterPasswordNotSetError,
    PlaintextSecretFoundError,
    SecretDecryptionError,
)
from financemailparser.infrastructure.config.user_rules import UserRulesError


def test_mask_secret_masks_short_values_fully() -> None:
    assert mask_secret("", head=2, tail=2) == ""
    assert mask_secret("a", head=2, tail=2) == "*"
    assert mask_secret("ab", head=2, tail=2) == "**"
    assert mask_secret("abcd", head=2, tail=2) == "****"


def test_mask_secret_masks_with_head_and_tail() -> None:
    assert mask_secret("abcdef", head=2, tail=2) == "ab***ef"
    assert mask_secret("abcdef", head=0, tail=2) == "***ef"
    assert mask_secret("abcdef", head=2, tail=0) == "ab***"


def test_map_secret_load_error_to_ui_state_maps_known_types() -> None:
    assert (
        map_secret_load_error_to_ui_state(MasterPasswordNotSetError("x"))[0]
        == "missing_master_password"
    )
    assert (
        map_secret_load_error_to_ui_state(PlaintextSecretFoundError("x"))[0]
        == "plaintext_secret"
    )
    assert (
        map_secret_load_error_to_ui_state(SecretDecryptionError("x"))[0]
        == "decrypt_failed"
    )
    assert map_secret_load_error_to_ui_state(RuntimeError("x"))[0] == "load_failed"


def test_get_transaction_filters_ui_snapshot_using_defaults_does_not_read_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filter_defaults",
        lambda: {"skip_keywords": ["k"], "amount_ranges": [{"gte": 0.0, "lte": 1.0}]},
    )
    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filters",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )

    snap = facade.get_transaction_filters_ui_snapshot(use_defaults=True)
    assert snap.state == "using_defaults"
    assert snap.filters["skip_keywords"] == ["k"]


def test_get_transaction_filters_ui_snapshot_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filter_defaults",
        lambda: {"skip_keywords": ["k"], "amount_ranges": [{"gte": 0.0, "lte": 1.0}]},
    )

    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filters",
        lambda: {"skip_keywords": ["u"], "amount_ranges": [{"gte": 9.0, "lte": 10.0}]},
    )
    ok = facade.get_transaction_filters_ui_snapshot()
    assert ok.state == "ok"
    assert ok.used_defaults is False

    def raise_user_error() -> object:
        raise UserRulesError("bad format")

    monkeypatch.setattr(facade.user_rules, "get_transaction_filters", raise_user_error)
    bad = facade.get_transaction_filters_ui_snapshot()
    assert bad.state == "format_error"
    assert bad.used_defaults is True
    assert bad.filters["skip_keywords"] == ["k"]
    assert "bad format" in bad.error_message

    def raise_unknown() -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(facade.user_rules, "get_transaction_filters", raise_unknown)
    failed = facade.get_transaction_filters_ui_snapshot()
    assert failed.state == "load_failed"
    assert failed.used_defaults is True
    assert failed.filters["skip_keywords"] == ["k"]
    assert "boom" in failed.error_message


def test_get_transaction_filters_ui_snapshot_states_when_defaults_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filter_defaults",
        lambda: (_ for _ in ()).throw(UserRulesError("bad defaults")),
    )
    snap = facade.get_transaction_filters_ui_snapshot()
    assert snap.state == "format_error"
    assert snap.filters["skip_keywords"] == []
    assert "bad defaults" in snap.error_message

    monkeypatch.setattr(
        facade.user_rules,
        "get_transaction_filter_defaults",
        lambda: (_ for _ in ()).throw(RuntimeError("load defaults failed")),
    )
    snap2 = facade.get_transaction_filters_ui_snapshot()
    assert snap2.state == "load_failed"
    assert snap2.filters["skip_keywords"] == []
    assert "load defaults failed" in snap2.error_message


def test_get_expenses_account_rules_ui_snapshot_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        facade.user_rules,
        "get_expenses_account_rules",
        lambda: [{"account": "Expenses:Food", "keywords": ["x"]}],
    )
    ok = facade.get_expenses_account_rules_ui_snapshot()
    assert ok.state == "ok"
    assert ok.rules and ok.used_defaults is False

    monkeypatch.setattr(
        facade.user_rules,
        "get_expenses_account_rules",
        lambda: (_ for _ in ()).throw(UserRulesError("bad")),
    )
    bad = facade.get_expenses_account_rules_ui_snapshot()
    assert bad.state == "format_error"
    assert bad.rules == []

    monkeypatch.setattr(
        facade.user_rules,
        "get_expenses_account_rules",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    failed = facade.get_expenses_account_rules_ui_snapshot()
    assert failed.state == "load_failed"
    assert failed.rules == []

    defaults = facade.get_expenses_account_rules_ui_snapshot(use_defaults=True)
    assert defaults.state == "using_defaults"
    assert defaults.rules == []


def test_save_action_results_wrap_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        facade.user_rules, "save_transaction_filters", lambda **_kw: None
    )
    ok = facade.save_transaction_filters_from_ui(skip_keywords=[], amount_ranges=[])
    assert ok.ok is True
    assert "已保存" in ok.message

    def raise_user_error(**_kw: object) -> None:
        raise UserRulesError("bad")

    monkeypatch.setattr(facade.user_rules, "save_transaction_filters", raise_user_error)
    bad = facade.save_transaction_filters_from_ui(skip_keywords=[], amount_ranges=[])
    assert bad.ok is False
    assert "保存失败" in bad.message

    monkeypatch.setattr(
        facade.user_rules,
        "save_expenses_account_rules",
        lambda _rules: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    failed = facade.save_expenses_account_rules_from_ui([])
    assert failed.ok is False
    assert "保存失败" in failed.message


def test_eval_helpers_forward_to_user_rules() -> None:
    matched_keyword, matched_amount = facade.eval_transaction_filter(
        description="hello world",
        amount=5.0,
        skip_keywords=["world"],
        amount_ranges=[{"gte": 0.0, "lte": 10.0}],
    )
    assert matched_keyword == "world"
    assert matched_amount is True

    assert (
        facade.eval_expenses_account(
            description="星巴克",
            rules=[{"account": "Expenses:Food:Cafe", "keywords": ["星巴克"]}],
        )
        == "Expenses:Food:Cafe"
    )
