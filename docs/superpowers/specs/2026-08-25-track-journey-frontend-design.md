# Track-to-track journey generation — frontend design spec

Status: approved by user, pending implementation plan.
Scope: bounded-to-architectural (extends an existing, well-understood UI pattern — the
single-seed picker — across multiple files; no new backend work, the API contract already
exists and is merged on `dev`: `POST /api/playlists/generate-from-journey` and its
`/stream` variant, per `docs/superpowers/specs/2026-08-25-track-journey-design.md`).

## Motivation

The backend half of the "journey" generation mode (playlist bridging a user-chosen start
and end track) is implemented and merged. There is currently no way to reach it from the
UI — `frontend/index.html`/`frontend/app.js` only expose "From Prompt" and "From Seed".
This spec adds a third top-level mode, "Journey", reusing the existing single-seed picker
pattern generalized to two independent slots.

## Decisions carried from the earlier design discussion

- Journey is a **third top-level tab** (`data-mode="journey"`) alongside Prompt and Seed,
  not a variant of the Seed tab and not API-only.
- **Both pickers (start and end) are visible simultaneously** — the user can search and
  select either one first, in any order. Not a sequential wizard.
- **No "surprise me" (random Last.fm suggestion) button** for either slot in this version
  — manual search only. (The existing single-seed surprise button is unaffected.)
- **No journey "width"/mode control** — a single fixed generation behavior, matching the
  backend design's decision not to add a strict/balanced/exploratory-style knob for
  journeys.
- **Streaming generation** (`/stream` endpoint, SSE progress messages), matching the
  existing Prompt and Seed experience — not a plain non-streaming call.
- `track_count` is the total including both anchors (matches the backend contract).

## State model

`frontend/app.js`'s `state` object gains two fields alongside the existing
`selectedSeed: null` (`app.js:6`):

```js
journeyStart: null,
journeyEnd: null,
```

## Generalizing the picker functions

The existing single-seed picker functions in `app.js` currently close over the single
`state.selectedSeed` global:

- `selectSeed(seed)` (`app.js:291-325`) — sets `state.selectedSeed`, renders the selected
  card into `#selected-seed`, hides `#seed-results`, shows `#seed-mode-controls`.
- `createSeedResult(seed)` (`app.js:327-348`) — builds one clickable result row, wired to
  call `selectSeed(seed)` on click.
- `renderSeedResults(results)` (`app.js:350-367`) — replaces the contents of
  `#seed-results` with rows from `createSeedResult`.
- `clearSelectedSeed({showResults, guidance})` (`app.js:182-189`) — clears
  `state.selectedSeed`, hides the selected card, optionally re-shows the results list.
- `searchSeed()` (`app.js:402-433`) — reads `#seed-query`, calls `/api/seeds/search`,
  calls `renderSeedResults`.

All five are generalized to take a **slot descriptor** instead of operating on the single
global and the four fixed element IDs (`selected-seed`, `seed-results`, `seed-query`,
`seed-search`... ). A slot descriptor is a small plain object:

```js
{
  key: 'seed' | 'journeyStart' | 'journeyEnd',   // which state field to read/write
  queryId, resultsId, selectedId, guidanceId,    // element IDs for this instance
  label,                                          // e.g. "seed", "starting track", "ending track" — used in the selected-card guidance text
}
```

`selectSeed`/`clearSelectedSeed`'s guidance text (`setSeedGuidance`, `app.js:55-59`) is
generalized to take the target guidance element and a message built from the descriptor's
`label` (e.g. "This playlist will start with “X” by Y." /
"This playlist will end with “X” by Y." for the two journey slots, vs. the
existing seed wording for the `seed` slot) rather than always writing to `#seed-guidance`.
Every other behavior (rendering the selected card, hiding the results list,
calling `updateGenerationControls()` to re-evaluate the Generate button) is unconditional
and shared across all three slot instances — no per-slot callback needed, since
`updateGenerationControls()` is already mode-aware via the generalized
`isGenerationReady()` below.

The existing single-seed call sites (`ensureSeedModeControls`, the seed-mode buttons,
`suggestRandomSeed`, event listeners for `#seed-search`/`#seed-query`) keep working
unchanged by passing the pre-existing IDs as the `seed` slot's descriptor — this is a
refactor of the seed picker's internals, not a behavior change for it. The two journey
slots reuse the exact same functions with their own descriptors and IDs. Seed-mode
controls (`#seed-mode-controls`, strict/balanced/exploratory) are **not** part of the
generalized slot — they stay specific to the single-seed flow, since journey has no mode
control (per the carried decision above).

## Markup (`frontend/index.html`)

New tab button next to the existing two (`index.html:35-38`):

```html
<button class="mode" data-mode="journey" type="button">From Journey</button>
```

New panel, structurally mirroring `#seed-panel` (`index.html:112-135`) but with two
instances of the search/results/selected trio, each labeled and using slot-specific IDs:

```html
<div id="journey-panel" class="hidden">
  <div class="journey-slot">
    <label for="journey-start-query">Starting track</label>
    <div class="inline">
      <input id="journey-start-query" placeholder="Artist, album or song title" autocomplete="off">
      <button id="journey-start-search" class="secondary" type="button" disabled aria-disabled="true">Search</button>
    </div>
    <p id="journey-start-guidance" class="hint hidden" aria-live="polite"></p>
    <div id="journey-start-results" class="seed-results hidden" aria-live="polite"></div>
    <div id="journey-start-selected" class="selected-seed hidden" aria-live="polite"></div>
  </div>
  <div class="journey-slot">
    <label for="journey-end-query">Ending track</label>
    <div class="inline">
      <input id="journey-end-query" placeholder="Artist, album or song title" autocomplete="off">
      <button id="journey-end-search" class="secondary" type="button" disabled aria-disabled="true">Search</button>
    </div>
    <p id="journey-end-guidance" class="hint hidden" aria-live="polite"></p>
    <div id="journey-end-results" class="seed-results hidden" aria-live="polite"></div>
    <div id="journey-end-selected" class="selected-seed hidden" aria-live="polite"></div>
  </div>
</div>
```

Reuses the existing `.seed-results`/`.selected-seed`/`.hint`/`.inline` classes (already
styled) so no new CSS classes are strictly required; a `.journey-slot` wrapper class is
added purely for layout (stacking/spacing the two slots) and styled minimally in the
existing controls/layout CSS file(s) the project already uses for this screen — no new
CSS file (avoids `tests/test_repository_hygiene.py` friction from an unreferenced or
unlinked asset).

## Generation flow

`generate()` (`app.js:478-535`) gets a third branch:

```js
} else if (state.mode === 'journey') {
  if (!state.journeyStart) return message('Search for and select a starting track first.', true);
  if (!state.journeyEnd) return message('Search for and select an ending track first.', true);
  endpoint = '/api/playlists/generate-from-journey/stream';
  request = {
    start: state.journeyStart,
    end: state.journeyEnd,
    track_count: trackCount(),
    options: options(),
  };
}
```

Everything after branch selection (loading-button state, `readGenerationStream`,
`sessionStorage` handoff to `playlist.html`, error handling) is unchanged and shared.

`setMode(mode, selectedButton)` (`app.js:537-547`) gets a third panel toggle:

```js
$('journey-panel').classList.toggle('hidden', mode !== 'journey');
```

`updateGenerationControls()` (`app.js:102-110`) calls
`generationState.isGenerationReady(...)`, which is generalized next.

## `generation-state.js` changes

`isGenerationReady(mode, prompt, selectedSeed)` (`generation-state.js:23-27`) becomes:

```js
function isGenerationReady(mode, prompt, selectedSeed, journeySelection) {
  if (mode === 'prompt') return Boolean(normalizePrompt(prompt));
  if (mode === 'journey') {
    return Boolean(journeySelection?.start) && Boolean(journeySelection?.end);
  }
  return Boolean(selectedSeed);
}
```

Backward compatible: existing call sites passing only 3 arguments keep working exactly as
before for `prompt`/`seed` modes; the caller in `app.js` passes
`{start: state.journeyStart, end: state.journeyEnd}` as the fourth argument.
`tests/generation-state.cjs` gets new cases for the `journey` branch (both selected, only
one selected, neither selected) alongside its existing `prompt`/`seed` cases.

## Secondary integration points

Found by tracing every frontend reference to `mode`/`seed`-specific branching, not called
out in the original backend-only spec:

- **`frontend/playlist-feedback.js`**: `generationFlow()` (`:33-37`) and `requestText()`
  (`:39-51`) branch on `generationRequest?.mode === 'seed'` to build a human-readable
  bug-report body; without a `'journey'` branch, a journey generation's feedback report
  would fall through to `clean(playlist?.prompt, 1950)` — the raw internal
  `_journey_instruction()` prompt text, not a useful summary. Add a `journey` branch
  mirroring the `seed` one, showing the start/end track title and artist instead of the
  internal prompt.
- **`frontend/replacement-history.js:92`**: a regex
  (`/\/api\/playlists\/generate(?:-from-seed)?(?:\?|$)/`) used to detect "this request
  created a new playlist" for diagnostic history. Extend it to also match
  `generate-from-journey`, e.g.
  `/\/api\/playlists\/generate(?:-from-(?:seed|journey))?(?:\?|$)/`.

## Testing

- `tests/generation-state.cjs`: extend for the new `isGenerationReady` journey branch (see
  above). No other pure-JS logic is added that needs `.cjs` coverage — the picker
  generalization only changes DOM wiring, which this project's existing test strategy
  does not unit-test in `.cjs` (the single-seed picker functions aren't unit-tested there
  today either).
- `tests/test_repository_hygiene.py`: run after the `index.html`/`app.js` changes — no new
  JS/CSS files are being added, so this should pass unchanged, but it's the project's
  standard structural check after any frontend file edit.
- Manual verification in a real browser against the scratch container (mirroring how the
  backend half was validated) before considering this done: search and select both
  tracks, generate, confirm the resulting playlist page renders the two anchors at the
  correct ends, confirm the feedback report and diagnostic history show sensible journey
  text.

## Explicitly out of scope

- "Surprise me" random suggestion for either journey slot.
- A journey "width"/mode control.
- Any change to `playlist.html`'s track-rendering itself (no special "anchor" badge on
  the start/end tracks) — not requested, and the response shape's `journey: {start, end}`
  field is additive/optional metadata the page doesn't need to consume for this version.
