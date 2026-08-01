(() => {
  'use strict';

  const state = {
    mode: 'prompt',
    selectedSeed: null,
    setupMode: 'single',
    setupStep: 'ai',
  };
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

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
    return Math.max(5, Math.min(100, Number($('track-count').value) || 25));
  }

  function normalizedPrompt() {
    return $('prompt').value.trim().replace(/\s+/g, ' ').slice(0, 1950);
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

    $('setup-eyebrow').textContent = onboarding
      ? 'Initial configuration'
      : 'Configuration';
    $('setup-title').textContent = onboarding
      ? 'Set up PlaylistMuse'
      : aiStep ? 'AI Settings' : 'YouTube Music Settings';
    $('setup-intro').textContent = onboarding
      ? 'Configure the AI provider first, then optionally connect YouTube Music for direct playlist publishing.'
      : aiStep
        ? 'Configure the AI provider used to generate and refine playlists.'
        : 'Configure and connect the YouTube Music account used for direct publishing.';

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
      state.selectedSeed = null;
      $('selected-seed').classList.add('hidden');
      $('seed-results').classList.remove('hidden');
      setSeedGuidance('Choose a track to use as the musical reference for the new playlist.');
      message('');
    });

    $('selected-seed').append(artwork, copy, change);
    $('selected-seed').classList.remove('hidden');
    $('seed-results').classList.add('hidden');
    setSeedGuidance(`This playlist will be built around “${seed.title}” by ${seed.artists}.`);
    message('');
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

    results.forEach((seed) => {
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
      container.append(button);
    });

    container.classList.remove('hidden');
  }

  async function searchSeed() {
    const query = $('seed-query').value.trim();
    if (query.length < 2) return message('Enter an artist or song title.', true);

    const button = $('seed-search');
    button.disabled = true;
    button.textContent = 'Searching…';
    setSeedGuidance('');
    message('Searching YouTube Music…');

    try {
      const data = await readJson(
        await fetch(`/api/seeds/search?q=${encodeURIComponent(query)}&limit=8`),
        {flattenValidationErrors: true},
      );
      const results = data.results || [];

      if (results.length) {
        state.selectedSeed = null;
        $('selected-seed').classList.add('hidden');
      }

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
      button.disabled = false;
      button.textContent = 'Search';
    }
  }

  async function generate() {
    const button = $('generate');
    if (button.disabled) return;

    let endpoint;
    let request;

    if (state.mode === 'prompt') {
      const prompt = normalizedPrompt();
      if (!prompt) return message('Describe the playlist you want.', true);
      endpoint = '/api/playlists/generate';
      request = { prompt, track_count: trackCount(), options: options() };
    } else {
      if (!state.selectedSeed) return message('Search for and select a seed track first.', true);
      endpoint = '/api/playlists/generate-from-seed';
      request = { seed: state.selectedSeed, track_count: trackCount(), options: options() };
    }

    const resetGeneratingButton = setLoadingButton(button, {
      label: 'Generating',
      resetText: 'Generate playlist',
      ariaLabel: 'Generating playlist',
    });
    message('Generating and resolving tracks on YouTube Music…');

    try {
      const data = await readJson(
        await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(request),
        }),
        {flattenValidationErrors: true},
      );
      sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(data));
      sessionStorage.setItem('playlistmuse-generation-request', JSON.stringify({mode: state.mode, ...request}));
      window.location.assign('/static/playlist.html');
    } catch (error) {
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
    message('');
  }

  $('generate').addEventListener('click', generate);
  $('seed-search').addEventListener('click', searchSeed);
  $('seed-query').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      searchSeed();
    }
  });

  document.querySelectorAll('.mode').forEach((button) => button.addEventListener('click', () => {
    setMode(button.dataset.mode, button);
  }));

  $('ai-open-settings').addEventListener('click', () => openSetup('ai', 'single'));
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

  void showInitialSetupIfRequired();
})();