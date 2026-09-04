(() => {
  'use strict';

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
  };
  const elementCache = new Map();
  const $ = (id) => {
    if (!elementCache.has(id)) {
      elementCache.set(id, document.getElementById(id));
    }
    return elementCache.get(id);
  };
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;
  const generationState = window.PlaylistMuseGenerationState;

  const SEED_MODES = {
    strict: {
      label: 'Strict',
      help: 'Stay very close to the seed. Similarity takes priority over variety and flow.',
    },
    balanced: {
      label: 'Balanced',
      help: 'Keep the seed central while allowing compatible variety. Recommended.',
    },
    exploratory: {
      label: 'Exploratory',
      help: 'Use the seed as a starting point for a wider but still connected journey.',
    },
  };

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
  };

  const GENERATION_LOCKED_CONTROL_IDS = [
    'prompt',
    'track-count',
    'exclude-live',
    'exclude-covers',
    'exclude-remixes',
    'prompt-surprise',
    'seed-surprise',
  ];

  function message(text = '', error = false) {
    $('status').textContent = text;
    $('status').classList.toggle('error', error);
  }

  function setSlotGuidance(slot, text = '') {
    const guidance = $(slot.guidanceId);
    guidance.textContent = text;
    guidance.classList.toggle('hidden', !text);
  }

  function options() {
    return {
      exclude_live: $('exclude-live').checked,
      exclude_covers: $('exclude-covers').checked,
      exclude_remixes: $('exclude-remixes').checked,
    };
  }

  function trackCount() {
    return generationState.clampTrackCount($('track-count').value);
  }

  function normalizedPrompt() {
    return generationState.normalizePrompt($('prompt').value);
  }

  function updateSeedSurpriseAvailability() {
    const button = $('seed-surprise');
    if (!button) return;
    button.hidden = !state.lastFmConfigured;
    const disabled = (
      !state.lastFmConfigured
      || state.seedSearching
      || state.seedSuggestionLoading
      || state.generating
    );
    button.disabled = disabled;
    button.setAttribute('aria-disabled', String(disabled));
  }

  function setGenerationInputsLocked(locked) {
    state.generating = locked;
    GENERATION_LOCKED_CONTROL_IDS.forEach((id) => {
      const control = $(id);
      if (!control) return;
      control.disabled = locked;
      control.setAttribute('aria-disabled', String(locked));
    });
    updateSeedSurpriseAvailability();
  }

  function updateGenerationControls() {
    const ready = generationState.isGenerationReady(
      state.mode,
      $('prompt').value,
      state.selectedSeed,
    );
    $('generation-controls').classList.toggle('hidden', !ready);
    if (!ready && state.mode === 'prompt') message('');
  }

  function updateSlotSearchAvailability(slot) {
    const enabled = generationState.isSeedSearchEnabled(
      $(slot.queryId).value,
      state[slot.searchingKey],
    );
    const button = $(slot.searchId);
    button.disabled = !enabled;
    button.setAttribute('aria-disabled', String(!enabled));
  }

  function setSlotSearching(slot, searching) {
    state[slot.searchingKey] = searching;
    $(slot.searchId).textContent = searching ? 'Searching…' : 'Search';
    updateSlotSearchAvailability(slot);
    if (slot === PICKER_SLOTS.seed) updateSeedSurpriseAvailability();
  }

  function updateSeedModeControls() {
    const controls = $('seed-mode-controls');
    if (!controls) return;
    controls.querySelectorAll('[data-seed-mode]').forEach((button) => {
      const selected = button.dataset.seedMode === state.seedMode;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    $('seed-mode-help').textContent = SEED_MODES[state.seedMode].help;
  }

  function ensureSeedModeControls() {
    if (document.getElementById('seed-mode-controls')) return;

    const controls = document.createElement('section');
    controls.id = 'seed-mode-controls';
    controls.className = 'seed-mode-controls hidden';
    controls.setAttribute('aria-label', 'Seed similarity mode');

    const label = document.createElement('span');
    label.className = 'seed-mode-label';
    label.textContent = 'Similarity';

    const buttons = document.createElement('div');
    buttons.className = 'seed-mode-buttons';
    buttons.setAttribute('role', 'group');
    buttons.setAttribute('aria-label', 'Choose how closely the playlist follows the seed');

    Object.entries(SEED_MODES).forEach(([value, definition]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary seed-mode-button';
      button.dataset.seedMode = value;
      button.textContent = definition.label;
      button.addEventListener('click', () => {
        state.seedMode = value;
        updateSeedModeControls();
      });
      buttons.append(button);
    });

    const help = document.createElement('p');
    help.id = 'seed-mode-help';
    help.className = 'hint seed-mode-help';
    help.setAttribute('aria-live', 'polite');

    controls.append(label, buttons, help);
    $('selected-seed').insertAdjacentElement('afterend', controls);
    elementCache.set('seed-mode-controls', controls);
    elementCache.set('seed-mode-help', help);
    updateSeedModeControls();
  }

  function clearSlotTrack(slot, {showResults = false, guidance = ''} = {}) {
    state[slot.key] = null;
    $(slot.selectedId).classList.add('hidden');
    if (slot === PICKER_SLOTS.seed) $('seed-mode-controls')?.classList.add('hidden');
    if (showResults) $(slot.resultsId).classList.remove('hidden');
    setSlotGuidance(slot, guidance);
    updateGenerationControls();
  }

  const SETUP_STEPS = ['ai', 'youtube', 'lastfm'];
  const SETUP_STEP_EVENTS = {
    ai: 'playlistmuse-ai-settings-opened',
    youtube: 'playlistmuse-youtube-settings-opened',
    lastfm: 'playlistmuse-lastfm-settings-opened',
  };
  const SETUP_STEP_TITLES = {
    ai: 'AI Settings',
    youtube: 'YouTube Music Settings',
    lastfm: 'Last.fm Settings',
  };
  const SETUP_NEXT_LABELS = {
    ai: 'Continue to YouTube Music',
    youtube: 'Continue to Last.fm',
  };

  function dispatchSetupStepEvent(step) {
    const eventName = SETUP_STEP_EVENTS[step];
    if (eventName) window.dispatchEvent(new Event(eventName));
  }

  function renderSetup() {
    const onboarding = state.setupMode === 'onboarding';
    const stepIndex = SETUP_STEPS.indexOf(state.setupStep);
    const lastStep = stepIndex === SETUP_STEPS.length - 1;
    const intro = $('setup-intro');

    $('setup-eyebrow').textContent = onboarding
      ? 'Initial configuration'
      : 'Configuration';
    $('setup-title').textContent = onboarding
      ? 'Set up PlaylistMuse'
      : SETUP_STEP_TITLES[state.setupStep];

    intro.textContent = onboarding
      ? "Start with an AI provider — it's required to generate playlists. "
        + 'YouTube Music and Last.fm are optional and can be connected now or later from Settings.'
      : '';
    intro.classList.toggle('hidden', !onboarding);

    $('setup-progress').classList.toggle('hidden', !onboarding);
    $('setup-navigation').classList.toggle('hidden', !onboarding);
    $('setup-ai-step').classList.toggle('hidden', state.setupStep !== 'ai');
    $('setup-youtube-step').classList.toggle('hidden', state.setupStep !== 'youtube');
    $('setup-lastfm-step')?.classList.toggle('hidden', state.setupStep !== 'lastfm');

    SETUP_STEPS.forEach((step, index) => {
      const item = $(`setup-progress-${step}`);
      if (!item) return;
      item.classList.toggle('active', step === state.setupStep);
      item.classList.toggle('complete', index < stepIndex);
    });

    $('setup-back').classList.toggle('hidden', stepIndex === 0);
    $('setup-next').classList.toggle('hidden', lastStep);
    $('setup-next').textContent = SETUP_NEXT_LABELS[state.setupStep] || 'Continue';
    $('setup-finish').classList.toggle('hidden', !lastStep);

    dispatchSetupStepEvent(state.setupStep);
  }

  function openSetup(step = 'ai', mode = 'single') {
    state.setupMode = mode;
    state.setupStep = step;
    renderSetup();

    const dialog = $('setup-dialog');
    if (!dialog.open) dialog.showModal();
  }

  function closeSetup() {
    const dialog = $('setup-dialog');
    if (dialog.open) dialog.close();
  }

  async function acknowledgeInitialSetup() {
    try {
      await readJson(await fetch('/api/onboarding/acknowledge', {
        method: 'POST',
        cache: 'no-store',
      }));
    } catch {
      // The wizard is already visible; warnings remain available if persistence fails.
    }
  }

  async function showInitialSetupIfRequired() {
    try {
      const status = await readJson(await fetch('/api/onboarding', {
        cache: 'no-store',
      }));
      if (!status.required) return;

      openSetup('ai', 'onboarding');
      void acknowledgeInitialSetup();
    } catch {
      // Setup warnings remain available if onboarding state cannot be checked.
    }
  }

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
    window.PlaylistMusePreview?.stop();
    $(slot.resultsId).classList.add('hidden');
    if (slot === PICKER_SLOTS.seed) $('seed-mode-controls').classList.remove('hidden');
    setSlotGuidance(slot, slot.guidance(track));
    updateGenerationControls();
    message('');
  }

  function createSlotResult(slot, track) {
    const item = document.createElement('div');
    item.className = 'seed-result';
    item.tabIndex = 0;
    item.setAttribute('role', 'button');
    item.setAttribute('aria-label', `Select ${track.title || 'this track'} as the seed`);

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

    item.append(artwork, copy);

    const previewButton = document.createElement('button');
    previewButton.type = 'button';
    previewButton.className = 'secondary track-action preview-track-button hidden';
    let previewUrl = null;
    let previewLookupStarted = false;

    function startPreviewLookup() {
      if (previewLookupStarted || !window.PlaylistMusePreview) return;
      previewLookupStarted = true;
      window.PlaylistMusePreview.lookup(track).then((url) => {
        if (!url) return;
        previewUrl = url;
        previewButton.classList.remove('hidden');
      });
    }

    item.addEventListener('mouseenter', startPreviewLookup);
    item.addEventListener('focus', startPreviewLookup);

    previewButton.addEventListener('click', (event) => {
      event.stopPropagation();
      if (!previewUrl) return;
      window.PlaylistMusePreview.toggle(previewUrl, {
        onStart: () => window.PlaylistMuseActionControls?.setPreviewPlaying(previewButton, true),
        onStop: () => window.PlaylistMuseActionControls?.setPreviewPlaying(previewButton, false),
      });
    });
    item.append(previewButton);

    item.addEventListener('click', (event) => {
      if (event.target.closest('button')) return;
      selectSlotTrack(slot, track);
    });
    item.addEventListener('keydown', (event) => {
      if (event.target !== item || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      selectSlotTrack(slot, track);
    });

    return item;
  }

  function renderSlotResults(slot, results) {
    const container = $(slot.resultsId);
    window.PlaylistMusePreview?.stop();
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

  async function suggestRandomSeed() {
    if (
      !state.lastFmConfigured
      || state.seedSuggestionLoading
      || state.seedSearching
      || state.generating
    ) return;

    state.seedSuggestionLoading = true;
    updateSeedSurpriseAvailability();
    message('Finding a random seed on Last.fm…');

    try {
      const suggestion = await readJson(
        await fetch('/api/lastfm/random-seed', {cache: 'no-store'}),
      );
      const query = String(suggestion.query || '').trim();
      if (!query) throw new Error('Last.fm returned an empty suggestion.');

      clearSlotTrack(PICKER_SLOTS.seed);
      $('seed-results').classList.add('hidden');
      $('seed-query').value = query;
      $('seed-query').dispatchEvent(new Event('input', {bubbles: true}));
      setSlotGuidance(PICKER_SLOTS.seed, '');
      message('');
    } catch (error) {
      message(error.message || String(error), true);
    } finally {
      state.seedSuggestionLoading = false;
      updateSeedSurpriseAvailability();
    }
  }

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

  // Reads a fetch() response streamed as newline-delimited SSE `data: {...}\n\n` frames
  // (see backend/main.py::_stream_generation). Calls onStage(evt) for every `type:"stage"`
  // event as it arrives, and resolves with the final `type:"result"` event's payload, or
  // throws an Error (message including which stage it happened in) for `type:"error"`.
  async function readGenerationStream(response, onStage) {
    if (!response.ok) {
      // Validation errors (e.g. bad request body) never reach the streaming code path on
      // the backend, so the body here is a plain JSON error, not an event stream.
      await readJson(response, {flattenValidationErrors: true});
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handleFrame = (frame) => {
      const line = frame.split('\n').find((item) => item.startsWith('data: '));
      if (!line) return null;
      return JSON.parse(line.slice('data: '.length));
    };

    for (;;) {
      const {done, value} = await reader.read();
      if (value) buffer += decoder.decode(value, {stream: true});
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = handleFrame(frame);
        if (event?.type === 'stage') {
          onStage(event);
        } else if (event?.type === 'result') {
          return event.playlist;
        } else if (event?.type === 'error') {
          const suffix = event.stage_message ? ` (${event.stage_message})` : '';
          throw new Error(`${event.message}${suffix}`);
        }
        boundary = buffer.indexOf('\n\n');
      }
      if (done) break;
    }
    throw new Error('The generation stream ended unexpectedly.');
  }

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


      data.playlistmuseFreshlyGenerated = true;
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

  window.addEventListener('playlistmuse-lastfm-status', (event) => {
    state.lastFmConfigured = Boolean(event.detail?.configured);
    updateSeedSurpriseAvailability();
  });

  document.querySelectorAll('.mode').forEach((button) => button.addEventListener('click', () => {
    setMode(button.dataset.mode, button);
  }));

  $('ai-open-settings').addEventListener('click', () => {
    window.PlaylistMuseCommon.openSettings('ai');
  });
  $('close-setup').addEventListener('click', closeSetup);
  $('setup-skip').addEventListener('click', closeSetup);
  $('setup-finish').addEventListener('click', closeSetup);
  $('setup-next').addEventListener('click', () => {
    const nextIndex = SETUP_STEPS.indexOf(state.setupStep) + 1;
    state.setupStep = SETUP_STEPS[Math.min(nextIndex, SETUP_STEPS.length - 1)];
    renderSetup();
  });
  $('setup-back').addEventListener('click', () => {
    const previousIndex = SETUP_STEPS.indexOf(state.setupStep) - 1;
    state.setupStep = SETUP_STEPS[Math.max(previousIndex, 0)];
    renderSetup();
  });

  Object.values(PICKER_SLOTS).forEach((slot) => updateSlotSearchAvailability(slot));
  updateSeedSurpriseAvailability();
  updateGenerationControls();
  void showInitialSetupIfRequired();
})();
