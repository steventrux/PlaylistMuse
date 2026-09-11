(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {setLoadingButton} = window.PlaylistMuseCommon;

  const input = $('import-url');
  const button = $('import-url-submit');
  const guidance = $('import-url-guidance');
  let importing = false;

  function setGuidance(error) {
    guidance.replaceChildren();
    if (!error) {
      guidance.classList.add('hidden');
      return;
    }
    guidance.classList.remove('hidden');
    // guidance is display:grid, so it must get exactly one child -- appending
    // text nodes and the link directly as siblings would put each on its own
    // grid row instead of flowing inline.
    const message = document.createElement('p');
    if (error.existingPlaylistId) {
      message.append(document.createTextNode('This playlist was already imported as "'));
      const link = document.createElement('a');
      link.href = `/static/playlist.html?id=${encodeURIComponent(error.existingPlaylistId)}`;
      link.textContent = error.existingPlaylistName;
      message.append(link, document.createTextNode('".'));
    } else {
      message.textContent = error.message || String(error);
    }
    guidance.append(message);
  }

  function updateAvailability() {
    const enabled = Boolean(input.value.trim()) && !importing;
    button.disabled = !enabled;
    button.setAttribute('aria-disabled', String(!enabled));
  }

  async function fetchImportPreview(url) {
    const response = await fetch('/api/youtube/playlists/import-preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url}),
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || `HTTP ${response.status}`);
    }
    if (!response.ok) {
      const detail = payload.detail;
      if (detail && typeof detail === 'object' && detail.playlist_id) {
        const error = new Error(`This playlist was already imported as "${detail.playlist_name}".`);
        error.existingPlaylistId = detail.playlist_id;
        error.existingPlaylistName = detail.playlist_name;
        throw error;
      }
      throw new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`);
    }
    return payload;
  }

  async function importFromUrl() {
    if (button.disabled || importing) return;
    const url = input.value.trim();
    if (!url) return;

    importing = true;
    updateAvailability();
    const resetButton = setLoadingButton(button, {
      label: 'Importing',
      resetText: 'Import',
      ariaLabel: 'Importing playlist',
    });
    setGuidance(null);

    try {
      const data = await fetchImportPreview(url);
      sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(data));
      sessionStorage.removeItem('playlistmuse-generation-request');
      window.location.assign('/static/playlist.html');
    } catch (error) {
      setGuidance(error);
      importing = false;
      resetButton();
      updateAvailability();
    }
  }

  button.addEventListener('click', () => void importFromUrl());
  input.addEventListener('input', updateAvailability);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void importFromUrl();
    }
  });
})();
