(() => {
  'use strict';

  const state = { mode: 'prompt', selectedSeed: null };
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

  function message(text = '', error = false) {
    $('status').textContent = text;
    $('status').classList.toggle('error', error);
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

  function openDialog(id, eventName = '') {
    const dialog = $(id);
    if (!dialog.open) dialog.showModal();
    if (eventName) window.dispatchEvent(new Event(eventName));
  }

  function closeDialog(id) {
    const dialog = $(id);
    if (dialog.open) dialog.close();
  }

  function openAiSettings() {
    closeDialog('settings-dialog');
    openDialog('ai-settings-dialog', 'playlistmuse-ai-settings-opened');
  }

  function openYouTubeSettings() {
    closeDialog('settings-dialog');
    openDialog('youtube-settings-dialog', 'playlistmuse-youtube-settings-opened');
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
    });

    $('selected-seed').append(artwork, copy, change);
    $('selected-seed').classList.remove('hidden');
    $('seed-results').classList.add('hidden');
    message('Seed selected. Generate the playlist when ready.');
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
    message('Searching YouTube Music…');

    try {
      const data = await readJson(
        await fetch(`/api/seeds/search?q=${encodeURIComponent(query)}&limit=8`),
        {flattenValidationErrors: true},
      );
      renderSeedResults(data.results || []);
      message(data.results?.length ? 'Choose the seed track.' : 'No matching songs found.', !data.results?.length);
    } catch (error) {
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

  $('settings-btn').addEventListener('click', () => openDialog('settings-dialog'));
  $('close-settings').addEventListener('click', () => closeDialog('settings-dialog'));
  $('open-ai-settings').addEventListener('click', openAiSettings);
  $('open-youtube-settings').addEventListener('click', openYouTubeSettings);
  $('ai-open-settings').addEventListener('click', openAiSettings);
  $('close-ai-settings').addEventListener('click', () => closeDialog('ai-settings-dialog'));
  $('close-youtube-settings').addEventListener('click', () => closeDialog('youtube-settings-dialog'));
})();