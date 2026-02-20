from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from financemailparser.infrastructure.config import config_manager as cm
from financemailparser.infrastructure.config.config_manager import get_config_manager
from financemailparser.infrastructure.config.ui_state import (
    UiStateError,
    clear_ai_process_beancount_account_definition_path,
    clear_ai_process_beancount_history_paths,
    get_ai_process_beancount_ui_state,
    save_ai_process_beancount_account_definition_path,
    save_ai_process_beancount_history_paths,
)


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _set_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(cm, "CONFIG_FILE", config_file)
    get_config_manager.cache_clear()
    return config_file


def test_get_ai_process_beancount_ui_state_defaults_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_config_file(tmp_path, monkeypatch)
    out = get_ai_process_beancount_ui_state()
    assert out["history_paths"] == []
    assert out["account_definition_path"] is None


def test_save_and_load_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = _set_config_file(tmp_path, monkeypatch)

    save_ai_process_beancount_history_paths(["  /a/b.bean  ", "", "/c/d.bean"])
    save_ai_process_beancount_account_definition_path(" /x/y.bean ")

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert raw["ui_state"]["ai_process_beancount"]["version"] == 1
    assert raw["ui_state"]["ai_process_beancount"]["history_paths"] == [
        "/a/b.bean",
        "/c/d.bean",
    ]
    assert (
        raw["ui_state"]["ai_process_beancount"]["account_definition_path"]
        == "/x/y.bean"
    )

    loaded = get_ai_process_beancount_ui_state()
    assert loaded["history_paths"] == ["/a/b.bean", "/c/d.bean"]
    assert loaded["account_definition_path"] == "/x/y.bean"

    clear_ai_process_beancount_history_paths()
    clear_ai_process_beancount_account_definition_path()
    loaded2 = get_ai_process_beancount_ui_state()
    assert loaded2["history_paths"] == []
    assert loaded2["account_definition_path"] is None


def test_get_rejects_unsupported_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = _set_config_file(tmp_path, monkeypatch)
    _write_yaml(
        config_file,
        """
ui_state:
  ai_process_beancount:
    version: 2
""".lstrip(),
    )

    with pytest.raises(UiStateError) as exc:
        get_ai_process_beancount_ui_state()
    assert "version 不支持" in str(exc.value)


def test_get_rejects_bad_types(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = _set_config_file(tmp_path, monkeypatch)
    _write_yaml(
        config_file,
        """
ui_state:
  ai_process_beancount:
    version: 1
    history_paths: "/not-a-list"
""".lstrip(),
    )

    with pytest.raises(UiStateError) as exc:
        get_ai_process_beancount_ui_state()
    assert "history_paths" in str(exc.value)
