# Track-to-Track Journey Generation (Frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Journey" tab to the main generation screen so a user can pick a starting
and ending track and generate a playlist that bridges them, using the already-merged
`POST /api/playlists/generate-from-journey` (+ `/stream`) backend endpoints.

**Architecture:** Add a third top-level mode alongside the existing Prompt and Seed tabs.
Generalize the existing single-seed picker functions in `frontend/app.js` (search, render
results, select, clear) to operate on a "slot" descriptor instead of the single
`state.selectedSeed` global, so the same functions serve the seed picker and two new,
independent journey pickers (start/end, both visible at once) without duplicating logic.
Journey has no track-count field (the backend enforces a hardcoded maximum and may return
fewer tracks than that) and no "surprise me" button. After a successful journey
generation, if the AI returned a very short bridge, the user is asked to confirm before
navigating to the playlist page.

**Tech Stack:** Plain JS (no framework, no build step, IIFEs attaching to `window`), Node's
built-in test runner (`node:test`) for `frontend/generation-state.js`'s pure logic.

**Spec:** `docs/superpowers/specs/2026-08-25-track-journey-frontend-design.md` (see its
"Amendment" section for the no-length-field / short-bridge-confirmation decisions this
plan implements from the start).

## Global Constraints

- No em-dashes or `--` in new UI copy shown directly in the product interface (button
  labels, guidance text, confirmation dialogs). The one exception this plan touches is
  `frontend/playlist-feedback.js`'s existing GitHub-issue-body text, which already uses a
  real em dash in its pre-existing `seed` branch (`Seed: ${title} — ${artists}`) for a
  developer-facing bug report, not end-user UI copy — the new `journey` branch in that
  same file may mirror that existing convention for consistency rather than introduce a
  different separator only for itself.
- No new CSS file and no new JS file (avoids `tests/test_repository_hygiene.py`
  friction from an unreferenced or unlinked asset) — all changes land in existing files.
- Every modified static asset referenced with a `?v=N` cache-busting query string in
  `frontend/index.html` and/or `frontend/playlist.html` must have that `N` bumped by 1 in
  every place it appears, per CLAUDE.md's cache-busting convention. Current versions before
  this plan: `app.js?v=21` (index.html only), `controls.css?v=8` (index.html AND
  playlist.html), `generation-state.js?v=3` (index.html only), `replacement-history.js?v=3`
  (index.html AND playlist.html), `playlist-feedback.js?v=1` (playlist.html only).
- The existing single-seed picker's behavior (search, select, "surprise me", seed-mode
  controls) must be unchanged after the generalization in Task 2 — verified by manual
  smoke-testing the Seed tab alongside the new Journey tab in Task 5, since this codebase
  has no automated UI test harness for these DOM-driven functions (confirmed: the
  single-seed picker functions aren't unit-tested in `.cjs` today either).
- Journey's search inputs/buttons are **not** added to `GENERATION_LOCKED_CONTROL_IDS`
  (`app.js`), matching the existing (if debatable) precedent that `seed-query`/`seed-search`
  aren't locked during generation today either — this plan doesn't introduce new
  inconsistency by changing that only for journey.

---

## Task 1: Generalize `isGenerationReady` for the journey mode

**Files:**
- Modify: `frontend/generation-state.js:23-27`, `frontend/index.html:316` (cache-bust
  bump)
- Test: `tests/generation-state.cjs`

**Interfaces:**
- Produces: `isGenerationReady(mode, prompt, selectedSeed, journeySelection)` — the fourth
  parameter is optional and ignored for `mode !== 'journey'`, so every existing call site
  (`prompt`/`seed` modes) is unaffected by omitting it. `journeySelection` is
  `{start, end}`; ready requires both to be truthy. Consumed by Task 2's
  `updateGenerationControls()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/generation-state.cjs` (after the existing `'seed search is disabled...'`
test at the end of the file):

```js
test('journey generation is ready only after both tracks are selected', () => {
  assert.equal(generationState.isGenerationReady('journey', 'ignored', null, {}), false);
  assert.equal(
    generationState.isGenerationReady('journey', 'ignored', null, {start: {video_id: 's'}}),
    false,
  );
  assert.equal(
    generationState.isGenerationReady(
      'journey',
      'ignored',
      null,
      {start: {video_id: 's'}, end: {video_id: 'e'}},
    ),
    true,
  );
});

test('prompt and seed readiness are unaffected by a missing journeySelection argument', () => {
  assert.equal(generationState.isGenerationReady('prompt', 'rock', null), true);
  assert.equal(
    generationState.isGenerationReady('seed', '', {video_id: 'seed-1'}),
    true,
  );
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/generation-state.cjs`
Expected: FAIL — `isGenerationReady` doesn't have a `journey` branch yet, so the first new
test's first assertion returns `false` as expected by luck but the third assertion (both
tracks selected) also returns `false` instead of `true` (current code falls through to
`Boolean(selectedSeed)`, which is `null` for a journey call). The test file should fail to
pass as a whole.

