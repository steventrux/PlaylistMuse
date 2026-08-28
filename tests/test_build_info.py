from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.build_info as build_info
from backend.application import app
from backend.build_info import current_build_info
from backend.source_revision import git_revision
from backend.version import (
    APP_VERSION,
    MAX_PLAYLIST_DESCRIPTION_LENGTH,
    PLAYLIST_SIGNATURE,
    REPOSITORY_URL,
    USER_AGENT,
    with_playlist_signature,
)

ROOT = Path(__file__).resolve().parents[1]


def test_application_version_is_centralized() -> None:
    assert APP_VERSION == "0.4.0"
    assert app.version == APP_VERSION


def test_release_identity_is_centralized() -> None:
    assert REPOSITORY_URL == "https://github.com/steventrux/PlaylistMuse"
    assert USER_AGENT == f"PlaylistMuse/{APP_VERSION} (+{REPOSITORY_URL})"


def test_playlist_signature_is_appended_once() -> None:
    signed = with_playlist_signature("A joyful power-pop playlist.")
    assert signed == f"A joyful power-pop playlist.\n\n{PLAYLIST_SIGNATURE}"

    # Idempotent: an already-signed description (e.g. carried forward by a refinement
    # flow) must not accumulate a second copy of the signature.
    assert with_playlist_signature(signed) == signed


def test_playlist_signature_includes_a_link_back_to_the_project() -> None:
    assert REPOSITORY_URL in PLAYLIST_SIGNATURE


def test_playlist_signature_handles_an_empty_description() -> None:
    assert with_playlist_signature("") == PLAYLIST_SIGNATURE
    assert with_playlist_signature("   ") == PLAYLIST_SIGNATURE


def test_playlist_signature_trims_an_overlong_description_instead_of_dropping_it() -> None:
    overlong = "x" * (MAX_PLAYLIST_DESCRIPTION_LENGTH + 500)

    signed = with_playlist_signature(overlong)

    assert len(signed) <= MAX_PLAYLIST_DESCRIPTION_LENGTH
    assert signed.endswith(f"\n\n{PLAYLIST_SIGNATURE}")
    body = signed[: -len(f"\n\n{PLAYLIST_SIGNATURE}")]
    assert body == "x" * (len(body) - 1) + "…"


def test_playlist_signature_trims_at_a_word_boundary() -> None:
    words = "supercalifragilisticexpialidocious " * 200
    overlong = words.strip()

    signed = with_playlist_signature(overlong)

    assert len(signed) <= MAX_PLAYLIST_DESCRIPTION_LENGTH
    assert signed.endswith(f"\n\n{PLAYLIST_SIGNATURE}")
    body = signed[: -len(f"\n\n{PLAYLIST_SIGNATURE}")]
    assert body.endswith("…")
    assert not body[:-1].endswith(" ")


def test_resolved_commit_sha_is_the_untruncated_source_for_running_commit(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "472c481f65da13876694f846708e2177981a7a7e")

    assert build_info._resolved_commit_sha() == "472c481f65da13876694f846708e2177981a7a7e"
    assert build_info._running_commit() == "472c481"


def test_build_info_defaults_to_dev_without_claiming_a_revision(monkeypatch) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_VERSION", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_CHANNEL", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_GIT_SHA", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_GIT_DIRTY", raising=False)
    monkeypatch.setattr(build_info, "_STARTUP_SOURCE_COMMIT", "")

    info = current_build_info()

    assert info.version == "dev"
    assert info.channel == "dev"
    assert info.commit == ""
    assert info.display == "dev"
    assert info.dirty is False


def test_stable_channel_uses_application_version_when_not_overridden(monkeypatch) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_VERSION", raising=False)
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "stable")
    monkeypatch.delenv("PLAYLISTMUSE_GIT_SHA", raising=False)
    monkeypatch.setattr(build_info, "_STARTUP_SOURCE_COMMIT", "")

    info = current_build_info()

    assert info.version == APP_VERSION
    assert info.channel == "stable"
    assert info.commit == ""
    assert info.display == f"v{APP_VERSION}"


def test_dev_build_falls_back_to_startup_checkout_revision(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "local")
    monkeypatch.setattr(
        build_info,
        "_STARTUP_SOURCE_COMMIT",
        "608c2a458283c69b2196eb9ecc0e3676f505ed98",
    )

    info = current_build_info()

    assert info.commit == "608c2a4"
    assert info.display == "dev · 608c2a4"


