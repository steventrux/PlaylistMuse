"""PlaylistMuse release identity shared by runtime integrations."""

APP_VERSION = "0.2.2"
REPOSITORY_URL = "https://github.com/steventrux/PlaylistMuse"
USER_AGENT = f"PlaylistMuse/{APP_VERSION} (+{REPOSITORY_URL})"
PLAYLIST_SIGNATURE = f"— Made with PlaylistMuse · {REPOSITORY_URL}"


def with_playlist_signature(description: str) -> str:
    """Append a discreet attribution line to a generated playlist's description.

    Idempotent: refinement and other flows that carry an existing description forward
    (rather than regenerating it) should not end up duplicating the line.
    """
    text = str(description or "").strip()
    if PLAYLIST_SIGNATURE in text:
        return text
    return f"{text}\n\n{PLAYLIST_SIGNATURE}" if text else PLAYLIST_SIGNATURE
