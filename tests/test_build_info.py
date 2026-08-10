from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.application import app
from backend.build_info import current_build_info
from backend.source_revision import git_revision


def test_build_info_defaults_to_dev_without_claiming_a_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_VERSION", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_CHANNEL", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_GIT_SHA", raising=False)
    monkeypatch.setenv("PLAYLISTMUSE_SOURCE_GIT_DIR", str(tmp_path / "missing-git"))

    info = current_build_info()

    assert info.version == "dev"
    assert info.channel == "dev"
    assert info.commit == ""
    assert info.display == "dev"


def test_dev_build_falls_back_to_checkout_revision(monkeypatch, tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    ref = git_dir / "refs" / "heads" / "dev"
    ref.parent.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    ref.write_text("608c2a458283c69b2196eb9ecc0e3676f505ed98\n", encoding="utf-8")

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "local")
    monkeypatch.setenv("PLAYLISTMUSE_SOURCE_GIT_DIR", str(git_dir))

    info = current_build_info()

    assert info.commit == "608c2a4"
    assert info.display == "dev · 608c2a4"


def test_explicit_build_revision_takes_precedence(monkeypatch, tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(
        "1111111111111111111111111111111111111111\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYLISTMUSE_SOURCE_GIT_DIR", str(git_dir))
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv(
        "PLAYLISTMUSE_GIT_SHA",
        "abcdef1234567890abcdef1234567890abcdef12",
    )

    info = current_build_info()

    assert info.commit == "abcdef1"
    assert info.display == "dev · abcdef1"


def test_build_info_keeps_stable_and_beta_labels_version_only(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.1.1")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "stable")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "abcdef1234567890")
    assert current_build_info().display == "v0.1.1"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-beta.1")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    assert current_build_info().display == "v0.2.0-beta.1"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "472c481f65da13876694f846708e2177981a7a7e")
    info = current_build_info()
    assert info.commit == "472c481"
    assert info.display == "v0.2.0-dev · 472c481"


def test_git_revision_supports_packed_refs(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "1234567890abcdef1234567890abcdef12345678 refs/heads/dev\n",
        encoding="utf-8",
    )

    assert git_revision(git_dir) == "1234567890abcdef1234567890abcdef12345678"


def test_version_endpoint_reports_running_build_metadata(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.3.0-beta.2")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "abcdef1234567890")

    response = TestClient(app).get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "version": "0.3.0-beta.2",
        "channel": "beta",
        "commit": "abcdef1",
        "display": "v0.3.0-beta.2",
        "repository_url": "https://github.com/steventrux/PlaylistMuse",
    }
