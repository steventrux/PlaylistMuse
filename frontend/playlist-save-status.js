(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const LIBRARY_ROOT = '/api/library/playlists';
  const SAVED_VISIBLE_MS = 1400;
  const LABELS = {
    saving: 'Saving…',
    saved: 'Saved',
    error: 'Save failed',
  };
  const originalFetch = window.fetch.bind(window);
  let activeWrites = 0;
  let batchFailed = false;
  let userChangeArmed = false;
  let visibleCycle = false;
  let hideTimer = null;

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

    status = document.createElement('p');
    status.id = 'playlist-save-status';
    status.className = 'playlist-save-status hidden';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    document.body.append(status);
    return status;
  }

  function hideStatus() {
    clearTimeout(hideTimer);
    hideTimer = null;
    visibleCycle = false;
    userChangeArmed = false;
    const status = ensureStatusElement();
    if (!status) return;
    status.textContent = '';
    status.dataset.state = '';
    status.title = '';
    status.classList.add('hidden');
  }

  function scheduleSavedHide() {
    clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hideStatus, SAVED_VISIBLE_MS);
  }

  function renderStatus() {
    const status = ensureStatusElement();
    if (!status) return;

    const state = document.body.dataset.librarySaveState || '';
    if (!isCurrentDraft()) {
      hideStatus();
      return;
    }

    if (state === 'saving' && userChangeArmed) visibleCycle = true;
    if (!visibleCycle || !LABELS[state]) {
      status.classList.add('hidden');
      return;
    }

    status.textContent = LABELS[state];
    status.dataset.state = state;
    status.title = state === 'error'
      ? 'Autosave failed. Your latest changes may not be stored.'
      : '';
    status.classList.remove('hidden');

    if (state === 'saved') {
      scheduleSavedHide();
    } else {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function setState(state) {
    document.body.dataset.librarySaveState = state;
    renderStatus();
  }

  function armUserChange(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest('.playlist-card') || !isCurrentDraft()) return;
    userChangeArmed = true;
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

  ['input', 'change', 'click', 'dragstart', 'drop'].forEach((eventName) => {
    document.addEventListener(eventName, armUserChange, true);
  });

  new MutationObserver(renderStatus).observe(document.body, {
    attributes: true,
    attributeFilter: ['data-library-save-state'],
  });

  window.addEventListener('playlistmuse-playlist-published', hideStatus);
  window.addEventListener('pageshow', hideStatus);

  hideStatus();
})();
