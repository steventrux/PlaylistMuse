# Track-to-track journey generation — design spec

Status: approved by user, pending implementation plan.
Scope: architectural (new generation mode, new endpoint pair, new top-level UI tab,
generalization of existing anchor-forcing/retry logic to two anchors instead of one).

## Motivation

Today PlaylistMuse generates playlists from a free-text prompt (`/api/playlists/generate`)
or from a single reference track (`/api/playlists/generate-from-seed`). Users want a third
mode: pick a **starting** track and an **ending** track and have the AI build a playlist
that forms a deliberate, sensible musical path between them — not just tracks similar to
one anchor, but a step-by-step bridge.

## Explicitly out of scope

- **ReccoBeats / audio-feature interpolation as the bridging mechanism.** Already tried and
  rejected for single-seed generation (`generation_runtime_core.py:492-499`): a live
  comparative check found ReccoBeats' `/track/recommendation` output genre-incoherent, and
  audio features (energy/valence/danceability) don't reliably capture genre/cultural
  identity — a K-pop candidate had a near-identical audio profile to an unrelated
  French-house seed. A spike for *this* feature (2026-08-25, throwaway script on branch
  `spike/track-journey`, not merged) confirmed the alternative — pure LLM reasoning grounded
  in Last.fm evidence, no ReccoBeats — produces coherent multi-hop bridges even across very
  distant genre pairs (extreme metal → jazz piano trio; French house → acoustic folk). This
  spec uses that approach exclusively.
- **A journey "width" control** (tight vs. wide bridge, analogous to seed_mode
  strict/balanced/exploratory). The spike showed the model sometimes builds a wider arc than
  strictly necessary when the two anchors are already close (synth-pop → synth-pop still
  routed through disco-funk). Explicitly deferred — user decided a single fixed behavior is
  enough for now; revisit only if real usage shows it's a recurring complaint.
- **N-anchor / multi-waypoint journeys** (3+ tracks). YAGNI — nobody asked for this; the
  two-anchor design below does not need to be generalized speculatively.

## Data model and endpoints

New Pydantic model in `main.py`, next to `SeedGenerateRequest` (`main.py:486-490`), reusing
the existing `SeedTrack` model (`main.py:476-484`) unchanged for both ends — it's already
exactly what `/api/seeds/search` returns, so the frontend picker needs no new backend
search endpoint:

```python
class JourneyGenerateRequest(BaseModel):
    start: SeedTrack
    end: SeedTrack
    track_count: int = Field(default=25, ge=5, le=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)
```

`track_count` is the **total** including both anchors (consistent with
`SeedGenerateRequest.track_count`, which already includes the seed) — user decision.

New endpoints mirroring the seed pair exactly:
- `POST /api/playlists/generate-from-journey` (mirrors `main.py:1532-1538`)
- `POST /api/playlists/generate-from-journey/stream` (mirrors `main.py:1630-1635`)

Both wrapped in `_generate_with_telemetry` (`main.py:1360-1385`) and the same
`ValueError` → 400 / other `Exception` → 502 handling already used by every generation
endpoint.

**Validation**: reject `start`/`end` identifying the same track (`track_identity_key`
match) with a 400 before any AI call — add a `field_validator` on `JourneyGenerateRequest`
mirroring the existing `normalize_prompt` validator pattern (`main.py:261-264`).

## Prompt construction and Last.fm evidence

New `_generate_from_journey_playlist(request)` in `main.py`, structurally mirroring
`_generate_from_seed_playlist` (`main.py:1467-1529`):

1. Fetch Last.fm evidence for **both** anchors concurrently, reusing the same "balanced"
   limit formula the single seed already uses (`_seed_lastfm_evidence_params`'s
   `default_limit`, `main.py:199`) since there's no width control to vary it by:
   ```python
   limit = min(MAX_LASTFM_CONTEXT_TRACKS, max(20, request.track_count * 2))
   start_evidence, end_evidence = await asyncio.gather(
       similar_track_candidates(request.start.artists, request.start.title, limit=limit),
       similar_track_candidates(request.end.artists, request.end.title, limit=limit),
   )
   ```
   `similar_track_candidates` (`lastfm.py:130`) already degrades to `[]` when Last.fm isn't
   configured — no change needed there. This keeps the core mechanism fully functional
   without Last.fm, confirmed acceptable in discussion: the spike's bridge tracks were
   mostly the model's own picks, not verbatim evidence-list entries, so evidence is
   reinforcement, not a requirement.
