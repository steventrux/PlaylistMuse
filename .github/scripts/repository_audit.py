from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".css", ".html", ".md", ".yml", ".yaml", ".txt", ".sh", ".json"}
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "data"}


def files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in SKIP_PARTS for part in path.parts)
    ]


def text_files(all_files: list[Path]) -> dict[Path, str]:
    values: dict[Path, str] = {}
    for path in all_files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            values[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            pass
    return values


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def report_duplicates(all_files: list[Path]) -> None:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in all_files:
        groups[hashlib.sha256(path.read_bytes()).hexdigest()].append(path)
    duplicates = [group for group in groups.values() if len(group) > 1]
    print("\n== BYTE-IDENTICAL FILES ==")
    if not duplicates:
        print("none")
    for group in sorted(duplicates, key=lambda items: (-len(items), rel(items[0]))):
        print(" | ".join(rel(path) for path in group))


def report_frontend_references(texts: dict[Path, str]) -> None:
    print("\n== FRONTEND FILE REFERENCE COUNTS ==")
    candidates = sorted((ROOT / "frontend").iterdir())
    all_text = "\n".join(texts.values())
    for path in candidates:
        if not path.is_file():
            continue
        name = path.name
        count = all_text.count(name)
        if count <= 1:  # Usually the only hit is a test or the file name in this audit output.
            print(f"{name}: {count}")


def imported_backend_modules(texts: dict[Path, str]) -> dict[str, set[str]]:
    incoming: dict[str, set[str]] = defaultdict(set)
    for path, content in texts.items():
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
            continue
        source = rel(path)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module == "backend":
                    incoming["__init__"].add(source)
                elif module.startswith("backend."):
                    incoming[module.split(".", 1)[1].split(".", 1)[0]].add(source)
    return incoming


def report_python_modules(texts: dict[Path, str]) -> None:
    incoming = imported_backend_modules(texts)
    print("\n== BACKEND MODULES WITH NO IN-REPO IMPORTS ==")
    for path in sorted((ROOT / "backend").glob("*.py")):
        module = path.stem
        if module in {"main", "__init__"}:
            continue
        if not incoming.get(module):
            print(rel(path))

    print("\n== BACKEND IMPORT CYCLES ==")
    graph: dict[str, set[str]] = defaultdict(set)
    modules = {path.stem for path in (ROOT / "backend").glob("*.py")}
    for path in (ROOT / "backend").glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        source = path.stem
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend."):
                target = node.module.split(".", 1)[1].split(".", 1)[0]
                if target in modules:
                    graph[source].add(target)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend."):
                        target = alias.name.split(".", 1)[1].split(".", 1)[0]
                        if target in modules:
                            graph[source].add(target)

    found: set[tuple[str, ...]] = set()
    def walk(start: str, node: str, path: list[str]) -> None:
        for target in graph.get(node, set()):
            if target == start and len(path) > 1:
                cycle = path[:]
                rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
                found.add(min(rotations))
            elif target not in path and len(path) < 12:
                walk(start, target, path + [target])
    for module in modules:
        walk(module, module, [module])
    if not found:
        print("none")
    for cycle in sorted(found):
        print(" -> ".join((*cycle, cycle[0])))


def report_large_code(texts: dict[Path, str]) -> None:
    print("\n== LARGE TEXT FILES (>= 20 KiB) ==")
    for path, content in sorted(texts.items(), key=lambda item: -len(item[1].encode())):
        size = len(content.encode())
        if size >= 20 * 1024:
            print(f"{rel(path)}: {size} bytes")

    print("\n== LONG PYTHON FUNCTIONS (>= 100 lines) ==")
    for path, content in texts.items():
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno:
                length = node.end_lineno - node.lineno + 1
                if length >= 100:
                    print(f"{rel(path)}:{node.lineno} {node.name}: {length} lines")


def report_markers(texts: dict[Path, str]) -> None:
    marker_re = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
    print("\n== TODO/FIXME/HACK/XXX ==")
    matches = []
    for path, content in texts.items():
        for line_no, line in enumerate(content.splitlines(), start=1):
            if marker_re.search(line):
                matches.append(f"{rel(path)}:{line_no}: {line.strip()[:180]}")
    print("none" if not matches else "\n".join(matches))


def report_missing_literal_paths(texts: dict[Path, str]) -> None:
    print("\n== REFERENCED REPOSITORY PATHS THAT DO NOT EXIST ==")
    patterns = (
        re.compile(r"(?<![\w/.-])((?:docker-compose|requirements)[\w.-]*\.(?:yml|yaml|txt))"),
        re.compile(r"(?<![\w/.-])((?:frontend|backend|scripts|tests)/[\w./-]+)"),
    )
    missing: set[str] = set()
    for path, content in texts.items():
        if path.parts[-3:-1] == (".github", "scripts"):
            continue
        for pattern in patterns:
            for match in pattern.finditer(content):
                value = match.group(1).rstrip(".,:;)'\"")
                if "*" in value or "{" in value:
                    continue
                target = ROOT / value
                if not target.exists():
                    missing.add(f"{rel(path)} -> {value}")
    print("none" if not missing else "\n".join(sorted(missing)))


def report_duplicate_html_ids(texts: dict[Path, str]) -> None:
    print("\n== DUPLICATE HTML IDS ==")
    any_duplicate = False
    for path, content in texts.items():
        if path.suffix != ".html":
            continue
        ids = re.findall(r'\bid="([^"]+)"', content)
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            any_duplicate = True
            print(f"{rel(path)}: {', '.join(duplicates)}")
    if not any_duplicate:
        print("none")


def main() -> None:
    all_files = files()
    texts = text_files(all_files)
    print(f"FILES={len(all_files)} TEXT_FILES={len(texts)}")
    report_duplicates(all_files)
    report_frontend_references(texts)
    report_python_modules(texts)
    report_large_code(texts)
    report_markers(texts)
    report_missing_literal_paths(texts)
    report_duplicate_html_ids(texts)


if __name__ == "__main__":
    main()