- [ ] **Step 3: Implement**

Replace `frontend/generation-state.js:23-27`:

```js
  function isGenerationReady(mode, prompt, selectedSeed) {
    return mode === 'prompt'
      ? Boolean(normalizePrompt(prompt))
      : Boolean(selectedSeed);
  }
```

with:

```js
  function isGenerationReady(mode, prompt, selectedSeed, journeySelection) {
    if (mode === 'prompt') return Boolean(normalizePrompt(prompt));
    if (mode === 'journey') {
      return Boolean(journeySelection?.start) && Boolean(journeySelection?.end);
    }
    return Boolean(selectedSeed);
  }
```

Bump the cache-busting version for `generation-state.js` in `frontend/index.html:316`
from `?v=3` to `?v=4`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/generation-state.cjs`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add frontend/generation-state.js frontend/index.html tests/generation-state.cjs
git commit -m "feat: add journey branch to isGenerationReady"
```

---

## Task 2: Journey tab markup and picker integration

**Files:**
- Modify: `frontend/index.html:35-38` (mode tabs), `frontend/index.html:111-136` (new
  panel + track-count wrapper id), `frontend/index.html:319` (app.js cache-bust bump),
  `frontend/index.html:14` (controls.css cache-bust bump, also update
  `frontend/playlist.html:14` since it references the same file),
  `frontend/controls.css` (minimal `.journey-slot` spacing rule), `frontend/app.js`
  (state, slot descriptors, generalized picker functions, `generate()`, `setMode()`,
  event wiring, init calls)
- Test: none automated (see Global Constraints — this class of DOM-driven code has no
  existing `.cjs`/Python coverage in this codebase); verified structurally in this task's
  Step 6 and manually end-to-end in Task 5.

**Interfaces:**
- Consumes: `generationState.isGenerationReady` (Task 1, now journey-aware).
- Produces: `state.journeyStart`, `state.journeyEnd` (selected track objects or `null`);
  `PICKER_SLOTS` (a `{seed, journeyStart, journeyEnd}` map of slot descriptors) — internal
  to `app.js`, not consumed by other tasks, but documented here since Task 3/4 readers may
  want to understand the shape.

- [ ] **Step 1: Add the tab button**

In `frontend/index.html`, inside the `.mode-tabs` block (`index.html:35-38`), add a third
button after the Seed one:

```html
      <div class="mode-tabs" role="tablist" aria-label="Playlist creation mode">
        <button class="mode active" data-mode="prompt" type="button">From Prompt</button>
        <button class="mode" data-mode="seed" type="button">From Seed</button>
        <button class="mode" data-mode="journey" type="button">From Journey</button>
      </div>
```

- [ ] **Step 2: Add the journey panel markup**

Immediately after the `</div>` that closes `#seed-panel` (`index.html:130`, right before
`<div id="generation-controls" class="hidden">` at `index.html:132`), insert:

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

- [ ] **Step 3: Give the "Tracks" field a wrapper id**

In `frontend/index.html:132-137`, change:

```html
      <div id="generation-controls" class="hidden">
        <div class="grid filters compact-filters">
          <label>Tracks
            <input id="track-count" type="number" min="5" max="100" value="25">
          </label>
        </div>
```

to:

```html
      <div id="generation-controls" class="hidden">
        <div class="grid filters compact-filters">
          <label id="track-count-field">Tracks
            <input id="track-count" type="number" min="5" max="100" value="25">
          </label>
        </div>
```

- [ ] **Step 4: Add minimal spacing CSS for the two journey slots**

Add to `frontend/controls.css` (near the existing `.selected-seed` rules, around
`controls.css:275`):

```css
.journey-slot + .journey-slot {
  margin-top: 1.5rem;
}
```

- [ ] **Step 5: Generalize the picker functions in `frontend/app.js`**

Add `journeyStart: null`, `journeyEnd: null`, `journeyStartSearching: false`,
`journeyEndSearching: false` to the `state` object (`app.js:4-14`):

```js
  const state = {
    mode: 'prompt',
    selectedSeed: null,
    seedMode: 'balanced',
    seedSearching: false,
    seedSuggestionLoading: false,
    lastFmConfigured: false,
    generating: false,
    setupMode: 'single',
    setupStep: 'ai',
    journeyStart: null,
    journeyEnd: null,
    journeyStartSearching: false,
    journeyEndSearching: false,
  };
```

Add a `PICKER_SLOTS` const right after the existing `SEED_MODES` const
(`app.js:25-38`):

