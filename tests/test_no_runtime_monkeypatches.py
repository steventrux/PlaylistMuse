from __future__ import annotations

import ast
from pathlib import Path

import backend

BACKEND_ROOT = Path(backend.__file__).resolve().parent


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def test_backend_does_not_patch_imported_modules_at_runtime() -> None:
    violations: list[str] = []

    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_names = _imported_names(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if function_name in {"setattr", "delattr"}:
                    violations.append(
                        f"{path.name}:{node.lineno} calls {function_name}"
                    )

            for target in _assignment_targets(node):
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in imported_names
                ):
                    violations.append(
                        f"{path.name}:{node.lineno} assigns "
                        f"{target.value.id}.{target.attr}"
                    )

    assert violations == []
