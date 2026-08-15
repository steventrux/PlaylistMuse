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

  function setSeedGuidance(text = '') {
    const guidance = $('seed-guidance');
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

  function updateSeedSearchAvailability() {
    const enabled = generationState.isSeedSearchEnabled(
      $('seed-query').value,
      state.seedSearching,
    );
    const button = $('seed-search');
    button.disabled = !enabled;
    button.setAttribute('aria-disabled', String(!enabled));
  }

  function setSeedSearching(searching) {
    state.seedSearching = searching;
    $('seed-search').textContent = searching ? 'Searching…' : 'Search';
    updateSeedSearchAvailability();
    updateSeedSurpriseAvailability();
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

  function clearSelectedSeed({showResults = false, guidance = ''} = {}) {
    state.selectedSeed = null;
    $('selected-seed').classList.add('hidden');
    $('seed-mode-controls')?.classList.add('hidden');
    if (showResults) $('seed-results').classList.remove('hidden');
    setSeedGuidance(guidance);
    updateGenerationControls();
  }

  function dispatchSetupStepEvent(step) {
    window.dispatchEvent(new Event(
      step === 'youtube'
        ? 'playlistmuse-youtube-settings-opened'
        : 'playlistmuse-ai-settings-opened',
    ));
  }

  function renderSetup() {
    const onboarding = state.setupMode === 'onboarding';
    const aiStep = state.setupStep === 'ai';
    const intro = $('setup-intro');

    $('setup-eyebrow').textContent = onboarding
      ? 'Initial configuration'
      : 'Configuration';
    $('setup-title').textContent = onboarding
      ? 'Set up PlaylistMuse'
      : aiStep ? 'AI Settings' : 'YouTube Music Settings';

    intro.textContent = onboarding
      ? 'Configure the AI provider first, then optionally connect YouTube Music for direct playlist publishing.'
      : '';
    intro.classList.toggle('hidden', !onboarding);

    $('setup-progress').classList.toggle('hidden', !onboarding);
    $('setup-navigation').classList.toggle('hidden', !onboarding);
    $('setup-ai-step').classList.toggle('hidden', !aiStep);
    $('setup-youtube-step').classList.toggle('hidden', aiStep);

    $('setup-progress-ai').classList.toggle('active', aiStep);
    $('setup-progress-ai').classList.toggle('complete', !aiStep);
    $('setup-progress-youtube').classList.toggle('active', !aiStep);
    $('setup-progress-youtube').classList.remove('complete');

    $('setup-back').classList.toggle('hidden', aiStep);
    $('setup-next').classList.toggle('hidden', !aiStep);
    $('setup-finish').classList.toggle('hidden', aiStep);

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

      clearSelectedSeed();
      $('seed-results').classList.add('hidden');
      $('seed-query').value = query;
      $('seed-query').dispatchEvent(new Event('input', {bubbles: true}));
      setSeedGuidance('');
      message('');
    } catch (error) {
      message(error.message || String(error), true);
    } finally {
      state.seedSuggestionLoading = false;
      updateSeedSurpriseAvailability();
    }
  }

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
      request = {prompt, track_count: trackCount(), options: options()};
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
  $('seed-search').addEventListener('click', searchSeed);
  $('seed-surprise').addEventListener('click', () => void suggestRandomSeed());
  $('seed-query').addEventListener('input', updateSeedSearchAvailability);
  $('seed-query').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void searchSeed();
    }
  });

  window.addEventListener('playlistmuse-lastfm-status', (event) => {
    state.lastFmConfigured = Boolean(event.detail?.configured);
    updateSeedSurpriseAvailability();
  });

  document.querySelectorAll('.mode').forEach((button) => button.addEventListener('click', () => {
    setMode(button.dataset.mode, button);
  }));

  $('ai-open-settings').addEventListener('click', () => {
    window.PlaylistMuseSettingsOverlay?.open('ai');
  });
  $('close-setup').addEventListener('click', closeSetup);
  $('setup-skip').addEventListener('click', closeSetup);
  $('setup-finish').addEventListener('click', closeSetup);
  $('setup-next').addEventListener('click', () => {
    state.setupStep = 'youtube';
    renderSetup();
  });
  $('setup-back').addEventListener('click', () => {
    state.setupStep = 'ai';
    renderSetup();
  });

  updateSeedSearchAvailability();
  updateSeedSurpriseAvailability();
  updateGenerationControls();
  void showInitialSetupIfRequired();
})();
