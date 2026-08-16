from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
STATIC_ASSET_RE = re.compile(r"/static/([A-Za-z0-9._/-]+)")
HTML_ENTRY_POINTS = (
    "index.html",
    "playlist.html",
    "library.html",
    "settings.html",
    "statistics.html",
    "statistics-nerd.html",
    "statistics-detail.html",
    "diagnostics.html",
)
REFERENCE_SOURCE_SUFFIXES = {".html", ".js", ".css"}
RUNTIME_ASSET_SUFFIXES = {".js", ".css", ".png", ".svg"}
BACKEND_ENTRYPOINTS = {"__init__", "application", "main"}
# These modules are intentionally parked after restoring the proven low-latency
# generation path. They remain covered by their focused tests but are not part of
# the active runtime graph.
PARKED_BACKEND_MODULES = {"reccobeats_runtime", "temporal_alias_guard"}

OBSOLETE_PATHS = (
    "backend/runtime_fixes.py",
    "frontend/ai-results-settings.js",
    "frontend/footer-compact.css",
    ".github/assets/playlistmuse-hero-dark.svg",
    ".github/assets/playlistmuse-hero-light.svg",
    ".github/assets/playlistmuse-hero.svg",
    ".github/assets/playlistmuse-logo-lockup.svg",
)


def _static_references(path: Path) -> set[str]:
    if path.suffix not in REFERENCE_SOURCE_SUFFIXES:
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
        if path.is_file() and path.suffix in REFERENCE_SOURCE_SUFFIXES:
            pending.extend(_static_references(path) - reachable)

    return reachable


def test_frontend_static_graph_has_no_missing_or_orphan_assets() -> None:
    reachable = _reachable_static_assets()
    missing = sorted(
        relative_name
        for relative_name in reachable
        if not (FRONTEND / relative_name).is_file()
    )
    assert not missing, f"Referenced frontend assets are missing: {', '.join(missing)}"

    runtime_assets = {
        path.name
        for path in FRONTEND.iterdir()
        if path.is_file() and path.suffix in RUNTIME_ASSET_SUFFIXES
    }
    orphaned = sorted(runtime_assets - reachable)
    assert not orphaned, f"Unreferenced frontend assets: {', '.join(orphaned)}"


def test_obsolete_compatibility_files_are_removed() -> None:
    leftovers = [relative for relative in OBSOLETE_PATHS if (ROOT / relative).exists()]
    assert leftovers == []


def test_old_release_user_agents_are_removed() -> None:
    stale = sorted(
        path.name
        for path in BACKEND.glob("*.py")
        if "PlaylistMuse/0.7" in path.read_text(encoding="utf-8")
    )
    assert stale == []


def test_legacy_lastfm_blending_helper_is_removed() -> None:
    main_source = (BACKEND / "main.py").read_text(encoding="utf-8")

    assert "def _blend_candidates(" not in main_source
    assert "Legacy bounded blending helper" not in main_source


def _runtime_backend_imports() -> set[str]:
    imported: set[str] = set()
    for path in BACKEND.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend."):
                        imported.add(alias.name.split(".", 1)[1].split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("backend."):
                    imported.add(module.split(".", 1)[1].split(".", 1)[0])
                elif module == "backend":
                    imported.update(alias.name for alias in node.names if alias.name != "*")
    return imported


def test_backend_modules_are_reachable_from_runtime_code() -> None:
    imported = _runtime_backend_imports()
    orphaned = sorted(
        path.name
        for path in BACKEND.glob("*.py")
        if path.stem not in BACKEND_ENTRYPOINTS
        and path.stem not in PARKED_BACKEND_MODULES
        and path.stem not in imported
    )
    assert orphaned == []


def test_readme_uses_current_frontend_brand_asset() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "frontend/playlistmuse-banner.svg" in readme
    assert not (ROOT / ".github" / "assets").exists()