```js
  const PICKER_SLOTS = {
    seed: {
      key: 'selectedSeed',
      searchingKey: 'seedSearching',
      queryId: 'seed-query',
      searchId: 'seed-search',
      resultsId: 'seed-results',
      selectedId: 'selected-seed',
      guidanceId: 'seed-guidance',
      guidance: (track) => `This playlist will be built around “${track.title}” by ${track.artists}.`,
      clearedGuidance: 'Choose a track to use as the musical reference for the new playlist.',
    },
    journeyStart: {
      key: 'journeyStart',
      searchingKey: 'journeyStartSearching',
      queryId: 'journey-start-query',
      searchId: 'journey-start-search',
      resultsId: 'journey-start-results',
      selectedId: 'journey-start-selected',
      guidanceId: 'journey-start-guidance',
      guidance: (track) => `This journey will start with “${track.title}” by ${track.artists}.`,
      clearedGuidance: 'Choose the track this journey should start from.',
    },
    journeyEnd: {
      key: 'journeyEnd',
      searchingKey: 'journeyEndSearching',
      queryId: 'journey-end-query',
      searchId: 'journey-end-search',
      resultsId: 'journey-end-results',
      selectedId: 'journey-end-selected',
      guidanceId: 'journey-end-guidance',
      guidance: (track) => `This journey will end with “${track.title}” by ${track.artists}.`,
      clearedGuidance: 'Choose the track this journey should end at.',
    },
  };
```

Replace `setSeedGuidance` (`app.js:55-59`):

```js
  function setSeedGuidance(text = '') {
    const guidance = $('seed-guidance');
    guidance.textContent = text;
    guidance.classList.toggle('hidden', !text);
  }
```

with:

```js
  function setSlotGuidance(slot, text = '') {
    const guidance = $(slot.guidanceId);
    guidance.textContent = text;
    guidance.classList.toggle('hidden', !text);
  }
```

Replace `updateGenerationControls` (`app.js:102-110`):

```js
  function updateGenerationControls() {
    const ready = generationState.isGenerationReady(
      state.mode,
      $('prompt').value,
      state.selectedSeed,
    );
    $('generation-controls').classList.toggle('hidden', !ready);
    if (!ready && state.mode === 'prompt') message('');
  }
```

with:

```js
  function updateGenerationControls() {
    const ready = generationState.isGenerationReady(
      state.mode,
      $('prompt').value,
      state.selectedSeed,
      {start: state.journeyStart, end: state.journeyEnd},
    );
    $('generation-controls').classList.toggle('hidden', !ready);
    if (!ready && state.mode === 'prompt') message('');
  }
```

Replace `updateSeedSearchAvailability` (`app.js:112-120`):

```js
  function updateSeedSearchAvailability() {
    const enabled = generationState.isSeedSearchEnabled(
      $('seed-query').value,
      state.seedSearching,
    );
    const button = $('seed-search');
    button.disabled = !enabled;
    button.setAttribute('aria-disabled', String(!enabled));
  }
```

with:

```js
  function updateSlotSearchAvailability(slot) {
    const enabled = generationState.isSeedSearchEnabled(
      $(slot.queryId).value,
      state[slot.searchingKey],
    );
    const button = $(slot.searchId);
    button.disabled = !enabled;
    button.setAttribute('aria-disabled', String(!enabled));
  }
```

Replace `setSeedSearching` (`app.js:122-127`):

```js
  function setSeedSearching(searching) {
    state.seedSearching = searching;
    $('seed-search').textContent = searching ? 'Searching…' : 'Search';
    updateSeedSearchAvailability();
    updateSeedSurpriseAvailability();
  }
```

with:

```js
  function setSlotSearching(slot, searching) {
    state[slot.searchingKey] = searching;
    $(slot.searchId).textContent = searching ? 'Searching…' : 'Search';
    updateSlotSearchAvailability(slot);
    if (slot === PICKER_SLOTS.seed) updateSeedSurpriseAvailability();
  }
```

Replace `clearSelectedSeed` (`app.js:182-189`):

```js
  function clearSelectedSeed({showResults = false, guidance = ''} = {}) {
    state.selectedSeed = null;
    $('selected-seed').classList.add('hidden');
    $('seed-mode-controls')?.classList.add('hidden');
    if (showResults) $('seed-results').classList.remove('hidden');
    setSeedGuidance(guidance);
    updateGenerationControls();
  }
```

with:

```js
  function clearSlotTrack(slot, {showResults = false, guidance = ''} = {}) {
    state[slot.key] = null;
    $(slot.selectedId).classList.add('hidden');
    if (slot === PICKER_SLOTS.seed) $('seed-mode-controls')?.classList.add('hidden');
    if (showResults) $(slot.resultsId).classList.remove('hidden');
    setSlotGuidance(slot, guidance);
    updateGenerationControls();
  }
```

Replace `selectSeed` (`app.js:291-325`):

