from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
STATIC_ASSET_RE = re.compile(r"/static/([A-Za-z0-9._/-]+)")
HTML_ENTRY_POINTS = ("index.html", "playlist.html", "library.html", "settings.html")
CODE_SUFFIXES = {".js", ".css"}


def _static_references(path: Path) -> set[str]:
    if path.suffix not in {".html", ".js", ".css"}:
        return set()
    text = path.read_text(encoding="utf-8")
    return set(STATIC_ASSET_RE.findall(text))


def _reachable_static_assets() -> set[str]:
    reachable: set[str] = set()
    pending: list[str] = []

    for entry_name in HTML_ENTRY_POINTS:
        pending.extend(_static_references(FRONTEND / entry_name))

    while pending:
        relative_name = pending.pop()
        if relative_name in reachable:
            continue
        reachable.add(relative_name)
        path = FRONTEND / relative_name
        if path.is_file() and path.suffix in CODE_SUFFIXES:
            pending.extend(_static_references(path) - reachable)

    return reachable


def test_frontend_has_no_orphan_code_assets() -> None:
    code_assets = {
        path.name
        for path in FRONTEND.iterdir()
        if path.is_file() and path.suffix in CODE_SUFFIXES
    }
    reachable = _reachable_static_assets()

    orphaned = sorted(code_assets - reachable)
    assert not orphaned, f"Unreferenced frontend code assets: {', '.join(orphaned)}"


def test_obsolete_compatibility_files_are_removed() -> None:
    assert not (ROOT / "backend" / "runtime_fixes.py").exists()
    assert not (FRONTEND / "ai-results-settings.js").exists()
    assert not (FRONTEND / "primary-navigation.css").exists()
    assert not (FRONTEND / "footer-compact.css").exists()


def test_readme_uses_current_frontend_brand_asset() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "frontend/playlistmuse-banner.svg" in readme
    assert not (ROOT / ".github" / "assets").exists()
