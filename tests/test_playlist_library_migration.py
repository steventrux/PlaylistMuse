from pathlib import Path


def test_library_migrates_legacy_session_playlist() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "frontend" / "library.js"
    ).read_text(encoding="utf-8")

    assert "async function migrateSessionPlaylist()" in script
    assert "playlist.library_id = record.id" in script