```js
  function selectSeed(seed) {
    state.selectedSeed = seed;
    $('selected-seed').replaceChildren();

    const artwork = document.createElement('img');
    artwork.src = seed.thumbnail_url || '';
    artwork.alt = '';

    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = seed.title;
    const meta = document.createElement('span');
    meta.textContent = [seed.artists, seed.album, seed.duration].filter(Boolean).join(' · ');
    copy.append(title, meta);

    const change = document.createElement('button');
    change.type = 'button';
    change.className = 'secondary compact-button';
    change.textContent = 'Change';
    change.addEventListener('click', () => {
      clearSelectedSeed({
        showResults: true,
        guidance: 'Choose a track to use as the musical reference for the new playlist.',
      });
      message('');
    });

    $('selected-seed').append(artwork, copy, change);
    $('selected-seed').classList.remove('hidden');
    $('seed-results').classList.add('hidden');
    $('seed-mode-controls').classList.remove('hidden');
    setSeedGuidance(`This playlist will be built around “${seed.title}” by ${seed.artists}.`);
    updateGenerationControls();
    message('');
  }
```

with:

```js
  function selectSlotTrack(slot, track) {
    state[slot.key] = track;
    const selectedEl = $(slot.selectedId);
    selectedEl.replaceChildren();

    const artwork = document.createElement('img');
    artwork.src = track.thumbnail_url || '';
    artwork.alt = '';

    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = track.title;
    const meta = document.createElement('span');
    meta.textContent = [track.artists, track.album, track.duration].filter(Boolean).join(' · ');
    copy.append(title, meta);

    const change = document.createElement('button');
    change.type = 'button';
    change.className = 'secondary compact-button';
    change.textContent = 'Change';
    change.addEventListener('click', () => {
      clearSlotTrack(slot, {showResults: true, guidance: slot.clearedGuidance});
      message('');
    });

    selectedEl.append(artwork, copy, change);
    selectedEl.classList.remove('hidden');
    $(slot.resultsId).classList.add('hidden');
    if (slot === PICKER_SLOTS.seed) $('seed-mode-controls').classList.remove('hidden');
    setSlotGuidance(slot, slot.guidance(track));
    updateGenerationControls();
    message('');
  }
```

Replace `createSeedResult` (`app.js:327-348`):

```js
  function createSeedResult(seed) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seed-result';

    const artwork = document.createElement('img');
    artwork.src = seed.thumbnail_url || '';
    artwork.alt = '';
    artwork.loading = 'lazy';

    const copy = document.createElement('span');
    copy.className = 'seed-result-copy';
    const title = document.createElement('strong');
    title.textContent = seed.title;
    const meta = document.createElement('small');
    meta.textContent = [seed.artists, seed.album, seed.duration].filter(Boolean).join(' · ');
    copy.append(title, meta);

    button.append(artwork, copy);
    button.addEventListener('click', () => selectSeed(seed));
    return button;
  }
```

with:

```js
  function createSlotResult(slot, track) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seed-result';

    const artwork = document.createElement('img');
    artwork.src = track.thumbnail_url || '';
    artwork.alt = '';
    artwork.loading = 'lazy';

    const copy = document.createElement('span');
    copy.className = 'seed-result-copy';
    const title = document.createElement('strong');
    title.textContent = track.title;
    const meta = document.createElement('small');
    meta.textContent = [track.artists, track.album, track.duration].filter(Boolean).join(' · ');
    copy.append(title, meta);

    button.append(artwork, copy);
    button.addEventListener('click', () => selectSlotTrack(slot, track));
    return button;
  }
```

Replace `renderSeedResults` (`app.js:350-367`):

```js
  function renderSeedResults(results) {
    const container = $('seed-results');
    container.replaceChildren();

    if (!results.length) {
      const empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = 'No matching songs found.';
      container.append(empty);
      container.classList.remove('hidden');
      return;
    }

    const fragment = document.createDocumentFragment();
    results.forEach((seed) => fragment.append(createSeedResult(seed)));
    container.append(fragment);
    container.classList.remove('hidden');
  }
```

with:

```js
  function renderSlotResults(slot, results) {
    const container = $(slot.resultsId);
    container.replaceChildren();

    if (!results.length) {
      const empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = 'No matching songs found.';
      container.append(empty);
      container.classList.remove('hidden');
      return;
    }

    const fragment = document.createDocumentFragment();
    results.forEach((track) => fragment.append(createSlotResult(slot, track)));
    container.append(fragment);
    container.classList.remove('hidden');
  }
```

Replace `searchSeed` (`app.js:402-433`):