def test_explicit_build_revision_takes_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        build_info,
        "_STARTUP_SOURCE_COMMIT",
        "1111111111111111111111111111111111111111",
    )
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv(
        "PLAYLISTMUSE_GIT_SHA",
        "abcdef1234567890abcdef1234567890abcdef12",
    )

    info = current_build_info()

    assert info.commit == "abcdef1"
    assert info.display == "dev · abcdef1"


def test_dirty_build_is_flagged_and_labeled_local(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "local")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_DIRTY", "true")
    monkeypatch.setattr(
        build_info,
        "_STARTUP_SOURCE_COMMIT",
        "608c2a458283c69b2196eb9ecc0e3676f505ed98",
    )

    info = current_build_info()

    assert info.dirty is True
    assert info.commit == "608c2a4"
    assert info.display == "dev · 608c2a4 (local)"


def test_dirty_flag_accepts_common_truthy_spellings_only(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setattr(build_info, "_STARTUP_SOURCE_COMMIT", "")

    for truthy in ("true", "TRUE", "1", "yes"):
        monkeypatch.setenv("PLAYLISTMUSE_GIT_DIRTY", truthy)
        assert current_build_info().dirty is True

    for falsy in ("false", "0", "no", ""):
        monkeypatch.setenv("PLAYLISTMUSE_GIT_DIRTY", falsy)
        assert current_build_info().dirty is False


def test_build_info_keeps_stable_and_beta_labels_version_only(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", APP_VERSION)
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "stable")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "abcdef1234567890")
    assert current_build_info().display == f"v{APP_VERSION}"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-beta.1")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    assert current_build_info().display == "v0.2.0-beta.1"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "472c481f65da13876694f846708e2177981a7a7e")
    info = current_build_info()
    assert info.commit == "472c481"
    assert info.display == "v0.2.0-dev · 472c481"


def test_git_revision_supports_loose_and_packed_refs(tmp_path: Path) -> None:
    loose_git = tmp_path / "loose" / ".git"
    loose_ref = loose_git / "refs" / "heads" / "dev"
    loose_ref.parent.mkdir(parents=True)
    (loose_git / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    loose_ref.write_text(
        "608c2a458283c69b2196eb9ecc0e3676f505ed98\n",
        encoding="utf-8",
    )
    assert git_revision(loose_git) == "608c2a458283c69b2196eb9ecc0e3676f505ed98"

    packed_git = tmp_path / "packed" / ".git"
    packed_git.mkdir(parents=True)
    (packed_git / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    (packed_git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "1234567890abcdef1234567890abcdef12345678 refs/heads/dev\n",
        encoding="utf-8",
    )
    assert git_revision(packed_git) == "1234567890abcdef1234567890abcdef12345678"


def test_compose_exposes_only_checkout_head_and_refs_for_revision() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "PLAYLISTMUSE_SOURCE_GIT_DIR: /run/playlistmuse-source-git" in compose
    assert "./.git/HEAD:/run/playlistmuse-source-git/HEAD:ro" in compose
    assert "./.git/refs:/run/playlistmuse-source-git/refs:ro" in compose
    assert "./.git:/run/playlistmuse-source-git" not in compose


def test_compose_preserves_stable_defaults_and_allows_dev_isolation() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "${PLAYLISTMUSE_CONTAINER_NAME:-playlistmuse}" in compose
    assert '"${PLAYLISTMUSE_HOST_PORT:-5780}:5780"' in compose


def test_version_endpoint_reports_running_build_metadata(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.3.0-beta.2")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "abcdef1234567890")
    monkeypatch.delenv("PLAYLISTMUSE_GIT_DIRTY", raising=False)

    response = TestClient(app).get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "version": "0.3.0-beta.2",
        "channel": "beta",
        "commit": "abcdef1",
        "display": "v0.3.0-beta.2",
        "dirty": False,
        "repository_url": REPOSITORY_URL,
    }


def test_dockerfile_and_compose_wire_up_the_local_dirty_flag() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG PLAYLISTMUSE_GIT_DIRTY=false" in dockerfile
    assert "PLAYLISTMUSE_GIT_DIRTY=${PLAYLISTMUSE_GIT_DIRTY}" in dockerfile

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "PLAYLISTMUSE_GIT_DIRTY: ${PLAYLISTMUSE_GIT_DIRTY:-false}" in compose

    smoke_test = (ROOT / "scripts" / "vps-smoke-test.sh").read_text(encoding="utf-8")
    assert 'git status --porcelain -- backend frontend quality' in smoke_test
    assert 'PLAYLISTMUSE_GIT_DIRTY="$GIT_DIRTY"' in smoke_test
