from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stable_release_gate_reads_version_without_runtime_dependencies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "from backend.version import APP_VERSION" not in workflow
    assert 'Path("backend/version.py").read_text(encoding="utf-8")' in workflow
    assert "ast.parse" in workflow
    assert 'target.id == "APP_VERSION"' in workflow


def test_stable_release_requires_curated_notes_for_current_version() -> None:
    version_source = (ROOT / "backend" / "version.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "0.4.3"' in version_source

    notes = ROOT / ".github" / "release-notes" / "v0.4.3.md"
    assert notes.is_file()
    assert notes.read_text(encoding="utf-8").strip()