```js
  async function searchSeed() {
    if (state.seedSearching) return;

    const query = $('seed-query').value.trim();
    if (query.length < 2) return message('Enter an artist or song title.', true);

    clearSelectedSeed();
    setSeedSearching(true);
    setSeedGuidance('');
    message('Searching YouTube Music…');

    try {
      const data = await readJson(
        await fetch(`/api/seeds/search?q=${encodeURIComponent(query)}&limit=8`),
        {flattenValidationErrors: true},
      );
      const results = data.results || [];

      renderSeedResults(results);
      setSeedGuidance(
        results.length
          ? 'Choose a track to use as the musical reference for the new playlist.'
          : '',
      );
      message(results.length ? '' : 'No matching songs found.', !results.length);
    } catch (error) {
      setSeedGuidance('');
      message(error.message || String(error), true);
    } finally {
      setSeedSearching(false);
    }
  }
```

with:

```js
  async function searchSlot(slot) {
    if (state[slot.searchingKey]) return;

    const query = $(slot.queryId).value.trim();
    if (query.length < 2) return message('Enter an artist or song title.', true);

    clearSlotTrack(slot);
    setSlotSearching(slot, true);
    setSlotGuidance(slot, '');
    message('Searching YouTube Music…');

    try {
      const data = await readJson(
        await fetch(`/api/seeds/search?q=${encodeURIComponent(query)}&limit=8`),
        {flattenValidationErrors: true},
      );
      const results = data.results || [];

      renderSlotResults(slot, results);
      setSlotGuidance(slot, results.length ? slot.clearedGuidance : '');
      message(results.length ? '' : 'No matching songs found.', !results.length);
    } catch (error) {
      setSlotGuidance(slot, '');
      message(error.message || String(error), true);
    } finally {
      setSlotSearching(slot, false);
    }
  }
```

`suggestRandomSeed()` (unchanged elsewhere, `app.js:369-400`) calls two of the
just-renamed functions directly — `clearSelectedSeed()` and `setSeedGuidance('')` — which
no longer exist after the renames above and must be updated or `suggestRandomSeed` will
throw a `ReferenceError` the first time "surprise me" is clicked. Inside that function,
replace:

```js
      clearSelectedSeed();
      $('seed-results').classList.add('hidden');
      $('seed-query').value = query;
      $('seed-query').dispatchEvent(new Event('input', {bubbles: true}));
      setSeedGuidance('');
```

with:

```js
      clearSlotTrack(PICKER_SLOTS.seed);
      $('seed-results').classList.add('hidden');
      $('seed-query').value = query;
      $('seed-query').dispatchEvent(new Event('input', {bubbles: true}));
      setSlotGuidance(PICKER_SLOTS.seed, '');
```

- [ ] **Step 6: Run the JS syntax check**

Run: `node --check frontend/app.js`
Expected: no output (success) — confirms the generalization compiles before wiring
`generate()`/`setMode()` in the next step.

- [ ] **Step 7: Add the journey branch to `generate()`, including the short-bridge confirmation**

Replace the whole `generate()` function (`app.js:478-535`):

```js
  async function generate() {
    const button = $('generate');
    if (button.disabled) return;
    if (state.generating) return;

    let endpoint;
    let request;

    if (state.mode === 'prompt') {
      const prompt = normalizedPrompt();
      if (!prompt) return message('Describe the playlist you want.', true);
      endpoint = '/api/playlists/generate/stream';
      request = {
        prompt,
        track_count: trackCount(),
        options: options(),
        complexity_score: window.PlaylistMusePromptComplexity?.currentScore?.() ?? null,
      };
    } else {
      if (!state.selectedSeed) return message('Search for and select a seed track first.', true);
      endpoint = '/api/playlists/generate-from-seed/stream';
      request = {
        seed: state.selectedSeed,
        seed_mode: state.seedMode,
        track_count: trackCount(),
        options: options(),
      };
    }

    const resetGeneratingButton = setLoadingButton(button, {
      label: 'Generating',
      resetText: 'Generate playlist',
      ariaLabel: 'Generating playlist',
    });
    setGenerationInputsLocked(true);
    message('Interpreting your request and drafting the playlist…');

    try {
      const data = await readGenerationStream(
        await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(request),
        }),
        (event) => message(event.message),
      );
      sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(data));
      sessionStorage.setItem('playlistmuse-generation-request', JSON.stringify({
        mode: state.mode,
        ...request,
      }));
      window.location.assign('/static/playlist.html');
    } catch (error) {
      setGenerationInputsLocked(false);
      resetGeneratingButton();
      message(error.message || String(error), true);
    }
  }
```

with:

```js
  async function generate() {
    const button = $('generate');
    if (button.disabled) return;
    if (state.generating) return;

    let endpoint;
    let request;

    if (state.mode === 'prompt') {
      const prompt = normalizedPrompt();
      if (!prompt) return message('Describe the playlist you want.', true);
      endpoint = '/api/playlists/generate/stream';
      request = {
        prompt,
        track_count: trackCount(),
        options: options(),
        complexity_score: window.PlaylistMusePromptComplexity?.currentScore?.() ?? null,
      };
    } else if (state.mode === 'journey') {
      if (!state.journeyStart) return message('Search for and select a starting track first.', true);
      if (!state.journeyEnd) return message('Search for and select an ending track first.', true);
      endpoint = '/api/playlists/generate-from-journey/stream';
      request = {
        start: state.journeyStart,
        end: state.journeyEnd,
        options: options(),
      };
    } else {
      if (!state.selectedSeed) return message('Search for and select a seed track first.', true);
      endpoint = '/api/playlists/generate-from-seed/stream';
      request = {
        seed: state.selectedSeed,
        seed_mode: state.seedMode,
        track_count: trackCount(),
        options: options(),
      };
    }

    const resetGeneratingButton = setLoadingButton(button, {
      label: 'Generating',
      resetText: 'Generate playlist',
      ariaLabel: 'Generating playlist',
    });
    setGenerationInputsLocked(true);
    message('Interpreting your request and drafting the playlist…');

    try {
      const data = await readGenerationStream(
        await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(request),
        }),
        (event) => message(event.message),
      );

      if (state.mode === 'journey' && data.tracks.length - 2 < 3) {
        const proceed = window.confirm(
          `PlaylistMuse only found a ${data.tracks.length - 2}-track bridge between `
          + 'these two songs. Continue anyway?',
        );
        if (!proceed) {
          setGenerationInputsLocked(false);
          resetGeneratingButton();
          message('');
          return;
        }
      }

      sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(data));
      sessionStorage.setItem('playlistmuse-generation-request', JSON.stringify({
        mode: state.mode,
        ...request,
      }));
      window.location.assign('/static/playlist.html');
    } catch (error) {
      setGenerationInputsLocked(false);
      resetGeneratingButton();
      message(error.message || String(error), true);
    }
  }
```

- [ ] **Step 8: Update `setMode()`**

Replace `setMode` (`app.js:537-547`):

```js
  function setMode(mode, selectedButton) {
    state.mode = mode;
    document.querySelectorAll('.mode').forEach((button) => {
      button.classList.toggle('active', button === selectedButton);
      button.setAttribute('aria-selected', String(button === selectedButton));
    });
    $('prompt-panel').classList.toggle('hidden', mode !== 'prompt');
    $('seed-panel').classList.toggle('hidden', mode !== 'seed');
    updateGenerationControls();
    message('');
  }
```

with:

```js
  function setMode(mode, selectedButton) {
    state.mode = mode;
    document.querySelectorAll('.mode').forEach((button) => {
      button.classList.toggle('active', button === selectedButton);
      button.setAttribute('aria-selected', String(button === selectedButton));
    });
    $('prompt-panel').classList.toggle('hidden', mode !== 'prompt');
    $('seed-panel').classList.toggle('hidden', mode !== 'seed');
    $('journey-panel').classList.toggle('hidden', mode !== 'journey');
    $('track-count-field').classList.toggle('hidden', mode === 'journey');
    updateGenerationControls();
    message('');
  }
```

- [ ] **Step 9: Update event wiring and init calls**

Replace this block (`app.js:549-560`):

```js
  ensureSeedModeControls();
  $('generate').addEventListener('click', generate);
  $('prompt').addEventListener('input', updateGenerationControls);
  $('seed-search').addEventListener('click', searchSeed);
  $('seed-surprise').addEventListener('click', () => void suggestRandomSeed());
  $('seed-query').addEventListener('input', updateSeedSearchAvailability);
  $('seed-query').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void searchSeed();
    }
  });
```

with:

```js
  ensureSeedModeControls();
  $('generate').addEventListener('click', generate);
  $('prompt').addEventListener('input', updateGenerationControls);
  $('seed-surprise').addEventListener('click', () => void suggestRandomSeed());

  Object.values(PICKER_SLOTS).forEach((slot) => {
    $(slot.searchId).addEventListener('click', () => void searchSlot(slot));
    $(slot.queryId).addEventListener('input', () => updateSlotSearchAvailability(slot));
    $(slot.queryId).addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        void searchSlot(slot);
      }
    });
  });
```

Replace the tail init calls (`app.js:588-591`):

```js
  updateSeedSearchAvailability();
  updateSeedSurpriseAvailability();
  updateGenerationControls();
  void showInitialSetupIfRequired();
```

with:

```js
  Object.values(PICKER_SLOTS).forEach((slot) => updateSlotSearchAvailability(slot));
  updateSeedSurpriseAvailability();
  updateGenerationControls();
  void showInitialSetupIfRequired();
```

- [ ] **Step 10: Bump cache-busting versions**

In `frontend/index.html`: `app.js?v=21` → `?v=22` (`index.html:319`); `controls.css?v=8`
→ `?v=9` (`index.html:14`). In `frontend/playlist.html`: `controls.css?v=8` → `?v=9`
(`playlist.html:14`, same file, must match).

