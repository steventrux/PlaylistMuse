from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    content = target.read_text(encoding="utf-8")
    if content.count(old) != 1:
        raise SystemExit(f"Unexpected source block in {path}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


replace_once(
    "backend/config.py",
    '''    if provider in {"openai", "anthropic"} and key.startswith("sk-or-"):
        return False
    return True
''',
    '''    return not (
        provider in {"openai", "anthropic"} and key.startswith("sk-or-")
    )
''',
)
replace_once(
    "backend/config.py",
    '        return {field_name: "" for field_name in PROFILE_FIELDS}\n',
    '        return dict.fromkeys(PROFILE_FIELDS, "")\n',
)
replace_once(
    "backend/constraint_interpreter.py",
    ').encode("utf-8")\n',
    ').encode()\n',
)
replace_once(
    "backend/lastfm.py",
    'from typing import Any, Callable\n',
    'from collections.abc import Callable\nfrom typing import Any\n',
)
replace_once(
    "backend/validation_fixes.py",
    'from typing import Any, Callable\n',
    'from collections.abc import Callable\nfrom typing import Any\n',
)
replace_once(
    "backend/lastfm_settings.py",
    '''        except ValueError:
            response.raise_for_status()
            raise ValueError("Last.fm returned an invalid validation response.")
''',
    '''        except ValueError as error:
            response.raise_for_status()
            raise ValueError(
                "Last.fm returned an invalid validation response."
            ) from error
''',
)
replace_once(
    "backend/metadata_validation.py",
    'import time\nfrom contextvars import ContextVar\n',
    'import time\nfrom contextlib import suppress\nfrom contextvars import ContextVar\n',
)
replace_once(
    "backend/metadata_validation.py",
    '''_ACTIVE_CONSTRAINTS: ContextVar[MetadataConstraints] = ContextVar(
    "playlistmuse_metadata_constraints",
    default=MetadataConstraints(),
)
''',
    '''_ACTIVE_CONSTRAINTS: ContextVar[MetadataConstraints | None] = ContextVar(
    "playlistmuse_metadata_constraints",
    default=None,
)
''',
)
replace_once(
    "backend/metadata_validation.py",
    '''def active_constraints() -> MetadataConstraints:
    return _ACTIVE_CONSTRAINTS.get()
''',
    '''def active_constraints() -> MetadataConstraints:
    return _ACTIVE_CONSTRAINTS.get() or MetadataConstraints()
''',
)
replace_once(
    "backend/metadata_validation.py",
    '''    return {
        key: legacy
        for key in (
            "allowed_artists",
            "excluded_artists",
            "allowed_albums",
            "excluded_albums",
            "release_year",
            "release_year_from",
            "release_year_to",
            "artist_country",
            "exception_tracks",
        )
    }
''',
    '''    return dict.fromkeys(
        (
            "allowed_artists",
            "excluded_artists",
            "allowed_albums",
            "excluded_albums",
            "release_year",
            "release_year_from",
            "release_year_to",
            "artist_country",
            "exception_tracks",
        ),
        legacy,
    )
''',
)
replace_once(
    "backend/metadata_validation.py",
    '''    if constraints.release_year_to is not None:
        if year is None or year > constraints.release_year_to:
            return constraints.release_year_to
''',
    '''    if (
        constraints.release_year_to is not None
        and (year is None or year > constraints.release_year_to)
    ):
        return constraints.release_year_to
''',
)
replace_once(
    "backend/metadata_validation.py",
    '''            try:
                _write_cache(metadata, ttl=ttl, path=cache_path)
            except sqlite3.Error:
                pass
''',
    '''            with suppress(sqlite3.Error):
                _write_cache(metadata, ttl=ttl, path=cache_path)
''',
)
replace_once(
    "backend/policy_enforcement.py",
    'runtime._RESOLVED_SESSION_TRACKS.set(tuple([*accepted, *selected]))',
    'runtime._RESOLVED_SESSION_TRACKS.set((*accepted, *selected))',
)
replace_once(
    "backend/selection_guard.py",
    'runtime._RESOLVED_SESSION_TRACKS.set(tuple([*before, *kept]))',
    'runtime._RESOLVED_SESSION_TRACKS.set((*before, *kept))',
)
replace_once(
    "backend/storage.py",
    'import json\nimport os\n',
    'import json\nimport os\nfrom contextlib import suppress\n',
)
replace_once(
    "backend/storage.py",
    '''    try:
        temporary.chmod(0o600)
    except OSError:
        pass
''',
    '''    with suppress(OSError):
        temporary.chmod(0o600)
''',
)
replace_once(
    "backend/storage.py",
    '''    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
''',
    '''    with suppress(OSError):
        path.unlink(missing_ok=True)
''',
)
replace_once(
    "backend/youtube.py",
    '''    if covers and (
        _COVER_RE.search(title_and_album) or _COVER_RE.search(normalized_artists)
    ):
        return True
    return False
''',
    '''    return bool(
        covers
        and (
            _COVER_RE.search(title_and_album)
            or _COVER_RE.search(normalized_artists)
        )
    )
''',
)
replace_once(
    "backend/youtube_publish.py",
    'import uuid\nfrom typing import Any\n',
    'import uuid\nfrom contextlib import suppress\nfrom typing import Any\n',
)
replace_once(
    "backend/youtube_publish.py",
    '''def _delete_quietly(client: httpx.Client, playlist_id: str) -> None:
    try:
        _request(client, "DELETE", "playlists", params={"id": playlist_id})
    except Exception:
        pass
''',
    '''def _delete_quietly(client: httpx.Client, playlist_id: str) -> None:
    with suppress(Exception):
        _request(client, "DELETE", "playlists", params={"id": playlist_id})
''',
)

ci_path = Path(".github/workflows/ci.yml")
ci = ci_path.read_text(encoding="utf-8")
old_lint = '      - name: Run Ruff\n        run: ruff check --select E4,E7,E9,F backend tests\n'
new_lint = '''      - name: Run Ruff
        run: |
          ruff check --select E4,E7,E9,F backend tests
          ruff check --select B,C4,SIM,UP backend
'''
if ci.count(old_lint) != 1:
    raise SystemExit("Unexpected CI Ruff step")
ci = ci.replace(old_lint, new_lint, 1)
checkout = '''      - name: Check out repository
        uses: actions/checkout@v4

      - name: Build image
'''
validated = '''      - name: Check out repository
        uses: actions/checkout@v4

      - name: Validate deployment configuration
        run: |
          cp .env.example .env
          docker compose -f docker-compose.yml config --quiet

      - name: Build image
'''
if ci.count(checkout) != 1:
    raise SystemExit("Unexpected container checkout block")
ci_path.write_text(ci.replace(checkout, validated, 1), encoding="utf-8")

Path(".github/workflows/tests.yml").unlink()

Path("tests/test_metadata_context_isolation.py").write_text(
    '''from __future__ import annotations

from contextvars import Context

from backend.metadata_validation import active_constraints


def test_default_metadata_constraints_are_not_shared_between_contexts() -> None:
    first = Context().run(active_constraints)
    first.allowed_artists.append("Example Artist")

    second = Context().run(active_constraints)

    assert second is not first
    assert second.allowed_artists == []
''',
    encoding="utf-8",
)
