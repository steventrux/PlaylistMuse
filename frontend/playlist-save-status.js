(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const LIBRARY_ROOT = '/api/library/playlists';
  const LABELS = {
    saving: 'Saving…',
    saved: 'Saved',
    error: 'Save failed',
  };
  const originalFetch = window.fetch.bind(window);
  let activeWrites = 0;
  let batchFailed = false;

  function sessionPlaylist() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    } catch {
      return null;
    }
  }

  function isCurrentDraft() {
    const playlist = sessionPlaylist();
    if (!playlist || !Array.isArray(playlist.tracks) || playlist.youtube_playlist?.url) {
      return false;
    }
    const requestedId = new URLSearchParams(window.location.search).get('id');
    return !requestedId || playlist.library_id === requestedId;
  }

  function ensureStatusElement() {
    let status = document.getElementById('playlist-save-status');
    if (status) return status;

    const titleEditor = document.querySelector('.playlist-title-editor');
    if (!titleEditor) return null;

    status = document.createElement('p');
    status.id = 'playlist-save-status';
    status.className = 'playlist-save-status hidden';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    titleEditor.insertAdjacentElement('afterend', status);
    return status;
  }

  function renderStatus() {
    const status = ensureStatusElement();
    if (!status) return;

    const playlist = sessionPlaylist();
    const fallbackState = playlist?.library_id ? 'saved' : '';
    const state = document.body.dataset.librarySaveState || fallbackState;
    const label = LABELS[state] || '';
    const visible = isCurrentDraft() && Boolean(label);

    status.textContent = visible ? label : '';
    status.dataset.state = visible ? state : '';
    status.title = state === 'error'
      ? 'Autosave failed. Your latest changes may not be stored.'
      : '';
    status.classList.toggle('hidden', !visible);
  }

  function setState(state) {
    document.body.dataset.librarySaveState = state;
    renderStatus();
  }

  function requestMethod(input, init) {
    if (init?.method) return String(init.method).toUpperCase();
    if (input instanceof Request && input.method) return input.method.toUpperCase();
    return 'GET';
  }

  function requestPath(input) {
    const value = input instanceof Request ? input.url : String(input);
    try {
      return new URL(value, window.location.href).pathname;
    } catch {
      return '';
    }
  }

  function isTrackedLibraryWrite(input, init) {
    const method = requestMethod(input, init);
    const path = requestPath(input);
    if (method === 'POST' && path === LIBRARY_ROOT) return true;
    if (method === 'PUT' && /^\/api\/library\/playlists\/[^/]+$/.test(path)) return true;
    if (method !== 'POST' || !path.startsWith(`${LIBRARY_ROOT}/`)) return false;
    return path.endsWith('/tags/suggest') || path.endsWith('/refine-apply');
  }

  window.fetch = async function playlistMuseTrackedFetch(input, init) {
    if (!isTrackedLibraryWrite(input, init)) {
      return originalFetch(input, init);
    }

    if (activeWrites === 0) batchFailed = false;
    activeWrites += 1;
    setState('saving');

    try {
      const response = await originalFetch(input, init);
      if (!response.ok) batchFailed = true;
      return response;
    } catch (error) {
      batchFailed = true;
      throw error;
    } finally {
      activeWrites -= 1;
      if (activeWrites === 0) setState(batchFailed ? 'error' : 'saved');
    }
  };

  new MutationObserver(renderStatus).observe(document.body, {
    attributes: true,
    attributeFilter: ['data-library-save-state'],
  });

  window.addEventListener('playlistmuse-playlist-published', () => {
    window.setTimeout(renderStatus, 0);
  });
  window.addEventListener('pageshow', renderStatus);

  if (sessionPlaylist()?.library_id && !document.body.dataset.librarySaveState) {
    document.body.dataset.librarySaveState = 'saved';
  }
  renderStatus();
})();
