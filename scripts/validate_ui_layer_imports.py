#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN_IMPORT_PREFIXES = (
    "config",
    "config.",
    "ai.config",
)


def _is_forbidden_import(module: str) -> bool:
    module = str(module or "")
    return module == "config" or module.startswith("config.") or module == "ai.config"


def _check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"{path}:0: 读取失败：{e}"]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        lineno = int(getattr(e, "lineno", 0) or 0)
        return [f"{path}:{lineno}: 语法错误：{e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = str(alias.name or "")
                if _is_forbidden_import(name) or any(
                    name.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES
                ):
                    errors.append(
                        f"{path}:{node.lineno}: 禁止在 UI 层直接 import：{name!r}"
                    )

        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue

            module = str(node.module or "")

            # `from config import ...` and `from config.xxx import ...`
            if module == "config" or module.startswith("config."):
                errors.append(
                    f"{path}:{node.lineno}: 禁止在 UI 层直接 import：from {module!r} ..."
                )
                continue

            # `from ai.config import ...`
            if module == "ai.config":
                errors.append(
                    f"{path}:{node.lineno}: 禁止在 UI 层直接 import：from {module!r} ..."
                )
                continue

            # `from ai import config` (still reaches ai.config directly)
            if module == "ai" and any(alias.name == "config" for alias in node.names):
                errors.append(
                    f"{path}:{node.lineno}: 禁止在 UI 层直接 import：from 'ai' import 'config'"
                )
                continue

    return errors


def main() -> int:
    ui_dir = PROJECT_ROOT / "ui"
    if not ui_dir.exists():
        print("ERROR: 未找到 ui/ 目录", file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in sorted(ui_dir.rglob("*.py")):
        # Skip cache or generated files.
        if "__pycache__" in path.parts:
            continue
        errors.extend(_check_file(path))

    if errors:
        print(
            "ERROR: UI 分层校验失败：检测到 UI 直接依赖 config/ai.config。",
            file=sys.stderr,
        )
        for msg in errors:
            print(f"- {msg}", file=sys.stderr)
        print(
            "建议：将相关逻辑移动到 app/services/*（例如 ui_config_facade）。",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
