"""
Hexagonal boundary: the core (domain, application, agents) must not import
infrastructure or the API layer. Adapters depend on the core, never the reverse.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CORE = Path(__file__).resolve().parents[3] / "src" / "truefit_core"
FORBIDDEN = ("truefit_infra", "truefit_api", "truefit_workers")


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_core_does_not_import_infra_api_or_workers():
    violations = [
        f"{path.relative_to(CORE.parent)} imports {mod}"
        for path in sorted(CORE.rglob("*.py"))
        for mod in sorted(_imports(path))
        if any(part in mod.split(".") for part in FORBIDDEN)
    ]
    assert violations == []


def test_the_guard_actually_scans_files():
    assert len(list(CORE.rglob("*.py"))) > 30