2. Build the initial prompt requesting `track_count - 2` intermediate tracks, using the
   bridging instruction validated in the spike: first/last track pinned to the exact
   start/end song, every intermediate track must connect to its neighbors (sound, energy,
   mood, instrumentation, scene, or artist affinity), and each track's `reason` field must
   state that connection. Fold both evidence lists in, formatted like
   `_seed_evidence_guidance` (`main.py:679-706`).
3. Call the normal `_generate(prompt, track_count - 2, options)` pipeline — LLM draft,
   catalogue resolution, metadata validation, replenishment rounds — entirely unchanged.

## Anchor enforcement and retry

Both `start` and `end` are inserted **exactly as selected by the user** — never
regenerated or paraphrased by the LLM, and never routed through `resolve_candidates()`'s
exclusion filters (`exclude_live`/`exclude_covers`/`exclude_remixes` don't apply to them),
identical to how the single seed is treated today (`main.py:1510-1523`). Final assembly:
`[start_payload, *bridge_tracks, end_payload]`.

Generalize `_seed_other_tracks` (`main.py:1431-1464`) into a version that checks against a
**set** of forbidden identity keys instead of one (`{start_key, end_key}`), retrying once
(same 2-attempt cap) with both songs explicitly named as forbidden in the repaired prompt
if either reappears among the AI's suggestions. Adjust `_is_seed_track` (`main.py:1425-1428`)
into a small helper that takes a set of keys instead of a single `SeedTrack`.

If both retries still leave a duplicate, raise the same style of `ValueError` used today,
reworded to name both anchor tracks.

## Frontend

New top-level tab "Journey" in `index.html` / `app.js`, alongside the existing Prompt and
Seed tabs. Duplicate the existing seed-picker widget (`createSeedResult`, `selectSeed`,
search wired to `/api/seeds/search`, `app.js:291-364`) into two independent instances
addressed by a `slot: 'start' | 'end'` parameter instead of the single
`state.selectedSeed`. Track-count control and `PlaylistOptions` checkboxes are reused
unchanged. Generate is disabled until both slots have a selection, mirroring the existing
seed-mode guard (`app.js:83-84` pattern generalized to both slots). No width/mode control
(see Explicitly out of scope).

## Edge cases

- **Last.fm not configured**: proceeds with empty evidence on both sides (see above).
- **`start` equals `end`**: rejected with 400 before any AI call.
- **Low `track_count`** (e.g. 5 → 3 bridge tracks): no extra floor needed beyond the
  existing `ge=5`; a 3-track bridge is a degenerate but valid case.
- **Anchors too far apart to fill enough compliant distinct tracks** after both retries:
  same `ValueError` message pattern already used for seed generation shortfalls, reworded
  for two named anchors.
- Anchor tracks are exempt from `exclude_live`/`exclude_covers`/`exclude_remixes`, same as
  the single seed today.

## Testing

- New `tests/test_main_journey.py`, mirroring the existing seed-generation test file:
  request validation (including the `start == end` rejection), forced anchor insertion at
  first/last position, the generalized dual-anchor retry, and error paths (misconfigured
  provider, exhausted retries).
- No automated check for "is this bridge musically sensible" — as established in the
  original feasibility analysis, no deterministic validator exists for pairwise narrative
  coherence. Prompt-wording changes should be spot-checked manually with a
  spike-script-style probe before being considered validated, not just unit-tested.
- `tests/test_repository_hygiene.py`: only relevant if the frontend work adds a new JS/CSS
  file rather than extending `app.js` in place — verify reachability either way.
- Full local suite (`pytest`, both `ruff` invocations, JS `node --check` + `node --test`)
  before commit, per standing project practice.

## Deferred follow-ups (explicitly not part of this feature)

- Journey "width" control (tight vs. wide bridge) — revisit only if real usage shows the
  fixed behavior over-widens noticeably often, beyond the single sanity-check case observed
  in the spike.
- N-anchor / multi-waypoint journeys.
