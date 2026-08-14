"""Deterministic artist-origin constraints from explicit national-repertoire wording."""

from __future__ import annotations

import re

_CONTEXT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "IT": (
        re.compile(r"\bitalian\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+italian[oaie]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+italien(?:ne)?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+italian[oa]s?\b", re.I),
        re.compile(r"\bitalienisch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
    "FR": (
        re.compile(r"\bfrench\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+frances[ei]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+fran[cç]ais(?:e)?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+frances(?:a|as|es)?\b", re.I),
        re.compile(r"\bfranz[oö]sisch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
    "DE": (
        re.compile(r"\bgerman\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+tedesc[oaie]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+allemand(?:e)?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+aleman(?:a|as|es)?\b", re.I),
        re.compile(r"\bdeutsch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
    "ES": (
        re.compile(r"\bspanish\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+spagnol[oaie]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+espagnol(?:e)?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+espa[nñ]ol(?:a|as|es)?\b", re.I),
        re.compile(r"\bspanisch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
    "GB": (
        re.compile(r"\b(?:british|uk)\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+britannic[oaie]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+britannique?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+brit[aá]nic(?:o|a|os|as)\b", re.I),
        re.compile(r"\bbritisch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
    "US": (
        re.compile(r"\b(?:american|us)\s+(?:music|songs?|tracks?|artists?|singers?|bands?|repertoire)\b", re.I),
        re.compile(r"\b(?:musica|brani|canzoni|tracce|artisti|cantanti|gruppi)\s+american[oaie]\b", re.I),
        re.compile(r"\b(?:musique|chansons?|titres?|artistes?|chanteurs?|groupes?)\s+am[eé]ricain(?:e)?s?\b", re.I),
        re.compile(r"\b(?:m[uú]sica|canciones?|temas?|artistas?|cantantes?|grupos?)\s+estadounidenses?\b", re.I),
        re.compile(r"\bamerikanisch\w*\s+(?:musik|songs?|titel|k[uü]nstler|s[aä]nger|bands?|gruppen?)\b", re.I),
    ),
}

_FROM_COUNTRY_PATTERNS: dict[str, re.Pattern[str]] = {
    "IT": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dall['’]?|da|de|d['’]|aus)\s+(?:italy|italia|italie|italien)\b", re.I),
    "FR": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dall['’]?|da|de|d['’]|aus)\s+(?:france|francia|frankreich)\b", re.I),
    "DE": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dall['’]?|da|de|d['’]|aus)\s+(?:germany|germania|allemagne|deutschland|alemania)\b", re.I),
    "ES": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dall['’]?|da|de|d['’]|aus)\s+(?:spain|spagna|espagne|espa[nñ]a|spanien)\b", re.I),
    "GB": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dal|dalla|de|du|aus)\s+(?:the\s+)?(?:uk|united kingdom|regno unito|royaume[- ]uni|reino unido|vereinigte(?:n|s)? k[oö]nigreich)\b", re.I),
    "US": re.compile(r"\b(?:artists?|singers?|bands?|artisti|cantanti|gruppi|artistes?|chanteurs?|groupes?|artistas?|cantantes?|grupos?|k[uü]nstler|s[aä]nger|bands?|gruppen?)\s+(?:from|dagli|dai|des|de|aus)\s+(?:the\s+)?(?:us|usa|united states|stati uniti|[eé]tats[- ]unis|estados unidos|vereinigte(?:n|s)? staaten)\b", re.I),
}


def infer_artist_country(prompt: str) -> str | None:
    """Return one explicit artist-origin country, or None when no unique hard cue exists.

    Patterns require repertoire/artist nouns, so style and genre labels such as
    ``Italian-style``, ``Italo disco``, ``French house`` and ``German techno`` do not
    become nationality constraints.
    """
    text = " ".join(str(prompt).split())
    matches = {
        country
        for country, patterns in _CONTEXT_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }
    matches.update(
        country
        for country, pattern in _FROM_COUNTRY_PATTERNS.items()
        if pattern.search(text)
    )
    return next(iter(matches)) if len(matches) == 1 else None
