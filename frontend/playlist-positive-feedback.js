(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ENDPOINT = '/api/quality/local-feedback';
  const CONFIRMED_LABEL = 'Noted, thanks!';
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

  function markCaptured(playlist) {
    // Persisted on the same stored playlist object (which is wholly replaced by
    // a fresh one on every new generation, so this naturally resets for the next
    // playlist) so the button stays disabled across a page reload/revisit of the
    // same freshly generated playlist, not just for the remainder of this one
    // in-memory page load -- without this, reloading let the button re-enable
    // and send duplicate capture entries for a playlist already marked.
    playlist.playlistmuseTasteCaptured = true;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));
  }

  function playlistDocument(playlist) {
    const document = JSON.parse(JSON.stringify(playlist));
    delete document.library_id;
    delete document.tags;
    // Client-only session markers -- must never reach a persisted snapshot.
    delete document.playlistmuseFreshlyGenerated;
    delete document.playlistmuseTasteCaptured;
    return document;
  }

  async function sendPositiveFeedback() {
    const playlist = readStoredJson(STORAGE_KEY);
    if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;
    const generationRequest = readStoredJson(REQUEST_KEY);
    const label = button.querySelector('.compact-action-label');

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
      // Stays disabled with the confirmation label for the rest of the page's
      // session (deliberately not restored): the button remains visible after
      // capture, and re-enabling it would let repeat clicks create duplicate
      // near-identical entries that inflate the "seen N times" grouping count
      // in the review panel.
      if (label) label.textContent = CONFIRMED_LABEL;
      else button.textContent = CONFIRMED_LABEL;
      markCaptured(playlist);
    } catch (error) {
      button.disabled = false;
      console.warn('Positive feedback could not be saved:', error);
    }
  }

  const playlist = readStoredJson(STORAGE_KEY);
  if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;
  if (!playlist.playlistmuseFreshlyGenerated) return;

  button.classList.remove('hidden');
  if (playlist.playlistmuseTasteCaptured) {
    // Not setting textContent here: action-controls.js decorates this button
    // (rebuilding its icon/label children) right after this script runs, and
    // mutating textContent first would just be overwritten by that decoration.
    // Disabling alone needs no DOM children, so it survives the redecoration.
    button.disabled = true;
  } else {
    button.addEventListener('click', sendPositiveFeedback);
  }
})();
