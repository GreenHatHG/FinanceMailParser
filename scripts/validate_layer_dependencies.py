#!/usr/bin/env python3
"""
Validate architectural layering via import rules.

This script is intended to run as a local pre-commit hook.
It checks that imports follow the intended dependency direction, e.g.:
- ui -> app (services) -> (data_source, statement_parsers, config, utils, models, ai)
- lower layers must not import higher layers

Rules are intentionally conservative and project-specific.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


INTERNAL_ROOTS = {
    "ui",
    "app",
    "data_source",
    "statement_parsers",
    "config",
    "ai",
    "utils",
    "models",
}


SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".ace-tool",
    "emails",
    "outputs",
}


LAYER_FORBIDDEN_ROOTS: dict[str, set[str]] = {
    # UI should only depend on app/services (+ ui helpers + utils/models/constants).
    "ui": {"config", "data_source", "statement_parsers", "ai"},
    # App services orchestrate, but should not depend on UI.
    "app": {"ui"},
    # Data access layer should not import app/ui or parsers.
    "data_source": {"ui", "app", "statement_parsers"},
    # Parsers should be pure (no app/ui/data_source/config/ai).
    "statement_parsers": {"ui", "app", "data_source", "config", "ai"},
    # Config layer should not depend on higher/business layers.
    "config": {"ui", "app", "data_source", "statement_parsers", "ai"},
    # AI module should not depend on UI.
    "ai": {"ui"},
    # Generic modules should not depend on app/ui.
    "utils": {"ui", "app"},
    # Models should be pure and not depend on other internal modules.
    "models": {
        "ui",
        "app",
        "data_source",
        "statement_parsers",
        "config",
        "ai",
        "utils",
    },
}


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    layer: str
    imported: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.lineno}: [{self.layer}] {self.message} ({self.imported!r})"


def _should_skip_path(path: Path) -> bool:
    return any(part in SKIP_DIR_PARTS for part in path.parts)


def _detect_layer(path: Path) -> str | None:
    """
    Determine the 'layer' for a file based on its top-level directory.
    Returns None for files outside known layers.
    """
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except Exception:
        return None

    if not rel.parts:
        return None

    root = rel.parts[0]
    if root in INTERNAL_ROOTS:
        return root
    return None


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for layer_root in sorted(INTERNAL_ROOTS):
        base = PROJECT_ROOT / layer_root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if _should_skip_path(path):
                continue
            files.append(path)
    return sorted(files)


def _extract_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """
    Return a list of (lineno, module) for absolute imports.
    - `import x.y` -> "x.y"
    - `from x.y import z` -> "x.y"
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = str(alias.name or "")
                if name:
                    found.append((int(node.lineno), name))
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports; they are within a package.
            if node.level and node.level > 0:
                continue
            module = str(node.module or "")
            if module:
                found.append((int(node.lineno), module))
            else:
                # `from . import x` is relative (handled above). For safety, ignore.
                continue
    return found


def _is_internal_import(module: str) -> bool:
    root = module.split(".", 1)[0]
    return root in INTERNAL_ROOTS


def _check_file(path: Path) -> list[Violation]:
    layer = _detect_layer(path)
    if not layer:
        return []

    forbidden_roots = LAYER_FORBIDDEN_ROOTS.get(layer, set())
    if not forbidden_roots:
        return []

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        return [
            Violation(
                path=path,
                lineno=0,
                layer=layer,
                imported="",
                message=f"读取失败：{e}",
            )
        ]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        lineno = int(getattr(e, "lineno", 0) or 0)
        return [
            Violation(
                path=path,
                lineno=lineno,
                layer=layer,
                imported="",
                message=f"语法错误：{e}",
            )
        ]

    violations: list[Violation] = []
    for lineno, module in _extract_imports(tree):
        if not _is_internal_import(module):
            continue

        root = module.split(".", 1)[0]
        if root in forbidden_roots:
            violations.append(
                Violation(
                    path=path,
                    lineno=lineno,
                    layer=layer,
                    imported=module,
                    message=f"禁止依赖内部层：{root}",
                )
            )
            continue

        # Extra strictness: block ui -> ai.config even if 'ai' rule changes later.
        if layer == "ui" and module == "ai.config":
            violations.append(
                Violation(
                    path=path,
                    lineno=lineno,
                    layer=layer,
                    imported=module,
                    message="禁止直接依赖 ai.config（请通过 app/services 门面）",
                )
            )

        # Block `from ai import config` explicitly (still reaching ai.config).
        if layer == "ui" and module == "ai":
            # If it imports 'ai' in ui, it is already forbidden by root rule.
            # Keep this branch for clarity if rules are relaxed in the future.
            pass

    return violations


def main() -> int:
    violations: list[Violation] = []
    for path in _iter_python_files():
        violations.extend(_check_file(path))

    if violations:
        print("ERROR: 分层依赖校验失败：检测到不允许的跨层 import。", file=sys.stderr)
        for v in violations:
            print(f"- {v.format()}", file=sys.stderr)
        print(
            "建议：调整依赖方向（上层依赖下层），或将胶水逻辑上移到 app/services。",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
