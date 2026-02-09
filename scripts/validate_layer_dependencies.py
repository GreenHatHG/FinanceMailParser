#!/usr/bin/env python3
"""
Validate architectural layering via import rules.

This script is intended to run as a local pre-commit hook.
It checks imports under `src/financemailparser/` follow the intended dependency direction:
- interfaces -> application -> (infrastructure/domain/shared)
- infrastructure should not depend on application/interfaces
- domain should stay pure

Rules are intentionally conservative and project-specific.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


PACKAGE_IMPORT_PREFIX = "financemailparser"
PACKAGE_PATH_PARTS = ("src", "financemailparser")


INTERNAL_LAYERS = {
    "application",
    "domain",
    "infrastructure",
    "interfaces",
    "integrations",
    "shared",
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
    # UI/entry should not bypass use-cases to call infra directly.
    "interfaces": {"infrastructure"},
    # Use-cases should not depend on UI/entry.
    "application": {"interfaces"},
    # Infra should not depend on upper layers.
    "infrastructure": {"interfaces", "application"},
    # Domain should be pure.
    "domain": {
        "application",
        "infrastructure",
        "interfaces",
        "integrations",
        "shared",
    },
    # Shared helpers should avoid depending on upper/business orchestration.
    "shared": {"interfaces", "application", "infrastructure", "integrations"},
    # Integrations should not depend on UI or app orchestration.
    "integrations": {"interfaces", "application"},
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
    Determine the layer for a file based on `src/financemailparser/<layer>/...`.
    Returns None for files outside known layers.
    """
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except Exception:
        return None

    if len(rel.parts) < 3:
        return None

    if rel.parts[:2] != PACKAGE_PATH_PARTS:
        return None

    layer = rel.parts[2]
    if layer in INTERNAL_LAYERS:
        return layer
    return None


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    base = PROJECT_ROOT.joinpath(*PACKAGE_PATH_PARTS)
    if not base.exists():
        return []
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
    return module == PACKAGE_IMPORT_PREFIX or module.startswith(
        f"{PACKAGE_IMPORT_PREFIX}."
    )


def _imported_layer(module: str) -> str | None:
    """
    Extract layer from import path:
    - financemailparser.application.foo -> application
    """
    if not _is_internal_import(module):
        return None
    remainder = module[len(PACKAGE_IMPORT_PREFIX) :].lstrip(".")
    if not remainder:
        return None
    layer = remainder.split(".", 1)[0]
    if layer in INTERNAL_LAYERS:
        return layer
    return None


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

        imported_layer = _imported_layer(module)
        if not imported_layer:
            continue

        if imported_layer in forbidden_roots:
            violations.append(
                Violation(
                    path=path,
                    lineno=lineno,
                    layer=layer,
                    imported=module,
                    message=f"禁止依赖内部层：{imported_layer}",
                )
            )

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
            "建议：调整依赖方向（interfaces -> application -> infra/domain/shared）。",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