- [ ] **Step 11: Run the JS syntax and structural checks**

Run:
```bash
node --check frontend/app.js
node --check frontend/index.html 2>/dev/null || true  # index.html is not JS; skip if this errors on non-JS content
venv/bin/python -m pytest -q tests/test_repository_hygiene.py
```
Expected: `app.js` syntax check passes with no output; `test_repository_hygiene.py`
passes (no missing or orphaned asset references introduced).

- [ ] **Step 12: Commit**

```bash
git add frontend/index.html frontend/playlist.html frontend/controls.css frontend/app.js
git commit -m "feat: add Journey tab with dual track pickers and generation wiring"
```

---

## Task 3: Journey-aware feedback report text

**Files:**
- Modify: `frontend/playlist-feedback.js:33-51`, `frontend/playlist.html:140`
  (cache-bust bump)
- Test: none automated (see Global Constraints; `tests/test_playlist_feedback.py` doesn't
  test per-mode branching in `generationFlow`/`requestText` today either).

**Interfaces:**
- Consumes: `generationRequest.mode === 'journey'`, `generationRequest.start`,
  `generationRequest.end` — the exact shape `app.js`'s `generate()` (Task 2) writes into
  `sessionStorage` under `playlistmuse-generation-request`.

- [ ] **Step 1: Update `generationFlow` and `requestText`**

Replace `frontend/playlist-feedback.js:33-51`:

```js
  function generationFlow(generationRequest, refinements) {
    if (refinements.length) return 'Playlist Studio refinement';
    if (generationRequest?.mode === 'seed') return 'Seed-track generation';
    return 'Initial prompt generation';
  }

  function requestText(playlist, generationRequest) {
    if (generationRequest?.mode === 'prompt') {
      return clean(generationRequest.prompt || playlist?.prompt, 1950);
    }
    if (generationRequest?.mode === 'seed') {
      const seed = generationRequest.seed || {};
      const title = clean(seed.title, 300);
      const artists = clean(seed.artists || seed.artist, 300);
      const mode = clean(generationRequest.seed_mode, 80);
      return `Seed: ${title || 'Unknown track'} — ${artists || 'Unknown artist'}${mode ? `\nSimilarity mode: ${mode}` : ''}`;
    }
    return clean(playlist?.prompt, 1950);
  }
```

with:

```js
  function generationFlow(generationRequest, refinements) {
    if (refinements.length) return 'Playlist Studio refinement';
    if (generationRequest?.mode === 'seed') return 'Seed-track generation';
    if (generationRequest?.mode === 'journey') return 'Track-to-track journey generation';
    return 'Initial prompt generation';
  }

  function requestText(playlist, generationRequest) {
    if (generationRequest?.mode === 'prompt') {
      return clean(generationRequest.prompt || playlist?.prompt, 1950);
    }
    if (generationRequest?.mode === 'seed') {
      const seed = generationRequest.seed || {};
      const title = clean(seed.title, 300);
      const artists = clean(seed.artists || seed.artist, 300);
      const mode = clean(generationRequest.seed_mode, 80);
      return `Seed: ${title || 'Unknown track'} — ${artists || 'Unknown artist'}${mode ? `\nSimilarity mode: ${mode}` : ''}`;
    }
    if (generationRequest?.mode === 'journey') {
      const start = generationRequest.start || {};
      const end = generationRequest.end || {};
      const startText = `${clean(start.title, 300) || 'Unknown track'} — ${clean(start.artists, 300) || 'Unknown artist'}`;
      const endText = `${clean(end.title, 300) || 'Unknown track'} — ${clean(end.artists, 300) || 'Unknown artist'}`;
      return `Journey start: ${startText}\nJourney end: ${endText}`;
    }
    return clean(playlist?.prompt, 1950);
  }
```

- [ ] **Step 2: Bump the cache-busting version**

In `frontend/playlist.html:140`: `playlist-feedback.js?v=1` → `?v=2`.

- [ ] **Step 3: Run the JS syntax check and the existing feedback test file**

Run:
```bash
node --check frontend/playlist-feedback.js
venv/bin/python -m pytest -q tests/test_playlist_feedback.py
```
Expected: no syntax errors; existing feedback tests still pass unchanged (this file's
tests don't exercise the `journey` branch, so they can't regress from this addition).

- [ ] **Step 4: Commit**

```bash
git add frontend/playlist-feedback.js frontend/playlist.html
git commit -m "feat: describe journey generations in the feedback report text"
```

---

## Task 4: Recognize journey requests in the diagnostic history

**Files:**
- Modify: `frontend/replacement-history.js:92`, `frontend/index.html:310`,
  `frontend/playlist.html:132` (cache-bust bump, same file referenced in both pages)
