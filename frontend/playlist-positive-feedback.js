(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ENDPOINT = '/api/quality/local-feedback';
  const CONFIRMED_LABEL = 'Noted, thanks!';
  const CONFIRMED_VISIBLE_MS = 2000;
  const button = document.getElementById('playlist-positive-feedback');
  if (!button) return;
  const {readJson} = window.PlaylistMuseCommon;

  function readStoredJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  function playlistDocument(playlist) {
    const document = JSON.parse(JSON.stringify(playlist));
    delete document.library_id;
    delete document.tags;
    return document;
  }

  async function sendPositiveFeedback() {
    const playlist = readStoredJson(STORAGE_KEY);
    if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;
    const generationRequest = readStoredJson(REQUEST_KEY);
    const label = button.querySelector('.compact-action-label');
    const originalLabel = label ? label.textContent : button.textContent;

    button.disabled = true;
    try {
      await readJson(await fetch(ENDPOINT, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          playlist: playlistDocument(playlist),
          generation_request: generationRequest || null,
        }),
      }));
      if (label) label.textContent = CONFIRMED_LABEL;
      else button.textContent = CONFIRMED_LABEL;
      window.setTimeout(() => {
        if (label) label.textContent = originalLabel;
        else button.textContent = originalLabel;
        button.disabled = false;
      }, CONFIRMED_VISIBLE_MS);
    } catch (error) {
      button.disabled = false;
      console.warn('Positive feedback could not be saved:', error);
    }
  }

  if (new URLSearchParams(window.location.search).has('id')) return;
  const playlist = readStoredJson(STORAGE_KEY);
  if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;

  button.classList.remove('hidden');
  button.addEventListener('click', sendPositiveFeedback);
})();
