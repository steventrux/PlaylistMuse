"""PlaylistMuse release identity shared by runtime integrations."""

APP_VERSION = "0.2.3"
REPOSITORY_URL = "https://github.com/steventrux/PlaylistMuse"
USER_AGENT = f"PlaylistMuse/{APP_VERSION} (+{REPOSITORY_URL})"
PLAYLIST_SIGNATURE = f"Made with PlaylistMuse · {REPOSITORY_URL}"

# YouTube Data API v3 caps playlists.snippet.description at 5000 characters; publishing
# a longer value fails the request. Keep well clear of that so the signature below is
# never the part that gets cut.
MAX_PLAYLIST_DESCRIPTION_LENGTH = 5000


def with_playlist_signature(description: str) -> str:
    """Append a discreet attribution line (with a link back to the project) to a
    generated playlist's description, trimming the description if needed so the
    signature always survives within YouTube's description length limit.

    Idempotent: refinement and other flows that carry an existing description forward
    (rather than regenerating it) should not end up duplicating the line.
    """
    text = str(description or "").strip()
    if PLAYLIST_SIGNATURE in text:
        return text

    if not text:
        return PLAYLIST_SIGNATURE

    separator = "\n\n"
    ellipsis = "…"
    budget = MAX_PLAYLIST_DESCRIPTION_LENGTH - len(separator) - len(PLAYLIST_SIGNATURE)
    if len(text) > budget:
        text = text[: budget - len(ellipsis)].rstrip()
        if " " in text:
            text = text.rsplit(" ", 1)[0]
        text = f"{text}{ellipsis}"

    return f"{text}{separator}{PLAYLIST_SIGNATURE}"