- Test: none automated (no existing test file covers `replacement-history.js`'s URL
  matching today).

**Interfaces:** None new — this is a self-contained regex change with no external callers
to update.

**Pre-flight finding (ruled on by the controller during SDD execution, not part of the
original spec):** the existing regex requires `?` or end-of-string immediately after
`generate` or `generate-from-seed`, but every real generation request in this app (prompt
and seed alike, `frontend/app.js:489,498`) hits the `/stream`-suffixed endpoint
(`/api/playlists/generate-from-seed/stream`, etc.), which this regex never matches —
confirmed empirically. `isNewPlaylist` gates clearing the replacement-history
`sessionStorage` key on a new generation (`replacement-history.js:110-111`), so today that
clear silently never fires for any real request — a pre-existing, unrelated bug that just
happens to live on the line this task already touches. Ruling: fix the `/stream` gap in
the same edit rather than ship a journey addition to an already-inert pattern.

- [ ] **Step 1: Extend the URL-matching regex (and fix the pre-existing `/stream` gap)**

In `frontend/replacement-history.js:92`, change:

```js
    const isNewPlaylist = /\/api\/playlists\/generate(?:-from-seed)?(?:\?|$)/.test(url);
```

to:

```js
    const isNewPlaylist = /\/api\/playlists\/generate(?:-from-(?:seed|journey))?(?:\/stream)?(?:\?|$)/.test(url);
```

Verified against every real generation URL this app issues plus the negative cases, via
`node -e`:
```
/api/playlists/generate                          -> true
/api/playlists/generate/stream                    -> true
/api/playlists/generate-from-seed                  -> true
/api/playlists/generate-from-seed/stream           -> true
/api/playlists/generate-from-journey                -> true
/api/playlists/generate-from-journey/stream         -> true
/api/playlists/replace-track                        -> false
/api/playlists/generate-from-seed/streamX           -> false
```

- [ ] **Step 2: Bump the cache-busting version**

`replacement-history.js?v=3` → `?v=4` in both `frontend/index.html:310` and
`frontend/playlist.html:132` (same file, both references must match).

- [ ] **Step 3: Run the JS syntax check**

Run: `node --check frontend/replacement-history.js`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add frontend/replacement-history.js frontend/index.html frontend/playlist.html
git commit -m "fix: recognize generate-from-journey requests and the /stream suffix in diagnostic history"
```

---

## Task 5: Full regression pass and manual browser verification

**Files:** None (verification only).

**Interfaces:** None.

- [ ] **Step 1: Run the full Python test suite**

Run: `venv/bin/python -m pytest -q`
Expected: all tests pass (no backend files were touched by this plan, so this is a pure
regression check — in particular `tests/test_repository_hygiene.py` and
`tests/test_playlist_feedback.py` again).

- [ ] **Step 2: Run both required lint invocations**

Run:
```bash
ruff check --select E4,E7,E9,F backend tests
ruff check --select B,C4,SIM,UP backend
```
Expected: no findings (this plan touches no backend files, so this should already be
clean, but it's the project's standard pre-commit gate).

- [ ] **Step 3: Run the JavaScript checks**

Run:
```bash
find frontend -maxdepth 1 -name "*.js" -print0 | xargs -0 -n1 node --check
find tests -maxdepth 1 -name "*.cjs" -print0 | xargs -0 -n1 node --check
node --test tests/*.cjs
```
Expected: no errors; all `.cjs` tests pass, including the two new journey cases from
Task 1.

- [ ] **Step 4: Manual verification in a real browser against the scratch container**

Rebuild and redeploy the scratch container from this branch (mirroring how the backend
half of this feature was verified earlier), then in a real browser:

1. Open the app, confirm three tabs are visible: From Prompt, From Seed, From Journey.
2. Click "From Journey". Confirm both "Starting track" and "Ending track" pickers are
   visible at once, the shared "Tracks" number field is hidden, and the
   exclude-live/covers/remixes checkboxes are still visible.
3. Search for and select a starting track, then search for and select an ending track
   (in either order). Confirm the Generate button only becomes enabled once both are
   selected.
4. Click Generate. Confirm the same progress messages used by Prompt/Seed appear during
   generation, and on success you land on `playlist.html` with the starting track first
   and the ending track last.
5. Switch back to "From Seed" and confirm the single-seed picker (search, select,
   "surprise me", similarity mode buttons) still works exactly as before — this is the
   regression check for Task 2's generalization.
6. If a generation happens to return a short bridge (fewer than 3 tracks between the
   anchors), confirm the confirmation dialog appears and that cancelling it returns to the
   generation screen with inputs re-enabled rather than navigating away.

- [ ] **Step 5: Report status**

If every command above is clean and the manual walkthrough behaves as described, the
track-journey feature (backend + frontend) is complete. If anything fails, fix it in
place before considering this plan complete.
